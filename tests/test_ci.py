"""Scope/gate refusal and inventory reachability regressions; no runtime suite."""
import ast
import copy
import hashlib
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
import three_x_ui

ROOT = Path(__file__).resolve().parents[1]


class PlanTests(unittest.TestCase):
    def test_docs_only_paths(self):
        readmes = ['README.md', 'README.en.md', 'README.ru.md', 'README_AR.md',
                   'README_ES.md', 'README_FA.md', 'README_TR.md', 'README_ZH_CN.md']
        self.assertTrue(all((ROOT/name).is_file() for name in readmes))
        for paths in ([name] for name in readmes):
            with self.subTest(paths=paths): self.assertTrue(ci_plan.paths_plan(paths))
        self.assertTrue(ci_plan.paths_plan(readmes + ['docs/OPERATIONS.md', 'docs/CI-COVERAGE.md']))

    def test_every_other_or_empty_path_is_full(self):
        for path in ('install.sh', 'telemt-web-manager.sh', 'lib/safety.py', 'tests/test_ci.py',
                     '.github/workflows/checks.yml', 'assets/fake-sites/cover.css', 'LICENSE',
                     'unknown', 'docs-other/file.md', 'README_DE.md', 'README.en.md.bak',
                     'AGENTS.md', 'CLAUDE.md', 'CONTRIBUTING.md'):
            for paths in ([path], *([readme, path] for readme in
                                   ('README.md', 'README_AR.md', 'README_ES.md', 'README_FA.md',
                                    'README_TR.md', 'README_ZH_CN.md', 'README.en.md', 'README.ru.md'))):
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
            for name in ('README_AR.md', 'README_ZH_CN.md'):
                (root/name).write_text('translated documentation')
            git('add', '.'); git('commit', '-m', 'translations')
            self.assertEqual(ci_plan.classify(base, git('rev-parse', 'HEAD'), 'pull_request', root)['mode'], 'DOCS_ONLY')
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

    def test_both_lifecycle_profiles_are_mandatory_and_docs_only_skippable(self):
        for job in ('lifecycle', 'lifecycle_includes'):
            self.assertIn(job, ci_plan.HEAVY)
            needs = {name: {'result': 'success'} for name in ci_plan.REQUIRED}
            for result in ('failure', 'cancelled', 'skipped'):
                needs[job]['result'] = result
                with self.subTest(job=job, result=result):
                    self.assertFalse(ci_plan.gate('FULL', needs))
            del needs[job]
            self.assertFalse(ci_plan.gate('FULL', needs))
        docs = {name: {'result': 'skipped' if name in ci_plan.HEAVY else 'success'}
                for name in ci_plan.REQUIRED}
        self.assertTrue(ci_plan.gate('DOCS_ONLY', docs))

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

    def test_split_lifecycle_cannot_omit_or_duplicate_a_profile(self):
        path = self.root/'.github/workflows/checks.yml'
        original = yaml.safe_load(path.read_text())
        for defect in ('missing-job', 'serial', 'selector', 'wrong-profile', 'export', 'provenance', 'checkout', 'duplicate'):
            value = copy.deepcopy(original)
            includes = value['jobs']['lifecycle_includes']
            if defect == 'missing-job': del value['jobs']['lifecycle_includes']
            elif defect == 'serial': includes['needs'] = ['lifecycle']
            elif defect == 'selector':
                step = value['jobs']['lifecycle']['steps'][-1]
                step['run'] = step['run'].replace('TWM_TEST_NGINX_FIXTURE=tests/fixtures/nginx-3x-ui ', '')
            elif defect in ('wrong-profile', 'export'):
                step = next(step for step in includes['steps'] if step.get('name') == 'Generate pinned includes profile')
                step['run'] = step['run'].replace('--profile includes', '--profile legacy') if defect == 'wrong-profile' else step['run'].replace('>> "$GITHUB_ENV"', '> /dev/null')
            elif defect == 'provenance':
                includes['steps'] = [step for step in includes['steps'] if step.get('name') != 'Verify official provenance and download both architectures + baseline']
            elif defect == 'duplicate': includes['steps'].append(copy.deepcopy(includes['steps'][-1]))
            else: includes['steps'][0]['with']['ref'] = 'main'
            path.write_text(yaml.safe_dump(value))
            with self.subTest(defect=defect), self.assertRaises((AssertionError, KeyError)):
                ci_manifest.check(self.root)

    def test_concurrency_cancels_only_older_runs_of_the_same_pr(self):
        workflow = yaml.safe_load((ROOT/'.github/workflows/checks.yml').read_text())
        concurrency = workflow['concurrency']
        self.assertEqual(concurrency['cancel-in-progress'], "${{ github.event_name == 'pull_request' }}")
        self.assertEqual(concurrency['group'], '${{ github.workflow }}-${{ github.event_name }}-${{ github.event.pull_request.number || github.run_id }}')
        def group(event, pr, run):
            # Resolve the three literal substitutions, including GHA's || fallback.
            return concurrency['group'].replace('${{ github.workflow }}', 'checks').replace(
                '${{ github.event_name }}', event).replace(
                '${{ github.event.pull_request.number || github.run_id }}', str(pr or run))
        self.assertEqual(group('pull_request', 7, 100), group('pull_request', 7, 101))
        self.assertNotEqual(group('pull_request', 7, 100), group('pull_request', 8, 101))
        # A shared main group can cancel pending runs even with cancellation false.
        self.assertNotEqual(group('push', None, 100), group('push', None, 101))
        self.assertNotEqual(group('pull_request', 100, 101), group('push', None, 100))
        for job in workflow['jobs'].values(): self.assertNotIn('concurrency', job)

    def test_kvm_preserves_guest_budget_and_container_isolation(self):
        source = (ROOT/'tests/update_boot_host.py').read_text()
        command = next(node.value for node in ast.walk(ast.parse(source))
                       if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                       and target.id == 'command' for target in node.targets))
        tokens = [node.value for node in command.elts if isinstance(node, ast.Constant)]
        for option, value in (('-accel', 'kvm'), ('-cpu', 'max'), ('-m', '1536'), ('-smp', '2')):
            self.assertEqual(tokens[tokens.index(option)+1], value)
        for token in ('--device=/dev/kvm', '--network=none', '--cap-drop=ALL',
                      '--cap-add=DAC_OVERRIDE', '--security-opt=no-new-privileges'):
            self.assertIn(token, tokens)
        self.assertNotIn('--privileged', tokens)
        self.assertIn('deadline=time.monotonic()+1200', source)

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
                        'sudo env TWM_TEST_NGINX_FIXTURE=tests/fixtures/nginx-3x-ui TELEMT_UPDATE_ARTIFACTS="$TELEMT_UPDATE_ARTIFACTS" PYTHONDONTWRITEBYTECODE=1 bash tests/uninstall.sh',
                        'sudo env TWM_TEST_NGINX_FIXTURE="$TWM_TEST_NGINX_FIXTURE" TELEMT_UPDATE_ARTIFACTS="$TELEMT_UPDATE_ARTIFACTS" PYTHONDONTWRITEBYTECODE=1 bash tests/uninstall.sh',
                        'bash tests/versions.sh', 'sudo env PYTHONDONTWRITEBYTECODE=1 python3 tests/update_transactions.py',
                        'sudo env PYTHONDONTWRITEBYTECODE=1 python3 tests/update_bootstrap.py',
                        'bash tests/conntrack.sh', 'bash tests/contracts.sh', 'bash tests/locks.sh',
                        'bash tests/acme.sh', 'sudo bash tests/renewal.sh', 'bash tests/nginx.sh',
                        'bash tests/three-x-ui.sh', 'bash tests/update_boot.sh 24.04',
                        'bash tests/update_boot.sh 26.04', 'bash tests/update_arm.sh 24.04'):
            with self.subTest(command=command): self.assertIn(command, commands)
        self.assertIn('for profile in legacy webroot v2.1.7 v2.1.7-ipv4 v2.1.7-no-vision v2.1.7-ipv4-no-vision includes includes-ipv4;',
                      (ROOT/'tests/three-x-ui.sh').read_text())
        for job in ('telemt', 'lifecycle', 'lifecycle_includes', 'system26', 'system24', 'arm'):
            calls = '\n'.join(step.get('run','') for step in workflow['jobs'][job]['steps'])
            self.assertIn('sudo --preserve-env=TELEMT_TEST_GITHUB_TOKEN env PYTHONDONTWRITEBYTECODE=1 python3 tests/update_provenance.py', calls)

    def test_v217_matrix_has_independent_ipv6_and_vision_flags(self):
        expected = {'v2.1.7': (True, True), 'v2.1.7-ipv4': (False, True),
                    'v2.1.7-no-vision': (True, False), 'v2.1.7-ipv4-no-vision': (False, False)}
        self.assertEqual(three_x_ui.V217_OPTIONS, expected)
        for profile in expected:
            self.assertEqual(three_x_ui.PROFILES[profile],
                             ('2ae180bb36efdc1af36912fd96c673e9e7d9055a',
                              'f93b6c0178e125294ff514adca15c6d00bc591cf'))

    def test_local_upstream_source_is_hash_checked_and_never_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'assets/vision/managed.py'
            path.parent.mkdir(parents=True)
            data = b'raise AssertionError("upstream must never execute")\n'
            path.write_bytes(data)
            blob = hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()
            with patch.object(three_x_ui.urllib.request, 'urlopen', side_effect=AssertionError('offline')):
                self.assertEqual(three_x_ui.source_bytes('assets/vision/managed.py',
                                 three_x_ui.V217_COMMIT, blob, directory), data)
                with self.assertRaises(ValueError):
                    three_x_ui.source_bytes('assets/vision/managed.py', three_x_ui.V217_COMMIT,
                                            '0' * 40, directory)
                path.unlink()
                with self.assertRaises(FileNotFoundError):
                    three_x_ui.source_bytes('assets/vision/managed.py', three_x_ui.V217_COMMIT,
                                            blob, directory)

    def test_vision_templates_use_only_literal_substitutions(self):
        # Minimal AST-contract sample, not an alternative integration config.
        source = '''MARKER = '# fixture\\n'
raise AssertionError('upstream must never execute')
def stream_config(text, domain, port):
    anchor = 'map $ssl_preread_server_name $sni_name {\\n    hostnames;\\n'
    return text.replace(anchor, anchor + f'    {domain} vision;\\n') + f'\\nupstream vision {{ server 127.0.0.1:{port}; }}\\n'
def fallback_config(domain, port, root='/var/www/html'):
    return MARKER + f'fallback {domain} {port} {root}'
def acme_config(domain, ipv6=None):
    listener = '    listen [::]:80;\\n' if ipv6 else ''
    return MARKER + f'acme {domain} {listener}'
'''
        for ipv6 in (False, True):
            stream, fallback, acme = three_x_ui.vision_configs(source,
                'map $ssl_preread_server_name $sni_name {\n    hostnames;\n}\n', ipv6)
            self.assertIn('vision.example.com vision;', stream)
            self.assertIn('127.0.0.1:10443', stream)
            self.assertEqual(fallback, '# fixture\nfallback vision.example.com 10444 /var/www/html')
            self.assertEqual('[::]:80' in acme, ipv6)
        with self.assertRaises(ValueError):
            three_x_ui.vision_configs(source.replace('{root}', '{danger()}'),
                'map $ssl_preread_server_name $sni_name {\n    hostnames;\n}\n', False)


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
