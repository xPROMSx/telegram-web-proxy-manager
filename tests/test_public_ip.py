"""Interactive IPv4 suggestions: real prompt/CLI, mocked curl, no network."""
import os
from pathlib import Path
import tempfile
import unittest

from web_link_fixture import ROOT, terminal


class PublicIPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = self.root / 'calls'
        self.env = dict(os.environ, PATH=f'{self.root}:{os.environ["PATH"]}',
                        FIXTURE_ROOT=str(self.root), PRIMARY_STATUS='0', FALLBACK_STATUS='0')
        (self.root / 'curl').write_text('''#!/bin/bash
printf '%s\\n' "$*" >>"$FIXTURE_ROOT/calls"
case "${!#}" in
    https://api.ipify.org) cat "$FIXTURE_ROOT/primary"; exit "$PRIMARY_STATUS";;
    https://ipv4.icanhazip.com) cat "$FIXTURE_ROOT/fallback"; exit "$FALLBACK_STATUS";;
    *) exit 99;;
esac
''')
        (self.root / 'curl').chmod(0o755)
        (self.root / 'primary').write_text('8.8.8.8')
        (self.root / 'fallback').write_text('1.1.1.1\n')

    def run_prompt(self, ip='', code=None, tty=True):
        self.calls.unlink(missing_ok=True)
        script = 'source "$1"\n' + (code or '''prompt_install
printf 'RESULT=%s|%s|%s\\n' "$DOMAIN" "$PUBLIC_IP" "$SOCKS"
''')
        result, output = terminal(['bash', '-c', script, 'fixture',
                                   str(ROOT / 'telemt-web-manager.sh')],
                                  f'proxy.example.com\n{ip}\nn\n'.encode(), self.env,
                                  input_tty=tty)
        calls = self.calls.read_text().splitlines() if self.calls.exists() else []
        for call in calls:
            self.assertEqual(call.split()[:-1],
                             ['-4', '--noproxy', '*', '--connect-timeout', '2',
                              '--max-time', '4', '--max-filesize', '64', '-fsS'])
        return result, output.decode(), [call.split()[-1] for call in calls]

    def test_primary_default_and_enter(self):
        result, output, calls = self.run_prompt()
        self.assertEqual(result, 0)
        self.assertIn('Detected public IPv4: 8.8.8.8', output)
        self.assertIn('Public IPv4 [8.8.8.8]:', output)
        self.assertIn('RESULT=proxy.example.com|8.8.8.8|', output)
        self.assertEqual(calls, ['https://api.ipify.org'])

    def test_fallback_only_after_primary_failure(self):
        self.env['PRIMARY_STATUS'] = '7'
        result, output, calls = self.run_prompt()
        self.assertEqual(result, 0)
        self.assertIn('RESULT=proxy.example.com|1.1.1.1|', output)
        self.assertEqual(calls, ['https://api.ipify.org', 'https://ipv4.icanhazip.com'])

    def test_both_fail_manual_input(self):
        self.env.update(PRIMARY_STATUS='7', FALLBACK_STATUS='28')
        result, output, calls = self.run_prompt('203.0.113.10')
        self.assertEqual(result, 0)
        self.assertIn('Could not detect public IPv4 automatically.', output)
        self.assertIn('Public IPv4 (must match DNS A):', output)
        self.assertIn('RESULT=proxy.example.com|203.0.113.10|', output)
        self.assertEqual(len(calls), 2)

    def test_invalid_or_nonpublic_response_rejected(self):
        for response in ('127.0.0.1', '10.0.0.1', '100.64.0.1', '169.254.1.1',
                         '203.0.113.10', '224.0.0.1', '::1', '999.1.1.1',
                         '8.8.8.8\nextra', '8.8.8.8\n\n', ' 8.8.8.8', '<html>error</html>'):
            with self.subTest(response=response):
                (self.root / 'primary').write_text(response)
                result, output, calls = self.run_prompt()
                self.assertEqual(result, 0)
                self.assertIn('RESULT=proxy.example.com|1.1.1.1|', output)
                self.assertEqual(len(calls), 2)

    def test_manual_override(self):
        result, output, _ = self.run_prompt('203.0.113.10')
        self.assertEqual(result, 0)
        self.assertIn('RESULT=proxy.example.com|203.0.113.10|', output)

    def test_noninteractive_does_not_detect(self):
        # Reach the first filesystem validation in real install_manager, then stop
        # before any host mutation. Platform/locking are outside this prompt test.
        code = '''STATE=$FIXTURE_ROOT/state
preflight() { :; }
take_lock() { :; }
recover_update() { :; }
helper() {
    [[ $1 == safe-path ]] || exit 99
    printf 'RESULT=%s|%s\\n' "$DOMAIN" "$PUBLIC_IP"
    exit 0
}
main --install --domain proxy.example.com --public-ip 203.0.113.10
'''
        result, output, calls = self.run_prompt(code=code, tty=False)
        self.assertEqual(result, 0)
        self.assertIn('RESULT=proxy.example.com|203.0.113.10', output)
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
