import argparse
from pprint import pprint
from sys import stderr
from getpass import getpass

from . import CorosFileType, CorosSportType, CorosTCClient, COROS_WEB_BASE

def main():
    p = argparse.ArgumentParser()
    p.add_argument('-u', '--username')
    p.add_argument('-p', '--password')
    p.add_argument('-T', '--accesstoken', help='Accesstoken or CPL-coros-token cookie')
    p.add_argument('-n', '--name', help='Activity name')
    p.add_argument('fitfile', nargs='+')
    args = p.parse_args()

    if not args.accesstoken:
        if not args.username:
            print('COROS Training Center Username: ', end='')
            args.username = input()
        if not args.password:
            args.password = getpass('COROS Training Center Password: ')

    client = CorosTCClient(args.username, args.password, args.accesstoken)
    client.connect()
    for fitfile in args.fitfile:
        with open(fitfile, 'rb') as f:
            a = client.upload_activity(f)
            if a is None:
                url = "<couldn't determine URL>"
            else:
                client.update_activity(a["labelId"], name=args.name)
                url = f'{COROS_WEB_BASE}/activity-detail?labelId={a["labelId"]}&sportType={a["sportType"]}'
            print(f'{fitfile!r} -> {url}')
    else:
        print(f'Uploaded {len(args.fitfile)} files')

if __name__=='__main__':
    main()
