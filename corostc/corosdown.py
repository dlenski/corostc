import argparse
import unicodedata
from pprint import pprint
from sys import stderr, stdout
from getpass import getpass
import os

from . import CorosFileType, CorosSportType, CorosTCClient, COROS_WEB_BASE, COROS_API_BASE

def main():
    p = argparse.ArgumentParser()
    p.add_argument('-u', '--username')
    p.add_argument('-p', '--password')
    p.add_argument('-T', '--accesstoken', help='Accesstoken or CPL-coros-token cookie')
    p.add_argument('activities', nargs='*',
                   help="Activity IDs to download. If unspecified, latest activity of logged-in user.")
    p.add_argument('-t', '--type', type=str.lower, choices=('fit', 'tcx', 'gpx', 'kml', 'csv'), default='fit',
                   help='Format in which to download activities (default is %(default)s')
    p.add_argument('-N', '--number', action='store_true',
                   help='Label activity files by number, rather than by their titles')
    x = p.add_mutually_exclusive_group()
    x.add_argument('-c', '--stdout', action='store_true', help="Write activity to standard input")
    x.add_argument('-d', '--directory', default='',
                   help="Directory in which to store activity files (default is current directory)")
    args = p.parse_args()

    if args.stdout and len(args.activities) > 1:
        p.error('specify at most one activity with -c/--stdout')
    ftype = CorosFileType[args.type.upper()]

    if not args.accesstoken:
        if not args.username:
            print('COROS Training Center Username: ', end='')
            args.username = input()
        if not args.password:
            args.password = getpass('COROS Training Center Password: ')

    client = CorosTCClient(args.username, args.password, args.accesstoken)
    client.connect()

    if not args.activities:
        try:
            act = next(client.list_activities(batch_size=1))
        except StopIteration:
            p.error('No latest activity found for user.')
        else:
            print('Found latest activity: {!r} ({})'.format(act['name'], act['_sportType'].name), file=stderr)
            args.activities = [act['labelId']]

    for activity_id in args.activities:
        uri = COROS_WEB_BASE + '/activity-detail?labelId={}&sportType=100'.format(activity_id)
        try:
            af = client.download_activity(activity_id, file_type=ftype)
        except Exception as exc:
            print("WARNING: Error downloading activity {} (check {}): {}".format(activity_id, uri, exc), file=stderr)
            continue

        if args.stdout:
            f = stdout.buffer
        else:
            filename = None
            if not args.number:
                try:
                    r = client.session.post(COROS_API_BASE + '/activity/detail/query', data=dict(labelId=activity_id, sportType=100))
                    j = client._coros_raise_or_json(r)
                    # hacky sanitization
                    name = unicodedata.normalize('NFKD', j['data']['summary']['name']).encode('ascii', 'ignore').decode('ascii')
                    filename = '_'.join(''.join(c for c in s if c.isalpha() or c=='_') for s in name.split())
                except Exception:
                    pass
            if not filename:
                filename = str(activity_id)
            filename += '.' + args.type
            f = open(os.path.join(args.directory, filename), "wb")

        with f:
            f.write(af)

        # show results
        print("  Wrote {} from {}".format(f.name, uri), file=stderr)

if __name__=='__main__':
    main()
