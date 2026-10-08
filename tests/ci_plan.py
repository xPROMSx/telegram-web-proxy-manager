"""Conservative changed-path plan and the stable required-check decision."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

HEAVY = ('regression', 'telemt', 'lifecycle', 'nginx', 'system26', 'system24', 'arm')
REQUIRED = ('scope', 'static', *HEAVY)
READMES = {'README.md', 'README.en.md', 'README.ru.md'}


def paths_plan(paths):
    return bool(paths) and all(p in READMES or p.startswith('docs/') for p in paths)


def classify(base, head, event, repository='.'):
    full = dict(mode='FULL', docs_only=False, full=True)
    if event not in ('pull_request', 'push'):
        return full | dict(reason='unknown event')
    if any(not re.fullmatch(r'[0-9a-f]{40}', sha or '') or sha == '0' * 40 for sha in (base, head)):
        return full | dict(reason='missing or invalid revision')
    try:
        for sha in (base, head):
            found = subprocess.check_output(['git', 'rev-parse', '--verify', sha + '^{commit}'],
                                            cwd=repository, stderr=subprocess.DEVNULL, timeout=15)
            if found.decode().strip() != sha:
                return full | dict(reason='revision identity differs')
        raw = subprocess.check_output(['git', 'diff', '--no-ext-diff', '--no-textconv',
                                       '--no-renames', '--name-only', '-z', base, head, '--'],
                                      cwd=repository, stderr=subprocess.DEVNULL, timeout=30)
        paths = raw.decode('utf-8').split('\0')
        if paths[-1] != '':
            return full | dict(reason='invalid diff output')
        docs = paths_plan(paths[:-1])
        return dict(mode='DOCS_ONLY' if docs else 'FULL', docs_only=docs, full=not docs,
                    reason='documentation paths only' if docs else 'runtime/unknown path or empty diff')
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return full | dict(reason='diff unavailable')


def gate(mode, needs):
    if mode not in ('DOCS_ONLY', 'FULL') or not isinstance(needs, dict) or set(needs) != set(REQUIRED):
        return False
    return all(isinstance(needs[job], dict) and needs[job].get('result') ==
               ('skipped' if mode == 'DOCS_ONLY' and job in HEAVY else 'success') for job in REQUIRED)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='operation', required=True)
    plan = sub.add_parser('classify')
    plan.add_argument('--base', default='')
    plan.add_argument('--head', default='')
    plan.add_argument('--event', default='')
    sub.add_parser('gate')
    args = parser.parse_args()
    if args.operation == 'gate':
        try:
            accepted = gate(os.environ.get('CI_MODE'), json.loads(os.environ.get('CI_NEEDS', '')))
        except (ValueError, TypeError):
            accepted = False
        print('CI / Required: ' + ('PASS' if accepted else 'FAIL'))
        raise SystemExit(0 if accepted else 1)
    result = classify(args.base, args.head, args.event)
    print(json.dumps(result, sort_keys=True))
    if os.environ.get('GITHUB_OUTPUT'):
        with Path(os.environ['GITHUB_OUTPUT']).open('a') as output:
            for key in ('mode', 'docs_only', 'full'):
                output.write(f'{key}={str(result[key]).lower() if isinstance(result[key], bool) else result[key]}\n')


if __name__ == '__main__':
    main()
