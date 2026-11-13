"""Real PTYs for per-invocation UI; operation fixtures never touch services."""
import errno
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
ROUTES = '''source ./telemt-web-manager.sh
preflight() { :; }; take_lock() { :; }; recover_update() { :; }; pending_update() { :; }
install_manager() { printf 'ROUTE:install:%s:%s\\n' "$MENU_ACTION" "$INTERACTIVE_INSTALL"; }
update_manager() { printf 'ROUTE:update\\n'; }
check_manager() { printf 'ROUTE:check\\n'; }
repair_manager() { printf 'ROUTE:repair\\n'; }
show_current_web_link() { printf 'ROUTE:link\\n'; }
uninstall_manager() { printf 'ROUTE:uninstall\\n'; }
main "$@"
'''


def terminal(code, answer=b'', args=(), env=None, input_tty=True, output_tty=True,
             error_tty=True, interrupt=False, timeout=10):
    master, slave = pty.openpty()
    environment = dict(os.environ, TERM='xterm', PYTHONDONTWRITEBYTECODE='1')
    environment.pop('NO_COLOR', None)
    environment.update(env or {})
    child = subprocess.Popen(['bash', '-c', code, 'ui-fixture', *args], cwd=ROOT,
        stdin=slave if input_tty else subprocess.PIPE,
        stdout=slave if output_tty else subprocess.PIPE,
        stderr=slave if error_tty and output_tty else subprocess.PIPE,
        env=environment, start_new_session=True)
    os.close(slave)
    captured = bytearray()
    try:
        if input_tty: os.write(master, answer)
        else: child.stdin.close(); child.stdin = None
        if not output_tty:
            output, error = child.communicate(timeout=timeout)
            return child.returncode, output, error or b''
        deadline = time.monotonic()+timeout
        sent = False
        while time.monotonic() < deadline:
            readable, _, _ = select.select([master], [], [], .05)
            if readable:
                try: block = os.read(master, 65536)
                except OSError as error:
                    if error.errno == errno.EIO: break
                    raise
                if not block: break
                captured.extend(block)
                if interrupt and not sent and b'Select /' in captured:
                    os.killpg(child.pid, signal.SIGINT); sent = True
            elif child.poll() is not None: break
        else: raise AssertionError('bounded PTY fixture timed out')
        result = child.wait(timeout=5)
        error = child.stderr.read() if child.stderr else b''
        return result, bytes(captured).replace(b'\r\n', b'\n'), error
    finally:
        if child.poll() is None: os.killpg(child.pid, signal.SIGKILL)
        child.wait(); os.close(master)
        for channel in (child.stdin,child.stdout,child.stderr):
            if channel is not None: channel.close()


