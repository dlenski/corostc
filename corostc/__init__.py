import json
import logging
from datetime import date, datetime, timezone, timedelta
from os import path
from hashlib import md5
from itertools import count
from enum import IntEnum
from io import RawIOBase, BytesIO
from tempfile import NamedTemporaryFile
from typing import Optional, Union
from gzip import GzipFile

try:
    import fitparse
except ImportError:
    fitparse = None
import requests

COROS_WEB_BASE = 'https://training.coros.com'
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
    def __init__(self, username: Optional[str] = None, password: Optional[str] = None, accesstoken: Optional[str] = None):
        self.username = username
        self.password = password
        self.accesstoken = accesstoken
        self.session = None
        self.user_id = self.nickname = None

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
        if self.accesstoken:
            self.session.headers['accessToken'] = self.accesstoken
            r = self.session.get(COROS_API_BASE + '/account/query')
            try:
                j = self._coros_raise_or_json(r)
            except Exception as exc:
                self.accesstoken = None
                log.warning(f'Reauthenticating with accesstoken failed', exc_info=exc)

        if self.accesstoken is None:
            if self.username is None or self.password is None:
                raise RuntimeError('Cannot authenticate without username and password')
            r = self.session.post(COROS_API_BASE + '/account/login', json=dict(
                account=self.username, pwd=md5(self.password.encode()).hexdigest(), accountType=2))
            j = self._coros_raise_or_json(r)

        data = j['data']
        self.session.headers['accessToken'] = self.accesstoken = data['accessToken']
        self.user_id = data['userId']
        self.nickname = data['nickname']
        if self.username:
            assert self.username.lower() == data['email'].lower()
        self.username = data['email']
        log.debug('Authenticated to account %s (email %s, nickname %r)', self.user_id, self.username, self.nickname)

    def list_activities(self, batch_size: int = 100,
                        start: Optional[Union[date, datetime]] = None,
                        end: Optional[Union[date, datetime]] = None):
        activities = []
        total = None
        for page in count(1):
            start_index = batch_size * (page - 1)
            end_index = start_index + batch_size - 1

            log.debug("fetching page %d of activities (%d through %d) ...", page, start_index, end_index)
            r = self.session.get(COROS_API_BASE + '/activity/query',
                                 params=dict(size=batch_size, pageNumber=page,
                                             startDay=start and start.strftime('%Y%m%d'),
                                             endDay=end and end.strftime('%Y%m%d')))
            j = self._coros_raise_or_json(r)['data']

            for a in j['dataList']:
                try:
                    a['_sportType'] = CorosSportType(a['sportType'])
                except ValueError:
                    log.debug('unknown sportType %r for activity %r', a['sportType'], a['labelId'])
                a['_date'] = date(year=a['date'] // 10000, month=a['date'] // 100 % 100, day=a['date'] % 100)
                stz = a['_startTimezone'] = timezone(timedelta(minutes=a['startTimezone']*15))
                etz = a['_endTimezone'] = timezone(timedelta(minutes=a['endTimezone']*15))
                a['_startTime'] = datetime.fromtimestamp(a['startTime'], stz)
                a['_endTime'] = datetime.fromtimestamp(a['endTime'], etz)
                a.update({k: bool(v) for k, v in a.items() if k.startswith(('has', 'is'))})
                yield a

            if total is None:
                total = j['count']
            assert total == j['count'], \
                f"total activity count changed from {total} to {j['count']} while fetching activities"
            if end_index >= total:
                break

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
        try:
            act = fitparse.FitFile(buf)
            act.parse()
            act_sess = next(act.get_messages(name='session'))
            _start_time = act_sess.get_value('start_time')
        except Exception as exc:
            log.warning('Cannot determine FIT file start time', exc_info=exc)
            return None
        assume_utc = _start_time.tzinfo is None
        if assume_utc:  # Tacit UTC timezone
            _start_time = _start_time.replace(tzinfo=timezone.utc)
        log.debug(f'Determined activity start time of {_start_time}{" (assumed UTC)" if assume_utc else ""}')
        start_time = _start_time.timestamp()

        # List activities within ±1 calendar day of start time to find the one
        # with a matching startTime (±1 second)
        try:
            return next(f'{COROS_WEB_BASE}/activity-detail?labelId={a["labelId"]}&sportType={a["sportType"]}'
                        for a in self.list_activities(start=_start_time - timedelta(days=1), end=_start_time + timedelta(days=1))
                        if abs(a['startTime'] - start_time) < 1.0)
        except StopIteration:
            log.warning(f'Uploaded FIT file with start_time of {_start_time}, but cannot find a matching activity in Coros TC')

    def delete_activity(self, activity_id: str):
        r = self.session.get(COROS_API_BASE + '/activity/delete',
                             params=dict(labelId=activity_id))
        self._coros_raise_or_json(r)

    def update_activity(self, activity_id: str, **attrs):
        r = self.session.post(COROS_API_BASE + '/activity/update',
                              json=dict(attrs, labelId=activity_id))
        self._coros_raise_or_json(r)
