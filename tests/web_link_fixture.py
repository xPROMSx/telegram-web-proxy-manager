#!/usr/bin/env python3
"""Native root, private random credentials and real PTYs; never echo captured output."""
import errno
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import pty
import secrets
import shutil
import select
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'lib/safety.py'
MENU = b'  1. Install Telegram proxy\n  2. Update Telemt\n  3. Check status\n  4. Check and restart services\n  5. Show connection link\n  6. Uninstall Telegram proxy\n  0. Exit\n'
COUNT = 0


def require(ok, reason):
    if not ok:
        raise AssertionError(reason)  # Never pass secrets/captured output as reason.


def passed(reason):
    global COUNT
    COUNT += 1
    print('ok - '+reason, flush=True)


def terminal(command, answer=b'', env=None, input_tty=True, output_tty=True, error_tty=True):
    master, slave = pty.openpty()
    child = subprocess.Popen(command, stdin=slave if input_tty else subprocess.PIPE,
                             stdout=slave if output_tty else subprocess.PIPE,
                             stderr=slave if output_tty and error_tty else subprocess.PIPE,
                             cwd=ROOT, env=env, start_new_session=True)
    os.close(slave)
    captured = bytearray()
    try:
        if input_tty:
            os.write(master, answer)
        else:
            child.stdin.close()
            child.stdin = None
        deadline = time.monotonic()+30
        if not output_tty:
            output,error=child.communicate(timeout=30)
            captured.extend(output); captured.extend(error or b'')
        else:
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], .1)
                if ready:
                    try:
                        block = os.read(master, 65536)
                    except OSError as error:
                        if error.errno == errno.EIO:
                            break
                        raise
                    if not block:
                        break
                    captured.extend(block)
                elif child.poll() is not None:
                    break
            require(time.monotonic() < deadline, 'PTY process timeout')
        result = child.wait(timeout=5)
        if output_tty and child.stderr: captured.extend(child.stderr.read())
        return result, bytes(captured).replace(b'\r\n', b'\n')
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
        child.wait()
        for channel in (child.stdin,child.stdout,child.stderr):
            if channel is not None: channel.close()
        os.close(master)


def snapshot(root):
    values = {}
    for path in sorted(root.rglob('*')):
        info = path.lstat()
        values[str(path.relative_to(root))] = (info.st_uid, info.st_gid, info.st_mode,
                                             hashlib.sha256(path.read_bytes()).hexdigest()
                                             if path.is_file() and not path.is_symlink() else None)
    return values