class ManagerUI(unittest.TestCase):
    def test_language_menus_and_all_six_one_shot_routes(self):
        for language, title, last in [('1','MAIN MENU','0. Exit'),('2','ГЛАВНОЕ МЕНЮ','0. Выход')]:
            for item, action in enumerate(('install:1:1','update','check','repair','link','uninstall'),1):
                with self.subTest(language=language,item=item):
                    result, output, _ = terminal(ROUTES,(language+'\n'+str(item)+'\n').encode())
                    self.assertEqual(result,0)
                    self.assertTrue(title.encode() in output and last.encode() in output,'localized seven-entry menu')
                    self.assertEqual(output.count(b'SELECT LANGUAGE /'),1)
                    self.assertEqual(output.count(b'TELEGRAM WEB PROXY MANAGER v1.3.2'),2,
                                     'language and main menu each show the current version once')
                    self.assertEqual(output.count(b'v1.3.2'),2)
                    self.assertTrue(('ROUTE:'+action).encode() in output,'operation/provenance preserved')
                    self.assertEqual(output.count(b'ROUTE:'),1)

    def test_cli_and_imports_ignore_language_environment(self):
        for code,args in [(ROUTES,('--install',)),('source ./telemt-web-manager.sh; main "$@"',('--help',))]:
            result, output, error = terminal(code,args=args,env={'TWM_UI_LANGUAGE':'ru'})
            self.assertEqual(result,0)
            self.assertTrue(b'SELECT LANGUAGE' not in output and b'\x1b' not in output+error)
            if args==('--install',): self.assertTrue(b'ROUTE:install:0:0' in output)
            else:
                self.assertTrue(b'Usage:' in output)
                self.assertEqual(output.count(b'Telegram Web Proxy Manager 1.3.2'),1)
        result = subprocess.run(['bash','-c','source ./telemt-web-manager.sh'],cwd=ROOT,capture_output=True)
        self.assertEqual((result.returncode,result.stdout,result.stderr),(0,b'',b''))
        result = subprocess.run(['python3','-c',"import importlib.util; s=importlib.util.spec_from_file_location('ui_import','lib/safety.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)"],cwd=ROOT,capture_output=True)
        self.assertEqual((result.returncode,result.stdout,result.stderr),(0,b'',b''))

    def test_cancel_invalid_eof_interrupt_and_non_tty_do_not_run_operations(self):
        for answer,code in [(b'0\n',0),(b'2\n0\n',0),(b'9\n0\n',0),(b'\x04',0),(b'2\n\x04',0),(b'2\n9\n',1)]:
            result, output, _ = terminal(ROUTES,answer)
            self.assertEqual(result,code)
            self.assertTrue(b'ROUTE:' not in output)
        result, output, _ = terminal(ROUTES,interrupt=True)
        self.assertEqual(result,130); self.assertTrue(b'ROUTE:' not in output)
        for input_tty,output_tty in ((False,True),(True,False),(False,False)):
            result,output,error = terminal(ROUTES,b'2\n1\n',input_tty=input_tty,output_tty=output_tty)
            self.assertNotEqual(result,0)
            self.assertTrue(b'ROUTE:' not in output and b'SELECT LANGUAGE' not in output+error)

    def test_localized_results_refusals_and_color_policy(self):
        code='source ./telemt-web-manager.sh; UI_INTERACTIVE=1; UI_LANG=$1; ui_ok "Completed." "Готово."; ui_die "Stopped; manual review required." "Остановлено; требуется ручная проверка."'
        for language in ('en','ru'):
            for env,color in (({},True),({'NO_COLOR':'1'},False),({'NO_COLOR':''},False),({'TERM':'dumb'},False),({'TERM':'unknown'},False)):
                result,output,_=terminal(code,args=(language,),env=env)
                self.assertEqual(result,1)
                expected=('Готово.','требуется ручная проверка') if language=='ru' else ('Completed.','manual review required')
                self.assertTrue(all(text.encode() in output for text in expected),'localized result and safe refusal')
                self.assertEqual(b'\x1b[' in output,color)
            result,output,error=terminal(code,args=(language,),output_tty=False)
            self.assertEqual(result,1); self.assertTrue(b'\x1b' not in output+error)
            result,_,error=terminal(code,args=(language,),error_tty=False)
            self.assertEqual(result,1); self.assertTrue(b'\x1b' not in error)

    def test_version_header_keeps_terminal_color_policy_and_uses_source_version(self):
        for language in (b'1\n0\n',b'2\n0\n'):
            for env,color in (({},True),({'NO_COLOR':''},False),({'TERM':'dumb'},False)):
                result,output,_=terminal(ROUTES,language,env=env)
                self.assertEqual(result,0)
                self.assertEqual(output.count(b'TELEGRAM WEB PROXY MANAGER v1.3.2'),2)
                self.assertEqual(b'\x1b[' in output,color)
        # A fixture source version proves the title is not a second literal pin.
        code='source <(sed "s/^readonly SCRIPT_VERSION=.*/readonly SCRIPT_VERSION=9.8.7/" ./telemt-web-manager.sh); ui_header TITLE'
        result,output,error=terminal(code,output_tty=False)
        self.assertEqual(result,0)
        self.assertEqual(output.count(b'TELEGRAM WEB PROXY MANAGER v9.8.7'),1)
        self.assertTrue(b'1.3.2' not in output and b'\x1b' not in output+error)

    def test_actual_install_questions_keep_input_values(self):
        code='''source ./telemt-web-manager.sh
UI_INTERACTIVE=1 UI_LANG=$1
detect_public_ipv4() { printf '203.0.113.10'; }
prompt_install
printf 'RESULT:%s:%s:%s\\n' "$DOMAIN" "$PUBLIC_IP" "$SOCKS"
'''
        for language,label in [('en','WEB domain:'),('ru','Домен WEB-прокси:')]:
            result,output,_=terminal(code,b'proxy.example.com\n\nY\n127.0.0.1\n1080\n',args=(language,))
            self.assertEqual(result,0)
            self.assertTrue(label.encode() in output)
            self.assertTrue(b'RESULT:proxy.example.com:203.0.113.10:127.0.0.1:1080' in output)

    def test_python_progress_receives_only_the_menu_language(self):
        # Real Bash -> Python environment/PTY boundary; render the real class,
        # with no engine, release request, service or acceptance wait.
        program=f'''import importlib.util, sys
spec=importlib.util.spec_from_file_location('ui_progress',{str(ROOT/'lib/safety.py')!r})
s=importlib.util.module_from_spec(spec); sys.modules[spec.name]=s; spec.loader.exec_module(s)
p=s.UpdateProgress()
for stage in range(1,6): p.event(stage,'English line diagnostic')
p.finish('Update completed',russian='Обновление завершено')
'''
        with tempfile.NamedTemporaryFile('w',suffix='.py') as helper:
            helper.write(program); helper.flush()
            code=ROUTES.replace("update_manager() { printf 'ROUTE:update\\n'; }",'update_manager() { universal_update; }')
            code=code.replace('main "$@"','HELPER=$1; shift; main "$@"')
            for language,label in [('1','Verifying release'),('2','Проверка релиза')]:
                result,output,_=terminal(code,(language+'\n2\n').encode(),args=(helper.name,))
                self.assertEqual(result,0); self.assertTrue(label.encode() in output)
                self.assertTrue(b'[5/5]' in output)
            result,output,_=terminal(code,args=(helper.name,'--update'),env={'TWM_UI_LANGUAGE':'ru'})
            self.assertEqual(result,0)
            self.assertTrue(b'Verifying release' in output and b'SELECT LANGUAGE' not in output)
        result=subprocess.run(['bash','-c','source ./telemt-web-manager.sh; UI_LANG=ru UI_INTERACTIVE=1; helper version-compare 3.5.16 3.5.16'],cwd=ROOT,capture_output=True)
        self.assertEqual((result.returncode,result.stdout,result.stderr),(0,b'0\n',b''))

    def test_uninstall_cancel_in_both_languages_before_mutation(self):
        code='''source ./telemt-web-manager.sh
UI_INTERACTIVE=1 UI_LANG=$1
need() { :; }; load_installation() { :; }
uninstall_load() { DOMAIN=proxy.example.com; }
helper() { printf UNEXPECTED_MUTATION; exit 99; }
backup_begin() { printf UNEXPECTED_MUTATION; exit 99; }
uninstall_manager
'''
        for language in ('en','ru'):
            for action,answer,english,russian in (
                    ('uninstall',b'CANCEL\n','Uninstall cancelled.','Удаление отменено.'),):
                result,output,_=terminal(code,answer,args=(language,action))
                self.assertEqual(result,0)
                self.assertTrue((russian if language=='ru' else english).encode() in output)
                self.assertTrue(b'UNEXPECTED_MUTATION' not in output)
                if action=='uninstall': self.assertTrue(b'UNINSTALL' in output)


