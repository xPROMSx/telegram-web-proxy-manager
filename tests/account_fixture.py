#!/usr/bin/env python3
"""Inert account commands for private fresh-transaction fixtures, never host NSS."""
import os
from pathlib import Path
import sys

root = Path(os.environ['FIXTURE_ACCOUNTS'])
root.mkdir(exist_ok=True)
user, group = root / 'passwd', root / 'group'
command, args = Path(sys.argv[0]).name, sys.argv[1:]
uid = gid = '424242'
with (root / 'commands').open('a') as log:
    log.write(command + ' ' + ' '.join(args) + '\n')
if command == 'getent':
    if args in (['passwd'], ['group']):
        path = user if args == ['passwd'] else group
        if path.exists(): print(path.read_text().strip())
        sys.exit(0)
    database, key = args
    path = user if database == 'passwd' else group
    if key not in ('telemt', uid) or not path.exists(): sys.exit(2)
    print(path.read_text().strip())
elif command == 'groupadd':
    if group.exists(): sys.exit(9)
    assert args[args.index('--gid')+1] == gid
    group.write_text('telemt:x:' + gid + ':\n')
elif command == 'useradd':
    if user.exists() or (group.exists() and '--gid' not in args): sys.exit(9)
    if '--gid' in args:
        assert group.exists() and args[args.index('--gid')+1] == gid and args[args.index('--uid')+1] == uid
    else: group.write_text('telemt:x:' + gid + ':\n')
    if os.environ.get('FIXTURE_PARTIAL_USERADD') == '1': sys.exit(1)
    home = args[args.index('--home-dir') + 1]
    user.write_text('telemt:x:' + uid + ':' + gid + '::' + home + ':/usr/sbin/nologin\n')
elif command == 'userdel':
    if os.environ.get('FIXTURE_USERDEL_FAIL') == '1': sys.exit(1)
    user.unlink()
    if os.environ.get('FIXTURE_USERDEL_REMOVES_GROUP') == '1': group.unlink()
elif command == 'groupdel':
    if os.environ.get('FIXTURE_GROUPDEL_FAIL') == '1': sys.exit(1)
    group.unlink()
else:
    sys.exit(2)
