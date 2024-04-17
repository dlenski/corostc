import json
import logging
from datetime import date, datetime, timezone, timedelta
from os import path
from hashlib import md5
from itertools import count
from enum import IntEnum
from io import RawIOBase, BytesIO
from tempfile import NamedTemporaryFile
from gzip import GzipFile

try:
    import fitparse
except ImportError:
    fitparse = None
import requests

COROS_API_BASE = 'https://teamapi.coros.com'
CorosFileType = IntEnum('CorosFileType', dict(CSV=0, GPX=1, KML=2, TCX=3, FIT=4))
CorosSportType = IntEnum('CorosSportType', dict(
    Run=100,
    IndoorRun=101,
    TrackRun=103,
    Hike=104,
    MtnClimb=105,
    Bike=200,
    IndoorBike=201,
    PoolSwim=300,
    OpenWater=301,
    Strength=402,
    GymCardio=400,
    GpsCardio=401,
    Ski=500,
    Snowboard=501,
    XcSki=502,
    SkiTouring=503,
    Speedsurfing=706,
    Windsurfing=705,
    Rowing=700,
    IndoorRower=701,
    Whitewater=702,
    Flatwater=704,
    Walk=900))

logging.basicConfig(level=logging.DEBUG)

log = logging.getLogger(__name__)
logging.getLogger('requests').setLevel(logging.ERROR)

class CorosTCClient():
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.session = None
        self.access_token = None

    @staticmethod
    def _coros_raise_or_json(r: requests.Response):
        r.raise_for_status()
        j = r.json()
        if j.get('result') != '0000':
            raise RuntimeError(f'{j.get("message")} (result code {j.get("result")!r})')
        return j

    def connect(self):
        self.session = requests.Session()
        self._authenticate()

    def disconnect(self):
        if self.session:
            self.session.close()
            self.session = None

    def _authenticate(self):
        r = self.session.post(COROS_API_BASE + '/account/login', json=dict(
            account=self.username, pwd=md5(self.password.encode()).hexdigest(), accountType=2))
        j = self._coros_raise_or_json(r)
        self.session.headers['accessToken'] = j['data']['accessToken']

    def list_activities(self, batch_size: int = 100):
        activities = []
        total = None
        for page in count(1):
            start_index = batch_size * (page - 1)
            end_index = start_index + batch_size - 1

            log.debug("fetching page %d of activities (%d through %d) ...", page, start_index, end_index)
            r = self.session.get(COROS_API_BASE + '/activity/query',
                                 params=dict(size=batch_size, pageNumber=page))
            j = self._coros_raise_or_json(r)['data']

            for a in j['dataList']:
                try:
                    a['sportType'] = CorosSportType(a['sportType'])
                except ValueError:
                    pass   # Unknown sport type integer. Just leave it alone.
                a['date'] = date(year=a['date'] // 10000, month=a['date'] // 100 % 100, day=a['date'] % 100)
                stz = a['startTimezone'] = timezone(timedelta(minutes=a['startTimezone']*15))
                etz = a['endTimezone'] = timezone(timedelta(minutes=a['endTimezone']*15))
                a['startTime'] = datetime.fromtimestamp(a['startTime'], stz)
                a['endTime'] = datetime.fromtimestamp(a['endTime'], etz)
                a.update({k: bool(v) for k, v in a.items() if k.startswith(('has', 'is'))})
                activities.append(a)

            if total is None:
                total = j['count']
            assert total == j['count'], \
                f"total activity count changed from {total} to {j['count']} while fetching activities"
            if end_index >= total:
                break

        return activities

    def download_activity(self, activity_id: str, sport_type: int = CorosSportType.Run,
                          file_type: CorosFileType = CorosFileType.FIT):
        url = self.get_download_url(activity_id, sport_type, file_type)
        r = self.session.get(url)
        r.raise_for_status()
        return r.content

    def get_download_url(self, activity_id: str, sport_type: int = CorosSportType.Run,
                         file_type: CorosFileType = CorosFileType.FIT):
        r = self.session.get(
            COROS_API_BASE + '/activity/detail/download',
            params=dict(
                labelId=str(activity_id),
                sportType=int(sport_type),
                fileType=int(file_type),
            ))
        j = self._coros_raise_or_json(r)
        return j['data'].get('fileUrl')

    def upload_activity(self, activity_file: RawIOBase, compress: bool = True):
        fn = path.basename(activity_file.name)
        buf = BytesIO(activity_file.read())

        if compress:
            upload_file = BytesIO()
            with GzipFile(fileobj=upload_file, mode='wb', filename=fn) as gzf:
                gzf.write(buf.read())
            upload_file.seek(0)
            fn += '.gz'
        else:
            upload_file = buf

        r = self.session.post(
            COROS_API_BASE + '/activity/fit/import',
            files=dict(
                jsonParameter=(None, '{}'),   # website sends {'source': 123456, 'timezone': -32}
                sportData=(fn, upload_file.read(), 'application/octet-stream')
            ))

        # FIXME: is anything here meaningful or useful? Is there a better
        # way to figure out the 'labelId' of the uploaded activity?
        self._coros_raise_or_json(r)

        if not fitparse:
            log.warning('Cannot determine activity ID in Coros TC Without python-fitparse')
            return None

        # Find the start time from the uploaded FIT file
        buf.seek(0)
        act = fitparse.FitFile(buf)
        act.parse()
        act_sess = next(act.get_messages(name='session'))
        start_time = act_sess.get_value('start_time')
        if start_time.tzinfo is None:  # Tacit UTC timezone
            start_time = start_time.replace(tzinfo=timezone.utc)
        start_time = start_time.timestamp()

        # Relisting all activities and find the one with a matching 'labelId'
        try:
            return next(a['labelId'] for a in self.list_activities() if abs(a['startTime'] - start_time) < 1.0)
        except StopIteration:
            log.warning(f'Uploaded FIT file with start_time of {start_time}, but cannot find a matching activity in Coros TC')

    def delete_activity(self, activity_id: str):
        r = self.session.get(COROS_API_BASE + '/activity/delete',
                             params=dict(labelId=activity_id))
        self._coros_raise_or_json(r)

    def update_activity(self, activity_id: str, **attrs):
        r = self.session.post(COROS_API_BASE + '/activity/update',
                              json=dict(attrs, labelId=activity_id))
        self._coros_raise_or_json(r)