class FreshRemnantMessages(unittest.TestCase):
    def test_existing_install_paths_are_explained_in_both_languages(self):
        cases = [('binary', 'BIN'), ('config', 'CONFIG'), ('unit', 'UNIT'),
                 ('data', 'DATA'), ('config-dir', 'CONFIG_DIR'), ('site', 'SITE_ROOT'),
                 ('state', 'STATE'), ('certificate-record', 'STATE/certificate.json'),
                 ('hook', 'RENEW_HOOK'), ('system-unit', '/etc/systemd/system/telemt.service')]
        for scenario, expected in cases:
            for language in ('en', 'ru'):
                with self.subTest(scenario=scenario, language=language), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    paths = dict(BIN=root/'bin', CONFIG_DIR=root/'config', CONFIG=root/'config/telemt.toml',
                                 UNIT=root/'telemt.service', DATA=root/'data', STATE=root/'state',
                                 SITE_ROOT=root/'site', RENEW_HOOK=root/'hook')
                    key = dict(binary='BIN', config='CONFIG', unit='UNIT', data='DATA',
                               **{'config-dir': 'CONFIG_DIR', 'site': 'SITE_ROOT', 'hook': 'RENEW_HOOK'}).get(scenario)
                    if key:
                        path = paths[key]
                        path.parent.mkdir(parents=True, exist_ok=True)
                        if scenario in ('data', 'config-dir', 'site'): path.mkdir()
                        else: path.write_text('PRIVATE_REMNANT_CONTENT')
                    if scenario in ('state', 'certificate-record'):
                        paths['STATE'].mkdir(mode=0o700)
                        path = paths['STATE']/('foreign' if scenario == 'state' else 'certificate.json')
                        path.write_text('PRIVATE_REMNANT_CONTENT' if scenario == 'state' else
                            '{"schema":1,"domain":"old.example.com","cert_name":"old.example.com",'
                            '"renewal_kind":"standalone","acme_webroot":""}')
                        path.chmod(0o600)
                    before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
                    script = '''source ./telemt-web-manager.sh
UI_INTERACTIVE=1 UI_LANG=$1 DOMAIN=proxy.example.com PUBLIC_IP=203.0.113.10
getent() { return 1; }
systemctl() { printf /etc/systemd/system/telemt.service; }
'''+''.join(key+'='+str(value)+'\n' for key,value in paths.items())+'install_manager\n'
                    result, output, _ = terminal(script, args=(language,))
                    self.assertEqual(result, 1)
                    expected_path = (str(paths['STATE']/'certificate.json') if expected == 'STATE/certificate.json'
                                     else str(paths.get(expected, expected)))
                    self.assertIn(expected_path.encode(), output)
                    if scenario == 'certificate-record':
                        self.assertEqual(output.decode().count('ERROR:') + output.decode().count('ОШИБКА:'), 1)
                        for phrase in (('saved', 'certificate', 'irreversible', 'same domain', 'docs/OPERATIONS.md')
                                       if language == 'en' else
                                       ('сохранённая', 'сертификат', 'необратимо', 'тот же домен', 'docs/OPERATIONS.md')):
                            self.assertIn(phrase.casefold(), output.decode().casefold())
                        for forbidden in ('another server', 'другого сервера', '3x-ui', 'old.example.com'):
                            self.assertNotIn(forbidden.encode(), output)
                    else:
                        for phrase in (('another server', '3x-ui', 'nothing', 'manually', "Let's Encrypt")
                                   if language == 'en' else
                                   ('другого сервера', '3x-ui', 'ничего', 'вручную', "Let's Encrypt")):
                            self.assertIn(phrase.encode(), output)
                    self.assertNotIn(b'PRIVATE_REMNANT_CONTENT', output)
                    self.assertEqual(before, {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_partial_certbot_paths_are_explained_without_deleting_them(self):
        for location in ('live', 'renewal', 'archive'):
            for language in ('en', 'ru'):
                with self.subTest(location=location, language=language), tempfile.TemporaryDirectory() as directory:
                    path = Path(directory)/location/('proxy.example.com.conf' if location == 'renewal' else 'proxy.example.com')
                    path.parent.mkdir()
                    if location == 'renewal': path.write_text('PRIVATE_CERTIFICATE')
                    else: path.mkdir()
                    code = '''source ./telemt-web-manager.sh
UI_INTERACTIVE=1 UI_LANG=$1 CERT_ROOT=$2 DOMAIN=proxy.example.com
ensure_certificate
'''
                    result, output, _ = terminal(code, args=(language, directory))
                    self.assertEqual(result, 1)
                    self.assertIn(('/etc/letsencrypt/'+location).encode(), output)
                    self.assertIn("Let's Encrypt".encode(), output)
                    self.assertNotIn(b'PRIVATE_CERTIFICATE', output)
                    self.assertTrue(path.exists())


if __name__ == '__main__': unittest.main()
