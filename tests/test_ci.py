"""Scope/gate refusal and inventory reachability regressions; no runtime suite."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

import ci_docs
import ci_manifest
import ci_plan

ROOT = Path(__file__).resolve().parents[1]


class PlanTests(unittest.TestCase):
    def test_docs_only_paths(self):
        for paths in (['README.md'], ['README.en.md'], ['README.ru.md'], ['docs/OPERATIONS.md'],
                      ['README.md', 'docs/CI-COVERAGE.md']):
            with self.subTest(paths=paths): self.assertTrue(ci_plan.paths_plan(paths))

    def test_every_other_or_empty_path_is_full(self):
        for path in ('install.sh', 'telemt-web-manager.sh', 'lib/safety.py', 'tests/test_ci.py',
                     '.github/workflows/checks.yml', 'assets/fake-sites/cover.css', 'LICENSE',
                     'unknown', 'docs-other/file.md'):
            for paths in ([path], ['README.md', path]):
                with self.subTest(paths=paths): self.assertFalse(ci_plan.paths_plan(paths))
        self.assertFalse(ci_plan.paths_plan([]))

    def test_real_git_diff_includes_deleted_and_renamed_runtime_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL).decode().strip()
            git('init'); git('config', 'user.email', 'ci@example.invalid'); git('config', 'user.name', 'CI')
            (root/'README.md').write_text('first'); git('add', '.'); git('commit', '-m', 'base')
            base = git('rev-parse', 'HEAD')
            (root/'README.md').write_text('second'); git('commit', '-am', 'docs')
            head = git('rev-parse', 'HEAD')
            self.assertEqual(ci_plan.classify(base, head, 'pull_request', root)['mode'], 'DOCS_ONLY')
            (root/'runtime.sh').write_text('runtime'); git('add', '.'); git('commit', '-m', 'runtime')
            base = git('rev-parse', 'HEAD')
            (root/'docs').mkdir(); (root/'runtime.sh').rename(root/'docs/moved.md')
            git('add', '-A'); git('commit', '-m', 'rename')
            self.assertEqual(ci_plan.classify(base, git('rev-parse', 'HEAD'), 'push', root)['mode'], 'FULL')

    def test_uncertainty_never_selects_docs(self):
        for base, head, event in (('', 'a'*40, 'push'), ('0'*40, 'a'*40, 'push'),
                                  ('bad', 'a'*40, 'pull_request'), ('a'*40, '', 'push'),
                                  ('a'*40, 'b'*40, 'unknown')):
            self.assertEqual(ci_plan.classify(base, head, event)['mode'], 'FULL')
        with patch.object(subprocess, 'check_output', side_effect=subprocess.CalledProcessError(1, 'git')):
            self.assertEqual(ci_plan.classify('a'*40, 'b'*40, 'pull_request')['mode'], 'FULL')

    def test_docs_and_full_gate_success(self):
        for mode in ('DOCS_ONLY', 'FULL'):
            needs = {j: {'result': 'skipped' if mode == 'DOCS_ONLY' and j in ci_plan.HEAVY else 'success'}
                     for j in ci_plan.REQUIRED}
            self.assertTrue(ci_plan.gate(mode, needs))

    def test_every_required_full_failure_cancel_skip_or_missing_fails(self):
        healthy = {j: {'result': 'success'} for j in ci_plan.REQUIRED}
        for job in ci_plan.REQUIRED:
            for result in ('failure', 'cancelled', 'skipped', '', None):
                needs = copy.deepcopy(healthy); needs[job]['result'] = result
                with self.subTest(job=job, result=result): self.assertFalse(ci_plan.gate('FULL', needs))
            needs = copy.deepcopy(healthy); del needs[job]
            self.assertFalse(ci_plan.gate('FULL', needs))

    def test_docs_gate_requires_policy_skips_and_real_static_success(self):
        needs = {j: {'result': 'skipped' if j in ci_plan.HEAVY else 'success'} for j in ci_plan.REQUIRED}
        for job in ci_plan.REQUIRED:
            wrong = copy.deepcopy(needs); wrong[job]['result'] = 'success' if job in ci_plan.HEAVY else 'skipped'
            self.assertFalse(ci_plan.gate('DOCS_ONLY', wrong))
        self.assertFalse(ci_plan.gate(None, needs)); self.assertFalse(ci_plan.gate('FULL', []))

    def test_gate_command_exit_status_is_fail_closed(self):
        for raw, mode in (('{', 'FULL'), ('{}', 'FULL'), ('{}', 'DOCS_ONLY'), ('{}', 'unknown')):
            result = subprocess.run(['python3', str(ROOT/'tests/ci_plan.py'), 'gate'],
                                    env=dict(os.environ, CI_MODE=mode, CI_NEEDS=raw), capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'FAIL', result.stdout)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT/'tests', self.root/'tests', ignore=shutil.ignore_patterns('__pycache__'))
        (self.root/'.github/workflows').mkdir(parents=True)
        shutil.copyfile(ROOT/'.github/workflows/checks.yml', self.root/'.github/workflows/checks.yml')

    def test_complete_current_inventory(self):
        self.assertEqual(ci_manifest.check()['orphan_tests'], 0)

    def test_unregistered_shell_python_helper_and_fixture_refused(self):
        for name in ('new.sh', 'new.py', 'helper.py', 'fixtures/unknown.txt'):
            path = self.root/'tests'/name; path.write_text('new')
            with self.subTest(name=name), self.assertRaises(AssertionError): ci_manifest.check(self.root)
            path.unlink()

    def test_new_test_module_is_automatically_discovered(self):
        (self.root/'tests/test_new.py').write_text('import unittest\n')
        self.assertEqual(ci_manifest.check(self.root)['discovered'], ci_manifest.check()['discovered'] + 1)

    def test_registered_but_unexecuted_suite_refused(self):
        path = self.root/'.github/workflows/checks.yml'
        path.write_text(path.read_text().replace('bash tests/fresh.sh', 'echo omitted fresh'))
        with self.assertRaises(AssertionError): ci_manifest.check(self.root)

    def test_commented_or_echoed_suite_is_not_execution(self):
        path = self.root/'.github/workflows/checks.yml'; original = yaml.safe_load(path.read_text())
        for command in ('# bash tests/fresh.sh', 'echo "bash tests/fresh.sh"'):
            value = copy.deepcopy(original)
            step = next(step for step in value['jobs']['lifecycle']['steps']
                        if step.get('run') == 'bash tests/fresh.sh')
            step['run'] = command
            path.write_text(yaml.safe_dump(value))
            with self.subTest(command=command), self.assertRaises(AssertionError): ci_manifest.check(self.root)

    def test_missing_helper_edge_refused(self):
        path = self.root/'tests/three-x-ui.sh'
        path.write_text(path.read_text().replace('bash tests/nginx-rollback.sh', 'echo omitted rollback'))
        with self.assertRaises(AssertionError): ci_manifest.check(self.root)

    def test_broken_discovery_refused(self):
        path = self.root/'tests/run.sh'; path.write_text(path.read_text().replace("'test_*.py'", "'test_safety.py'"))
        with self.assertRaises(AssertionError): ci_manifest.check(self.root)

    def test_gate_omission_or_optimistic_job_condition_refused(self):
        path = self.root/'.github/workflows/checks.yml'; original = yaml.safe_load(path.read_text())
        for field in ('needs', 'condition'):
            value = copy.deepcopy(original)
            if field == 'needs': value['jobs']['required']['needs'].remove('system24')
            else: value['jobs']['system24']['if'] = 'false'
            path.write_text(yaml.safe_dump(value))
            with self.assertRaises(AssertionError): ci_manifest.check(self.root)

    def test_conditional_skip_and_ignored_failure_refused(self):
        path = self.root/'.github/workflows/checks.yml'; original = yaml.safe_load(path.read_text())
        for defect in ('step-if', 'ignored', 'gate-bypass'):
            value = copy.deepcopy(original)
            if defect == 'step-if': value['jobs']['regression']['steps'][-1]['if'] = 'false'
            elif defect == 'ignored': value['jobs']['regression']['continue-on-error'] = True
            else: value['jobs']['required']['steps'][-1]['run'] += ' || true'
            path.write_text(yaml.safe_dump(value))
            with self.assertRaises(AssertionError): ci_manifest.check(self.root)

    def test_all_original_mandatory_calls_retained(self):
        workflow = yaml.safe_load((ROOT/'.github/workflows/checks.yml').read_text())
        commands = '\n'.join(step.get('run','') for job in workflow['jobs'].values() for step in job['steps'])
        # Frozen old execution contracts: guards against deleting both registration and invocation.
        for command in ('sudo env PYTHONDONTWRITEBYTECODE=1 bash tests/run.sh',
                        'bash tests/fresh.sh', 'bash tests/fresh-rollback.sh', 'bash tests/download.sh',
                        'bash tests/bootstrap_versions.sh', 'bash tests/preflight.sh',
                        'sudo python3 tests/web_link_fixture.py', 'sudo bash tests/fresh-account.sh',
                        'bash tests/pinned.sh', 'bash tests/upstream.sh', 'bash tests/staging.sh',
                        'sudo env TELEMT_TEST_EVIDENCE_DIR="$TELEMT_TEST_EVIDENCE_DIR" bash tests/runtime.sh',
                        'bash tests/pinned.sh --versions', 'sudo bash tests/bootstrap.sh',
                        'sudo env TELEMT_UPDATE_ARTIFACTS="$TELEMT_UPDATE_ARTIFACTS" PYTHONDONTWRITEBYTECODE=1 bash tests/uninstall.sh',
                        'bash tests/versions.sh', 'sudo env PYTHONDONTWRITEBYTECODE=1 python3 tests/update_transactions.py',
                        'sudo env PYTHONDONTWRITEBYTECODE=1 python3 tests/update_bootstrap.py',
                        'bash tests/conntrack.sh', 'bash tests/contracts.sh', 'bash tests/locks.sh',
                        'bash tests/acme.sh', 'sudo bash tests/renewal.sh', 'bash tests/nginx.sh',
                        'bash tests/three-x-ui.sh', 'bash tests/update_boot.sh 24.04',
                        'bash tests/update_boot.sh 26.04', 'bash tests/update_arm.sh 24.04'):
            with self.subTest(command=command): self.assertIn(command, commands)
        self.assertIn('for profile in legacy webroot;', (ROOT/'tests/three-x-ui.sh').read_text())
        for job in ('telemt', 'lifecycle', 'system26', 'system24', 'arm'):
            calls = '\n'.join(step.get('run','') for step in workflow['jobs'][job]['steps'])
            self.assertIn('sudo --preserve-env=TELEMT_TEST_GITHUB_TOKEN env PYTHONDONTWRITEBYTECODE=1 python3 tests/update_provenance.py', calls)


class DocumentationTests(unittest.TestCase):
    def test_current_links_and_anchors(self):
        self.assertGreater(ci_docs.check(), 0)

    def test_missing_target_and_anchor_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'README.md'
            for link in ('[missing](absent.md)', '[missing](#absent)'):
                path.write_text(link)
                with self.assertRaises(AssertionError): ci_docs.check(directory)


if __name__ == '__main__':
    unittest.main()
