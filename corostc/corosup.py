import argparse
from pprint import pprint
from sys import stderr
from getpass import getpass

from . import CorosFileType, CorosSportType, CorosTCClient

def main():
    p = argparse.ArgumentParser()
    p.add_argument('-u', '--username')
    p.add_argument('-p', '--password')
    p.add_argument('-T', '--accesstoken', help='Accesstoken or CPL-coros-token cookie')
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
        url = client.upload_activity(open(fitfile, 'rb'), compress=False)
        print(f'{fitfile!r} -> {"<couldn't determine URL>" if url is None else url}')
    else:
        print(f'Uploaded {len(args.fitfile)} files')

if __name__=='__main__':
    main()
