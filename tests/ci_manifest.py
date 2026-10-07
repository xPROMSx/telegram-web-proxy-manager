"""Inventory and explicit execution-path check; this does not execute suites."""
import json
from pathlib import Path
import sys

import yaml

from ci_plan import HEAVY, REQUIRED

ROOT = Path(__file__).resolve().parents[1]


def check(root=ROOT):
    root = Path(root)
    manifest = json.loads((root / 'tests/suites.json').read_text())
    workflow = yaml.safe_load((root / '.github/workflows/checks.yml').read_text())
    jobs = workflow['jobs']
    assert manifest['schema'] == 1
    assert set(jobs) == {*REQUIRED, 'required'}, 'unexpected/missing job'
    assert jobs['required']['name'] == 'CI / Required'
    assert jobs['required']['if'] in ('always()', '${{ always() }}')
    assert set(jobs['required']['needs']) == set(REQUIRED), 'gate omitted a job'
    for job in jobs.values():
        assert not job.get('continue-on-error', False), 'job failure is ignored'
        for step in job['steps']:
            assert 'if' not in step and not step.get('continue-on-error', False), 'step can bypass coverage'
    gate_step = jobs['required']['steps'][-1]
    assert gate_step['run'].strip() == 'python3 tests/ci_plan.py gate'
    assert gate_step['env'] == {'CI_MODE': '${{ needs.scope.outputs.mode }}',
                                'CI_NEEDS': '${{ toJSON(needs) }}'}
    for job in HEAVY:
        assert jobs[job]['needs'] == ['scope']
        assert jobs[job]['if'] == "needs.scope.outputs.full == 'true'", 'FULL job can be skipped'
    assert 'if' not in jobs['scope']
    assert jobs['static']['if'] == 'always()'
    assert workflow['permissions'] == {'contents': 'read'}
    events = workflow.get('on', workflow.get(True))
    assert set(events) == {'pull_request', 'push'}
    assert events['pull_request'] is None, 'workflow-level PR filtering forbidden'
    assert events['push'] == {'branches': ['main']}

    def commands(job):
        return '\n'.join(' '.join(step['run'].split()) for step in jobs[job]['steps'] if 'run' in step)

    entries = manifest['entrypoints']
    reachable = set(jobs)
    for entry in entries:
        assert ' '.join(entry['command'].split()) in commands(entry['job']), 'entrypoint not executed: ' + entry['path']
        reachable.add(entry['path'])
    assert 'python3 tests/ci_plan.py gate' in commands('required')
    discovery = manifest['discovery']
    assert discovery == {'pattern': 'tests/test_*.py', 'entrypoint': 'tests/run.sh',
                         'command': "python3 -m unittest discover -s tests -p 'test_*.py' -v"}
    assert discovery['entrypoint'] in reachable
    assert discovery['command'] in (root / discovery['entrypoint']).read_text()
    discovered = {str(p.relative_to(root)) for p in root.glob(discovery['pattern'])}
    assert discovered, 'empty discovery'

    pending = list(manifest['indirect_entrypoints']) + list(manifest['helpers']) + list(manifest['builds'])
    while pending:
        progressed = False
        for item in list(pending):
            parent = item['called_by']
            if parent not in reachable:
                continue
            source = commands(parent) if parent in jobs else '\n'.join(
                line for line in (root / parent).read_text().splitlines() if not line.lstrip().startswith('#'))
            assert item['reference'] in source, 'missing helper execution edge: ' + item['path']
            reachable.add(item['path']); pending.remove(item); progressed = True
        assert progressed, 'unreachable helper/build'
    groups = [set(e['path'] for e in entries), discovered,
              set(e['path'] for e in manifest['indirect_entrypoints']),
              set(e['path'] for e in manifest['helpers']), set(e['path'] for e in manifest['builds']),
              set(manifest['fixtures']), set(manifest['metadata'])]
    assert sum(map(len, groups)) == len(set().union(*groups)), 'ambiguous classification'
    known = set().union(*groups)
    actual = {str(p.relative_to(root)) for p in (root / 'tests').rglob('*') if p.is_file()
              and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    assert actual == known, 'unclassified or missing tests: ' + repr(sorted(actual ^ known))
    return dict(files=len(actual), discovered=len(discovered), entrypoint_calls=len(entries),
                helpers=len(manifest['helpers']), builds=len(manifest['builds']), orphan_tests=0)


if __name__ == '__main__':
    try:
        print(json.dumps(check(), sort_keys=True))
    except (AssertionError, KeyError, ValueError, OSError, yaml.YAMLError) as error:
        print('CI manifest: FAIL: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