def main():
    require(os.geteuid() == 0, 'native root required')
    with tempfile.TemporaryDirectory(prefix='twm-link-') as directory:
        root = Path(directory)
        state = root/'state'; state.mkdir(mode=0o700)
        config = root/'telemt.toml'
        link = state/'web-link.txt'; manifest = state/'manifest.json'
        token = secrets.token_hex(16)
        expected = f'tg://webproxy?server=proxy.example.com&secret=dd{token}'.encode()
        original = {
            manifest: json.dumps(dict(schema=1, domain='proxy.example.com', public_ip='203.0.113.10',
                                      unit_sha256='a'*64, nginx_sha256='b'*64, acme_webroot=None)).encode(),
            link: expected+b'\n',
            config: (f'[access.users]\nweb-user = "{token}"\n[web]\nenabled = true\n'
                     '[[web.vhosts]]\nhost = "proxy.example.com"\n[[web.vhosts.profiles]]\n'
                     'user = "web-user"\nsecret_mode = "dd"\n').encode(),
        }
        def reset():
            for path, value in original.items():
                if path.is_symlink() or path.exists(): path.unlink()
                path.write_bytes(value); path.chmod(0o640 if path == config else 0o600)
            state.chmod(0o700)
        reset()
        for name in ('unit', 'nginx', 'certificate', 'renewal'):
            (root/name).write_text('unchanged fixture '+name)
        (root/'backups').mkdir()
        (state/'certificate.json').write_text('independent preserved ownership fixture')
        lock = root/'lock'; lock.touch(mode=0o600)
        code = '''source ./telemt-web-manager.sh
STATE=$1 CONFIG=$2 LOCK=$3
systemctl() { exit 91; }
nginx() { exit 92; }
backup_begin() { exit 93; }
main
'''
        command = ['bash', '-c', code, 'fixture', str(state), str(config), str(lock)]
        env = dict(os.environ, TERM='xterm', PYTHONDONTWRITEBYTECODE='1')
        env.pop('NO_COLOR', None)
        # Actual Show operation with only its three tools plus startup dirname/bash.
        # No conntrack, Nginx, Certbot, systemd tooling or runtime health is available.
        tools = root/'minimal-tools'; tools.mkdir()
        for name in ('bash', 'dirname', 'python3', 'flock', 'stat'):
            target = shutil.which(name)
            require(target is not None, 'missing fixture tool: '+name)
            (tools/name).symlink_to(target)
        result, output = terminal(command, b'1\n5\n', dict(env, PATH=str(tools)))
        require(result == 0 and expected in output, 'Show link gained unrelated dependencies')
        passed('actual Show link succeeds with conntrack/Nginx/Certbot/systemd tools absent')

        # Native root runner: invoke the real platform guards with controlled facts.
        # The apt function cannot mutate packages even if a guard regresses.
        for reason, facts in [
            ('Supported OS: Ubuntu', 'read() { init=systemd; }; source() { ID=debian; VERSION_ID=12; }'),
            ('Unsupported architecture', 'read() { init=systemd; }; source() { ID=ubuntu; VERSION_ID=24.04; }; uname() { printf riscv64; }'),
            ('active init system', 'read() { init=fixture-init; }'),
        ]:
            script = ('source "$1"; '+facts+'; MENU_ACTION=1; '
                      'apt-get() { printf UNEXPECTED_APT; return 98; }; preflight --install')
            process = subprocess.run(['bash', '-c', script, 'fixture', str(ROOT/'telemt-web-manager.sh')],
                                     cwd=ROOT, capture_output=True, timeout=5)
            captured = process.stdout+process.stderr
            require(process.returncode != 0 and reason.encode() in captured
                    and b'UNEXPECTED_APT' not in captured, 'immutable platform guard: '+reason)
            passed('real platform guard before apt: '+reason)
        before = snapshot(root)
        for language, menu, warning in [('1',MENU,b'WARNING: This link contains a bearer secret.'),
                ('2','  1. Установить Telegram-прокси\n  2. Обновить Telemt\n  3. Проверить состояние\n  4. Проверить и перезапустить службы\n  5. Показать ссылку подключения\n  6. Удалить Telegram-прокси\n  0. Выход\n'.encode(),
                 'ВНИМАНИЕ: ссылка содержит секрет доступа.'.encode())]:
            for name, extra, colored in [('color', {}, True), ('NO_COLOR', {'NO_COLOR':'1'}, False),
                                         ('NO_COLOR empty', {'NO_COLOR':''}, False), ('TERM=dumb', {'TERM':'dumb'}, False),
                                         ('TERM=unknown', {'TERM':'unknown'}, False)]:
                result, output = terminal(command, (language+'\n5\n').encode(), dict(env, **extra))
                require(result == 0 and menu in output, 'exact localized seven-entry menu')
                require(output.count(b'SELECT LANGUAGE /')==1, 'one language choice per invocation')
                require(expected in output and output.count(expected) == 1, 'exact current TOML/domain link display')
                require((b'\x1b[' in output) == colored, 'terminal color policy')
                require(warning in output, 'localized bearer warning')
                require(snapshot(root) == before, 'show operation mutated managed files')
                passed('read-only exact menu/link '+language+' '+name+'; no service, Nginx or backup operation')
        result = subprocess.run(['python3', str(HELPER), 'web-link-validate', str(state), str(config)],
                                capture_output=True, timeout=5)
        require(result.returncode == 0 and not result.stdout and not result.stderr, 'silent validation')
        passed('validation-only helper emits no secret or diagnostics on success')
        for input_tty, output_tty in [(True,False),(False,True),(False,False)]:
            result, output = terminal(command, b'1\n5\n', env, input_tty, output_tty)
            require(result != 0 and expected not in output and token.encode() not in output
                    and b'\x1b' not in output, 'noninteractive secret/color disclosure')
        for language in ('1','2'):
            result,output=terminal(command,(language+'\n5\n').encode(),env,error_tty=False)
            require(result!=0 and expected not in output and token.encode() not in output,
                    'redirected stderr secret disclosure')
        for language in ('en','ru'):
            result,output=terminal(['python3',str(HELPER),'web-link-display',str(state),str(config)],
                                   env=dict(env,TWM_UI_LANGUAGE=language),error_tty=False)
            require(result!=0 and expected not in output and token.encode() not in output and b'\x1b' not in output,
                    'direct helper redirected stderr disclosure')
        passed('redirected stderr refuses explicit link display in both languages')
        for action in ('web-link-display',):
            result = subprocess.run(['python3', str(HELPER), action, str(state), str(config)],
                                    capture_output=True, timeout=5)
            require(result.returncode != 0 and token.encode() not in result.stdout+result.stderr
                    and b'\x1b' not in result.stdout+result.stderr, 'non-TTY helper disclosure')
        result = subprocess.run(['bash', str(ROOT/'telemt-web-manager.sh'), '--show-link'], capture_output=True)
        require(result.returncode != 0 and token.encode() not in result.stdout+result.stderr, 'unrequested public CLI')
        passed('stdin/stdout TTY gates, redirected output and absent --show-link CLI')

        def invalid(name, change):
            reset(); change()
            result = subprocess.run(['python3', str(HELPER), 'web-link-validate', str(state), str(config)],
                                    capture_output=True, timeout=5)
            require(result.returncode != 0 and not result.stdout
                    and re.fullmatch(rb'Safety validation failed(?: \((?:(?:web_link_read|current_web_link|web_link_value):[0-9]+|symlink path requires manual review|unexpected path owner|unexpected path type)\))?; manual review required \(no credentials displayed\)\.\n', result.stderr)
                    and token.encode() not in result.stderr,
                    'unsafe file validation: '+name)
            for language, refusal in [('1',b'No valid manager-owned WEB link is available.'),
                                      ('2','Проверенная WEB-ссылка этой установки недоступна'.encode())]:
                result, output = terminal(command, (language+'\n5\n').encode(), env)
                require(result != 0 and b'tg://' not in output and token.encode() not in output,
                        'failure secret disclosure: '+language+' '+name)
                require(refusal in output, 'failure UX: '+language+' '+name)
            passed('refusal without secret: '+name)

        invalid('missing link', lambda: link.unlink())
        invalid('missing manifest', lambda: manifest.unlink())
        invalid('link symlink', lambda: (link.unlink(), link.symlink_to(config)))
        invalid('manifest symlink', lambda: (manifest.unlink(), manifest.symlink_to(config)))
        invalid('config symlink', lambda: (config.unlink(), config.symlink_to(root/'unit')))
        invalid('wrong link mode', lambda: link.chmod(0o640))
        invalid('wrong manifest mode', lambda: manifest.chmod(0o644))
        invalid('wrong config mode', lambda: config.chmod(0o644))
        invalid('wrong link owner', lambda: os.chown(link,65534,65534))
        invalid('wrong manifest owner', lambda: os.chown(manifest,65534,65534))
        invalid('wrong config owner', lambda: os.chown(config,65534,65534))
        invalid('unsafe state mode', lambda: state.chmod(0o755))
        invalid('multiline', lambda: link.write_bytes(original[link]+b'\n'))
        invalid('malformed URL', lambda: link.write_bytes(b'https://example.com\n'))
        invalid('domain mismatch', lambda: link.write_bytes(original[link].replace(b'proxy.example.com',b'foreign.example.com')))
        invalid('secret mismatch', lambda: link.write_bytes(original[link].replace(token.encode(),secrets.token_hex(16).encode())))
        invalid('TOML secret mismatch', lambda: config.write_bytes(original[config].replace(token.encode(),secrets.token_hex(16).encode())))
        invalid('malformed manifest', lambda: manifest.write_bytes(b'{'))
        invalid('unsupported manifest', lambda: manifest.write_bytes(original[manifest].replace(b'"schema": 1',b'"schema": 2')))
        invalid('FIFO', lambda: (link.unlink(), os.mkfifo(link,0o600)))
        reset()
        alias = root/'alias'
        invalid('hardlink', lambda: os.link(link,alias))
        alias.unlink(); reset()
        old_state = root/'old-state'; state.rename(old_state); state.symlink_to(old_state)
        try:
            result = subprocess.run(['python3', str(HELPER), 'web-link-validate', str(state), str(config)],capture_output=True)
            require(result.returncode != 0 and token.encode() not in result.stdout+result.stderr, 'state symlink refusal')
        finally:
            state.unlink(); old_state.rename(state)
        passed('state symlink refused')
        root.chmod(0o777)
        try:
            result = subprocess.run(['python3', str(HELPER), 'web-link-validate', str(state), str(config)],capture_output=True)
            require(result.returncode != 0 and token.encode() not in result.stdout+result.stderr, 'unsafe ancestor refusal')
        finally: root.chmod(0o700)
        passed('unsafe ancestor refused')
        with lock.open('r+') as held:
            fcntl.flock(held, fcntl.LOCK_SH)
            result, output = terminal(command,b'1\n5\n',env)
            require(result == 0 and expected in output, 'concurrent shared read blocked')
            fcntl.flock(held, fcntl.LOCK_EX)
            result, output = terminal(command,b'1\n5\n',env)
            require(result != 0 and token.encode() not in output, 'exclusive mutation not respected')
        passed('shared lock coexists with reader and refuses concurrent exclusive mutation')

        # Actual menu provenance flag, without invoking unrelated production setup.
        route = '''source ./telemt-web-manager.sh
preflight() { :; }
recover_update() { :; }
take_lock() { :; }
install_manager() { [[ $INTERACTIVE_INSTALL == "$1" ]]; }
'''
        # The mock accepts no arguments from main, so the desired flag is literal in its body.
        for argument, expected_flag, answer in [('', '1', b'1\n1\n'), ('--install','0',b'')]:
            script = route.replace('"$1"', expected_flag)+'main '+argument
            result, _ = terminal(['bash','-c',script],answer,env)
            require(result == 0, 'menu versus CLI Install provenance flag')
        passed('only actual menu selection sets interactive Install provenance')
        # A root CI command reads a runner-owned checkout. Preserve fixture
        # permissions when copying it, but never retain the checkout's owner.
        nginx_source = root/'runner-owned-nginx'
        shutil.copytree(ROOT/'tests/fixtures/nginx', nginx_source)
        for path in (nginx_source, *nginx_source.rglob('*')):
            os.chown(path, 65534, 65534)
        fresh = ['bash', str(ROOT/'tests/fresh.sh'), str(nginx_source)]
        fresh_env = dict(env,FIXTURE_LINK_UX='1')
        for language in ('en','ru'):
            localized_fresh=dict(fresh_env,FIXTURE_UI_LANGUAGE=language)
            result, output = terminal(fresh, env=localized_fresh)
            require(result == 0 and output.count(b'tg://webproxy?server=') == 1
                    and output.index(b'FIXTURE_COMMITTED') < output.index(b'tg://webproxy?server='),
                    'interactive fresh committed display')
            passed('actual fresh transaction displays validated link only after ARMED=0, manifest and health commit')
            result, output = terminal(fresh,env=dict(localized_fresh,FIXTURE_INCOMPATIBLE='1'))
            require(result != 0 and b'tg://' not in output and b'FIXTURE_COMMITTED' not in output,
                    'rejected interactive Install disclosed link')
            passed('interactive candidate failure/rollback does not present link')
        for settings, output_tty in [({'FIXTURE_MENU_INSTALL':'0'},True), ({},False)]:
            result, output = terminal(fresh,env=dict(fresh_env,**settings),output_tty=output_tty)
            require(result == 0 and b'tg://' not in output and b'\x1b' not in output
                    and b'Private WEB link:' in output and b'FIXTURE_COMMITTED' not in output,
                    'CLI/redirected fresh Install disclosed link')
        passed('CLI Install even on PTY and redirected menu Install show saved path only')
        result,output=terminal(fresh,env=dict(fresh_env,FIXTURE_UI_LANGUAGE='ru'),error_tty=False)
        require(result==0 and b'tg://' not in output and 'Секретная WEB-ссылка сохранена:'.encode() in output,
                'committed Russian Install with redirected stderr disclosed link')
        passed('committed Russian Install with redirected stderr retains saved-path-only disclosure')
    print(f'WEB link regression: {COUNT} checks passed; captured credentials never printed.')


if __name__ == '__main__':
    main()
