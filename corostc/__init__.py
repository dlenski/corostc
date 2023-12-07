import json
import logging
from os import path
from hashlib import md5
from itertools import count
from enum import IntEnum
from io import RawIOBase, BytesIO
from tempfile import NamedTemporaryFile
from gzip import GzipFile

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

            activities.extend(dict((k, (CorosSportType(v) if k=='sportType' else v))
                                   for (k, v) in a.items()
                                   if k in ('labelId', 'sportType', 'startTime', 'endTime', 'name'))
                              for a in j['dataList'])
            if end_index >= j['count']:

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
        contents = activity_file.read()
        fn = path.basename(activity_file.name)

        if compress:
            ntf = NamedTemporaryFile(suffix='.zip')
            with GzipFile(filename=fn, fileobj=ntf, mode='wb') as gzf:
                gzf.write(contents)
            ntf.seek(0)
            upload_file = ntf
            fn += '.gz'
        else:
            upload_file = BytesIO(contents)

        with activity_file:
            r = self.session.post(
                COROS_API_BASE + f'/activity/fit/import',
                files=dict(
                    jsonParameter=(None, json.dumps(dict(source=1, timezone=-32))),
                    sportData=(fn, upload_file.read(), 'application/octet-stream')
                ))
            # FIXME: is this actually useful at all?
            j = self._coros_raise_or_json(r)

    return j

    def delete_activity(self, activity_id: str):
        r = self.session.get(COROS_API_BASE + '/activity/delete',
                             params=dict(labelId=activity_id))
        self._coros_raise_or_json(r)

    def update_activity(self, activity_id: str, **attrs):
        r = self.session.post(COROS_API_BASE + '/activity/update',
                              json=dict(attrs, labelId=activity_id))
        self._coros_raise_or_json(r)
