#!/usr/bin/env python3
"""Strict, read-only parsers and staged Nginx plans. Python 3.11+ stdlib only."""
# This canonical header is also the install.sh downloaded-pair identity marker.
import base64
import types
import zlib
import glob
import hashlib
import ipaddress
import json
import os
import signal
import subprocess
import tempfile
from contextlib import contextmanager, redirect_stdout
import io
import stat
import tarfile
import re
import sys
import tomllib
import time
import uuid
import urllib.request
import urllib.parse
import ssl
import platform
import shutil
import fcntl
import socket
import selectors
import struct
import hmac
import http.client
from dataclasses import dataclass
from pathlib import Path


class NginxDomainInUse(ValueError):
    """Exact foreign server_name collision; no configuration text is diagnostic."""


def require(ok, message="automatic nginx integration not possible"):
    if not ok:
        raise ValueError(message)


def semver(value):
    match = re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
                         r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
                         r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?", value)
    require(match is not None, "invalid SemVer")
    pre = match[4].split(".") if match[4] else []
    require(all(not x.isdigit() or x == "0" or not x.startswith("0") for x in pre))
    return tuple(int(match[i]) for i in (1, 2, 3)), pre


def version_compare(left, right):
    a, ap = semver(left)
    b, bp = semver(right)
    if a != b:
        return (a > b) - (a < b)
    if not ap or not bp:
        return (not ap) - (not bp)
    for x, y in zip(ap, bp):
        if x != y:
            if x.isdigit() and y.isdigit():
                return (int(x) > int(y)) - (int(x) < int(y))
            if x.isdigit() != y.isdigit():
                return -1 if x.isdigit() else 1
            return (x > y) - (x < y)
    return (len(ap) > len(bp)) - (len(ap) < len(bp))


def safe_path(path):
    """Check writable destinations and their ancestors, without resolving links.

    Root-owned sticky directories such as /tmp are safe ancestors of private
    staging directories. Production EUID is root; fixtures use the CI EUID.
    """
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode), "symlink path requires manual review")
        if os.name == "posix":
            require(info.st_uid in (0, os.geteuid()), "unexpected path owner")
            require(not info.st_mode & 0o022 or
                    (stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and info.st_mode & stat.S_ISVTX),
                    "unsafe writable path")
        require(stat.S_ISDIR(info.st_mode) if item != path else
                stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), "unexpected path type")


def lock_path(path):
    safe_path(Path(path).parent)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600, "unsafe lock file")
        print(f"{info.st_dev}:{info.st_ino}")
    finally:
        os.close(fd)


# Fresh Telemt transaction ownership; ACME assets are deliberately outside it.
@contextmanager
def fresh_signal_window():
    blocked = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, blocked)


def fresh_ledger(path):
    safe_path(path)
    info = Path(path).lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600)
    value = json.loads(Path(path).read_text())
    require(value['schema'] == 1 and len(value['roots']) in (3,4))
    return value


def fresh_save(path, value):
    safe_path(path)
    fd, temporary = tempfile.mkstemp(dir=Path(path).parent, prefix='.fresh-ownership.')
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(value, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def fresh_init(path, *roots):
    require(len(roots) in (3,4) and len(set(roots)) == len(roots))
    for root in roots:
        safe_path(root)
        require(Path(root).is_absolute())
        if root == roots[2] and os.path.lexists(root): certificate_only_state(root)
        else: require(not os.path.lexists(root))
    safe_path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(dict(schema=1, roots=list(roots), directories=[], account=None,
                       pending_account=False, user_removed=False,
                       preserved_state=os.path.lexists(roots[2])), output)


def fresh_getent(database, key):
    result = subprocess.run(['getent', database, str(key)], capture_output=True, text=True)
    if result.returncode == 2:
        return None
    require(result.returncode == 0 and len(result.stdout.splitlines()) == 1)
    return result.stdout.rstrip('\n').split(':')


def fresh_passwd():
    result = subprocess.run(['getent', 'passwd'], capture_output=True, text=True)
    require(result.returncode == 0)
    entries = [line.split(':') for line in result.stdout.splitlines()]
    require(all(len(entry) == 7 for entry in entries))
    return entries


def fresh_identity(home):
    user, group = fresh_getent('passwd', 'telemt'), fresh_getent('group', 'telemt')
    require(user is not None and group is not None and len(user) == 7 and len(group) == 4)
    require(user[0] == group[0] == 'telemt' and user[2].isdigit() and user[3].isdigit()
            and group[2].isdigit() and int(user[2]) > 0 and int(user[3]) > 0
            and user[3] == group[2] and user[5:] == [home, '/usr/sbin/nologin'] and not group[3])
    require(fresh_getent('passwd', user[2]) == user and fresh_getent('group', group[2]) == group)
    entries = fresh_passwd()
    require([entry for entry in entries if entry[2] == user[2] or entry[3] == group[2]] == [user],
            'UID/GID shared with an unrelated account')
    return dict(user=user, group=group)


def fresh_account_create(path, home):
    with fresh_signal_window():
        value = fresh_ledger(path)
        require(home == value['roots'][1] and value['account'] is None)
        require(fresh_getent('passwd', 'telemt') is None and fresh_getent('group', 'telemt') is None)
        # An unsuccessful/partial useradd is not ownership proof: retain evidence
        # and require manual review rather than guessing from paths or names.
        value['pending_account'] = True
        fresh_save(path, value)
        subprocess.run(['useradd', '--system', '--user-group', '--home-dir', home,
                        '--no-create-home', '--shell', '/usr/sbin/nologin', 'telemt'], check=True)
        value['account'] = fresh_identity(home)
        value['pending_account'] = False
        fresh_save(path, value)


def fresh_mkdir(path, directory, mode):
    with fresh_signal_window():
        value = fresh_ledger(path)
        config, data, state = map(Path, value['roots'][:3])
        allowed = {config, data, data / 'public', data / 'state', state, *map(Path,value['roots'][3:])}
        directory = Path(directory)
        require(directory in allowed and directory.is_absolute() and mode in ('0750', '0700', '0755'))
        require(mode != '0755' or str(directory) in value['roots'][3:])
        safe_path(directory)
        # mkdir, never install -d: existing objects are not adopted or chmod'd.
        os.mkdir(directory, int(mode, 8))
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            value['directories'].append(dict(path=str(directory), dev=info.st_dev, ino=info.st_ino))
            fresh_save(path, value)
            # The manager's umask is 077. Match install -d -m semantics so
            # Telemt can traverse root:telemt config/data/public directories.
            os.fchmod(fd, int(mode, 8))
        finally: os.close(fd)


def fresh_account_quiet(value):
    require(not value['pending_account'], 'partial account creation requires manual review')
    account = value['account']
    if account is None: return
    require(fresh_identity(value['roots'][1]) == account, 'account identity changed')
    uid = int(account['user'][2])
    for process in Path('/proc').iterdir():
        if not process.name.isdigit(): continue
        try:
            text = (process / 'status').read_text()
        except (FileNotFoundError, ProcessLookupError):
            continue
        record = re.search(r'^Uid:\s+([0-9 \t]+)$', text, re.M)
        require(record is not None and uid not in map(int, record[1].split()), 'Telemt process still present')


def fresh_verify(path, *roots):
    value = fresh_ledger(path)
    require(list(roots) == value['roots'])
    fresh_account_quiet(value)
    allowed = set(roots) | {str(Path(roots[1]) / name) for name in ('public', 'state')}
    # st_dev alone misses same-device bind mounts. Check the kernel mount table
    # before touching files, including nested mounts inside runtime state.
    mounts = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        field = line.split()[4]
        mount = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), field)
        mounts.append(Path(mount))
    for root in map(Path, roots):
        require(not any(mount == root or mount.is_relative_to(root) for mount in mounts), 'fresh cleanup crosses a mount')
    for record in value['directories']:
        directory = Path(record['path'])
        require(str(directory) in allowed)
        safe_path(directory.parent)
        try: info = directory.lstat()
        except FileNotFoundError: continue
        owners = {0, os.geteuid()}
        if value['account']: owners.add(int(value['account']['user'][2]))
        require(stat.S_ISDIR(info.st_mode) and info.st_uid in owners
                and (info.st_dev, info.st_ino) == (record['dev'], record['ino']), 'created directory identity changed')
    return value


def fresh_cleanup_dirs(path, *roots):
    value = fresh_verify(path, *roots)
    records = {r['path']: r for r in value['directories']}
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    def clear(fd, device):
        with os.scandir(fd) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(entry.name, flags, dir_fd=fd)
                    try:
                        actual = os.fstat(child)
                        require(actual.st_dev == device and actual.st_ino == info.st_ino)
                        clear(child, device)
                    finally: os.close(child)
                    os.rmdir(entry.name, dir_fd=fd)
                else:
                    # Unlink symlinks and runtime files without following targets.
                    os.unlink(entry.name, dir_fd=fd)

    for root in reversed(roots):
        if root not in records: continue
        target = Path(root)
        parent = os.open(target.parent, flags)
        try:
            try: fd = os.open(target.name, flags, dir_fd=parent)
            except FileNotFoundError: continue
            try:
                info = os.fstat(fd)
                require((info.st_dev, info.st_ino) == (records[root]['dev'], records[root]['ino']))
                clear(fd, info.st_dev)
            finally: os.close(fd)
            os.rmdir(target.name, dir_fd=parent)
        finally: os.close(parent)


def fresh_cleanup_account(path, *roots):
    with fresh_signal_window():
        value = fresh_ledger(path)
        require(list(roots) == value['roots'] and not value['pending_account'])
        require(all(not os.path.lexists(root) for root in roots[:2]))
        if value.get("preserved_state"): certificate_only_state(roots[2])
        else: require(not os.path.lexists(roots[2]))
        if len(roots) == 4: require(not os.path.lexists(roots[3]))
        account = value['account']
        if account is None: return
        if not value['user_removed']:
            fresh_account_quiet(value)
            subprocess.run(['userdel', 'telemt'], check=True)  # Never -r or -f.
            require(fresh_getent('passwd', 'telemt') is None)
            value['user_removed'] = True
            fresh_save(path, value)
        require(fresh_getent('passwd', 'telemt') is None and fresh_getent('passwd', account['user'][2]) is None)
        require(not any(entry[3] == account['group'][2] for entry in fresh_passwd()), 'group still used by an account')
        group = fresh_getent('group', 'telemt')
        if group is not None:
            require(group == account['group'] and fresh_getent('group', group[2]) == group)
            subprocess.run(['groupdel', 'telemt'], check=True)
            require(fresh_getent('group', 'telemt') is None)
        value['account'] = None
        fresh_save(path, value)


def certificate_paths(root, host):
    domain(host)
    root = Path(root)
    safe_path(root)
    for name in ("fullchain", "privkey"):
        target = root / "live" / host / f"{name}.pem"
        safe_path(target.parent)
        actual = target.resolve(strict=True)
        require(actual.is_relative_to(root.resolve() / "archive" / host) or actual == target)
        safe_path(actual)
        require(actual.is_file())
        if name == "privkey":
            require(stat.S_IMODE(actual.stat().st_mode) & 0o077 == 0, "certificate key is not private")


def socks_address(value):
    host, port = value.rsplit(":", 1)
    require(port.isascii() and port.isdigit() and 0 < int(port) < 65536)
    if re.fullmatch(r"[0-9.]+", host):
        ipv4(host)
    elif host != "localhost":
        domain(host.lower())


def extract_binary(archive, output):
    # Never extract archive paths. Bound both member count and payload size;
    # reject hardlinks, symlinks, metadata-driven names and duplicate members.
    with tarfile.open(archive, "r:gz") as tar:
        first = tar.next()
        require(first is not None and first.name in ("telemt", "./telemt")
                and first.isfile() and 0 < first.size <= 128 * 1024 * 1024,
                "unsafe binary archive")
        require(tar.next() is None, "multiple archive members")
        with tar.extractfile(first) as source:
            fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o700)
            with os.fdopen(fd, "wb") as target:
                while block := source.read(1024 * 1024):
                    target.write(block)


def runtime_contract(path, data):
    c = read_config(path)
    managed_web_contract(c, data)
    general = c.get("general", {})
    require(general.get("use_middle_proxy") is False, "middle proxy requires runtime review")
    require(c.get("censorship", {}).get("tls_emulation") is False)
    require(c.get("logging", {}).get("destination", "stderr") == "stderr")
    require(general.get("data_path", data) == data)
    state = Path(data) / "state"
    paths = [general.get("quota_state_path", "telemt.limit.json")]
    if general.get("beobachten", True):
        paths.append(general.get("beobachten_file", "cache/beobachten.txt"))
    if general.get("unknown_dc_file_log_enabled", False):
        paths.append(general.get("unknown_dc_log_path", "unknown-dc.txt"))
    for value in paths:
        p = Path(value)
        require(p != state and p.is_absolute() and p.is_relative_to(state) and ".." not in p.parts,
                "active state path escapes systemd sandbox; manual review required")


def renewal_info(root, host):
    """Read Certbot sections without executing hooks or interpolating values."""
    host = domain(host)
    path = Path(root) / "renewal" / f"{host}.conf"
    safe_path(path)
    sections = {"": {}}
    section = ""
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line in ("[renewalparams]", "[[webroot_map]]"):
            section = line
            require(section not in sections, "duplicate renewal section")
            sections[section] = {}
        else:
            require(not line.startswith("[") and "=" in line, "unsupported renewal syntax")
            key, value = (part.strip() for part in line.split("=", 1))
            require(key not in sections[section], "duplicate renewal option")
            sections[section][key] = value
    params = sections.get("[renewalparams]", {})
    kind = params.get("authenticator")
    require(kind in ("standalone", "webroot"), "unrecognized certificate authenticator")
    for key in ("cert", "privkey", "chain", "fullchain"):
        expected = str(Path(root) / "live" / host / f"{key}.pem")
        require(sections[""].get(key, expected) == expected, "foreign certificate lineage")
    expected = str(Path(root) / "archive" / host)
    require(sections[""].get("archive_dir", expected) == expected)
    return kind, params, sections.get("[[webroot_map]]", {})


def renewal_contract(root, host, webroot):
    kind, params, mapping = renewal_info(root, host)
    require(kind == "webroot")
    require(params.get("webroot_path", "").rstrip(",") == str(webroot))
    require(not mapping or mapping == {host: str(webroot)}, "foreign renewal webroot map")


def renewal_kind(root, host, webroot):
    kind, params, mapping = renewal_info(root, host)
    if kind == "webroot":
        renewal_contract(root, host, webroot)
    else:
        require(not params.get("webroot_path") and not mapping)
    print(kind)


def acme_state(root, host, webroot):
    """Accept only complete persistent manager state for webroot renewal."""
    webroot = Path(webroot)
    for path in (webroot, webroot / ".well-known", webroot / ".well-known/acme-challenge"):
        safe_path(path)
        require(path.is_dir(), "ACME webroot incomplete")
    marker = webroot / ".telemt-web-manager"
    safe_path(marker)
    require(marker.is_file() and marker.read_text() == host + "\n", "ACME marker missing or changed")
    vhost = Path(root) / "conf.d/telemt-web-manager-acme.conf"
    safe_path(vhost)
    require(vhost.is_file() and vhost.read_text() == render_acme(host, webroot),
            "ACME vhost missing or changed")
    parser = Nginx(root)
    nodes = parser.read(parser.root / "nginx.conf")
    http = exact(nodes, "http")
    require(len(http) == 1 and sum(n.path == vhost.resolve()
                                  for n in exact(http[0].children, "server")) == 1,
            "ACME vhost not included exactly once")


def domain(value):
    require(len(value) <= 253 and "." in value and all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", x)
        for x in value.split(".")), "invalid domain (use lowercase ASCII/punycode)")
    return value


def ipv4(value):
    require(ipaddress.ip_address(value).version == 4, "expected IPv4 address")
    return value


def dns_check(a_text, aaaa_text, expected):
    ipv4(expected)
    require(not any(line.lstrip().startswith(';;') for line in a_text.splitlines()),
            'DNS A query diagnostic; retry after checking DNS')
    require(not any(line.lstrip().startswith(';;') for line in aaaa_text.splitlines()),
            'DNS AAAA query diagnostic; retry after checking DNS')
    def addresses(text):
        for item in text.splitlines():
            item = item.strip()
            if not item: continue
            try:
                address = ipaddress.ip_address(item)
            except ValueError:
                # Both dig answers may contain CNAME targets, even without AAAA.
                continue
            yield address
    resolved = list(addresses(a_text))
    require(resolved, "DNS A missing: the domain or CNAME chain has no final IPv4 address")
    require(len(resolved) == 1, "DNS A has multiple IPv4 addresses; keep only the server IPv4")
    require(str(resolved[0]) == expected, "DNS A points to another IPv4; it must match the server IPv4")
    for address in addresses(aaaa_text):
        require(address.version == 6 and address.ipv4_mapped is None,
                "DNS AAAA is not a real IPv6 address")
        require(False, "DNS AAAA exists: remove the IPv6 record before installing this IPv4 proxy")


@dataclass
class Node:
    args: list
    children: object
    path: Path
    start: int
    close: int
    data_record: bool = False


class Nginx:
    def __init__(self, root):
        safe_path(root)
        self.root = Path(root).resolve()
        self.sources = {}
        self.stack = []
        self.reads = 0

    def read(self, path, context="directives"):
        path = Path(path).resolve()
        require(not any(c in str(path) for c in "\t\r\n"), "unsupported Nginx filename")
        external_module = path.is_relative_to(Path("/usr/share/nginx/modules-available"))
        require(path.is_relative_to(self.root) or external_module, "Nginx include escapes config directory")
        safe_path(path)
        # A shared HTTP snippet can be included by several vhosts. Only an
        # active recursion is a cycle; each inclusion gets its own AST nodes.
        self.reads += 1
        require(path not in self.stack and self.reads <= 256 and len(self.stack) < 32,
                "cyclic or excessive Nginx includes")
        self.stack.append(path)
        with path.open('rb') as input_file:
            source = input_file.read(1024 * 1024 + 1).decode("utf-8")
        require(len(source) <= 1024 * 1024, "Nginx source exceeds parser limit")
        self.sources[path] = source
        tokens = nginx_tokens(source)
        position = 0

        def parse(nested=False, context="directives"):
            nonlocal position
            nodes = []
            while position < len(tokens):
                if tokens[position][0] == "}":
                    require(nested)
                    close = tokens[position][1]
                    position += 1
                    return nodes, close
                args = []
                start = tokens[position][1]
                while position < len(tokens) and tokens[position][0] not in ("{", "}", ";"):
                    token = tokens[position][0]
                    args.append(token[1:-1] if token.startswith(('"', "'")) else token)
                    position += 1
                require(args and position < len(tokens))
                if context == "directives":
                    require(re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]*", args[0]),
                            "escaped or unknown Nginx directive name")
                terminator, close = tokens[position]
                position += 1
                require(terminator != "}")
                children = None
                if context == "types":
                    require(terminator == ";", "nested MIME records are unsupported")
                if terminator == "{":
                    if args[0] == "types":
                        require(args == ["types"])
                    child_context = args[0] if args[0] in ("map", "types") else "directives"
                    children, close = parse(True, child_context)
                node = Node(args, children, path, start, close, context == "types")
                nodes.append(node)
                if args[0] == "include" and context != "types":
                    require(children is None and len(args) == 2
                            and not any(c in args[1] for c in "$\\"))
                    include = Path(args[1])
                    if not include.is_absolute():
                        include = self.root / include
                    node.children = []
                    matches = sorted(glob.glob(str(include)))
                    require(matches or any(c in str(include) for c in "*?["))
                    for item in matches:
                        node.children.extend(self.read(item, context))
            require(not nested)
            return nodes, len(source)

        nodes, _ = parse(context=context)
        if external_module:
            require(all(n.args[0] == "load_module" and n.children is None for n in nodes))
        self.stack.pop()
        return nodes


def expand(nodes):
    for node in nodes:
        if node.data_record:
            continue
        if node.args[0] == "include":
            yield from expand(node.children)
        else:
            yield node


def walk(nodes):
    for node in nodes:
        if node.data_record:
            continue
        yield node
        if node.children:
            yield from walk(node.children)


def exact(nodes, key):
    return [n for n in expand(nodes) if n.args[0] == key]


def nginx_tokens(source):
    """Track syntax boundaries without interpreting regex/escape expressions.

    Preserve escaped pairs in token values: critical routing directives below
    accept only exact literals. Quotes, escaped delimiters and ${variables} in
    unrelated HTTP directives cannot manufacture a block or hide a listener.
    """
    tokens = []
    i = 0
    while i < len(source):
        if source[i].isspace():
            i += 1
            continue
        if source[i] == "#":
            end = source.find("\n", i)
            i = len(source) if end < 0 else end + 1
            continue
        start = i
        if source[i] in "{};":
            tokens.append((source[i], i))
            i += 1
            continue
        chars = []
        quote = source[i] if source[i] in "\"'" else None
        if quote:
            chars.append(quote)
            i += 1
        closed = not quote
        while i < len(source):
            c = source[i]
            if c == "\\":
                require(i + 1 < len(source), "incomplete Nginx escape")
                chars.append(source[i:i + 2])
                i += 2
            elif quote and c == quote:
                chars.append(c)
                i += 1
                closed = True
                break
            elif not quote and source.startswith("${", i):
                variable = re.match(r"\$\{[a-zA-Z_][a-zA-Z_0-9]*\}", source[i:])
                require(variable is not None, "unsupported Nginx variable syntax")
                chars.append(variable.group())
                i += len(variable.group())
            elif not quote and (c.isspace() or c in "{};#"):
                break
            else:
                require(quote or c not in "\"'", "mixed Nginx quote syntax")
                chars.append(c)
                i += 1
        require(closed and chars, "unterminated Nginx token")
        if quote:
            require(i == len(source) or source[i].isspace() or source[i] in ";{}#)",
                    "concatenated Nginx tokens")
        tokens.append(("".join(chars), start))
    return tokens


def nginx_stream_includes(parser, nodes, stream, mapping):
    """Recognize only the two active, correctly scoped 3X-UI extension points."""
    paths = [parser.root / name for name in ('stream-sni.d', 'stream-upstreams.d')]
    found = []
    for directory, context in zip(paths, (mapping, stream)):
        matches = [n for n in walk(nodes) if n.args[0] == 'include' and len(n.args) == 2
                   and str(parser.root / n.args[1]) == str(directory / '*.conf')]
        require(len(matches) <= 1, 'duplicate stream extension point')
        if matches:
            # Include wrappers may lead to the stream, but never through another
            # map/server/upstream block. Only direct directives at this level.
            def level(items):
                for node in items:
                    yield node
                    if node.args[0] == 'include': yield from level(node.children)
            require(matches[0] in list(level(context.children)), 'misplaced stream extension point')
        found.append(bool(matches))
    require(found[0] == found[1], 'incomplete stream extension contract')
    if all(found):
        for directory in paths:
            safe_path(directory)
            require(directory.is_dir(), 'stream extension directory missing')
            info = directory.stat()
            require(info.st_uid == os.geteuid() and info.st_gid == os.getegid()
                    and stat.S_IMODE(info.st_mode) == 0o755, 'unsafe stream extension directory')
    return all(found)


def nginx_stream_files(parser, host):
    return ((parser.root / 'stream-sni.d/telemt-web-manager.conf', f'{host} twm_frontend;\n'),
            (parser.root / 'stream-upstreams.d/telemt-web-manager.conf',
             'upstream twm_frontend {\n    server 127.0.0.1:7444;\n}\n'))


def nginx_owned_stream(parser, host, stream):
    """Exact owned fragments, independent of unrelated stream configuration."""
    mappings=[n for n in exact(stream.children,'map') if len(n.args)==3 and n.args[1]=='$ssl_preread_server_name']
    require(len(mappings)==1)
    rows=[n for n in expand(mappings[0].children) if n.args[0]==host]
    upstreams=[n for n in exact(stream.children,'upstream') if n.args==['upstream','twm_frontend']]
    require(len(rows)==len(upstreams)==1 and rows[0].args==[host,'twm_frontend'] and rows[0].children is None)
    require([n.args for n in expand(upstreams[0].children)]==[['server','127.0.0.1:7444']])
    require(sum('twm_frontend' in n.args for n in walk(stream.children))==2,
            'managed upstream shared or substituted')
    ranges={}; managed={}
    files = nginx_stream_files(parser, host)
    included = (rows[0].path == files[0][0], upstreams[0].path == files[1][0])
    require(included[0] == included[1], 'mixed stream ownership formats')
    if all(included):
        for key, node, (path, literal) in zip(('nginx-map', 'nginx-upstream'),
                                             (rows[0], upstreams[0]), files):
            safe_path(path)
            info = path.lstat()
            require(info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o644,
                    'unsafe managed stream file')
            require(parser.sources[path] == literal, 'managed stream file changed')
            managed[key] = hashlib.sha256((str(path.relative_to(parser.root))+'\0'+literal).encode()).hexdigest()
            ranges[path] = None  # Entire proven-owned include, not a shared file.
        return managed, ranges
    require(not any(os.path.lexists(path) for path, _ in files), 'orphan managed stream file')
    for node,literal in ((rows[0],f'    {host} twm_frontend; # telemt-web-manager\n'),
                        (upstreams[0],'\n# telemt-web-manager\nupstream twm_frontend { server 127.0.0.1:7444; }\n')):
        source=parser.sources[node.path]; line_start=source.rfind('\n',0,node.start)+1
        start=node.start-4 if node==rows[0] else line_start-len('\n# telemt-web-manager\n')
        if node==rows[0]: require(start>=line_start and not source[line_start:start].strip())
        require(start>=0 and source[start:start+len(literal)]==literal,'managed stream entry changed')
        key='nginx-map' if node==rows[0] else 'nginx-upstream'
        managed[key]=hashlib.sha256((str(node.path.relative_to(parser.root))+'\0'+literal).encode()).hexdigest()
        ranges.setdefault(node.path,[]).append((start,start+len(literal)))
    return managed,ranges


def nginx_web_backend(http, vhost):
    """The HTTP connection cache must never be defined or shared by a neighbor."""
    for node in walk(http.children):
        if node.path == vhost:
            continue
        # Nginx strips quotes and escaped literal characters in upstream names.
        args = [re.sub(r'\\(.)', r'\1', arg).lower() for arg in node.args]
        require(not any('twpm_web_backend' in arg for arg in args),
                'managed HTTP upstream name used outside owned vhost')
        if args[0] == 'proxy_pass' and len(args) == 2:
            authority = args[1].split('://', 1)[-1].split('/', 1)[0].split('?', 1)[0]
            # A fixed host with a variable port/query (the legacy 3X-UI
            # snippet) cannot name this cache. A variable hostname can.
            require('$' not in authority.split(':', 1)[0],
                    'dynamic HTTP upstream hostname needs manual review')


def nginx_plan(root, host, output, acme_root="/var/lib/telemt-web-manager-acme", uninstall=False,
               keepalive=False, site_digest=None, site_port=18081, manifest=None):
    installed = uninstall or keepalive or (manifest is not None and Path(manifest).is_file())
    domain(host)
    if site_digest is not None:
        require(type(site_port) is int and 18081 <= site_port <= 18090, 'unsupported origin port')
    parser = Nginx(root)
    nodes = parser.read(Path(root) / "nginx.conf")
    streams, https = exact(nodes, "stream"), exact(nodes, "http")
    require(len(streams) == len(https) == 1)
    stream, http = streams[0], https[0]
    require(all(n.args[0] in ("map", "upstream", "server", "map_hash_bucket_size")
                for n in expand(stream.children)),
            "unknown stream context directive")
    buckets = exact(stream.children, "map_hash_bucket_size")
    require(not buckets or (len(buckets) == 1 and buckets[0].args == ["map_hash_bucket_size", "272"]
                            and buckets[0].children is None), "unknown stream hash bucket contract")
    maps = exact(stream.children, "map")
    routers = exact(stream.children, "server")
    require(len(maps) == len(routers) == 1)
    mapping, router = maps[0], routers[0]
    require(len(mapping.args) == 3 and mapping.args[1] == "$ssl_preread_server_name"
            and re.fullmatch(r"\$[a-zA-Z_][a-zA-Z_0-9]*", mapping.args[2]))
    include_contract = nginx_stream_includes(parser, nodes, stream, mapping)
    stream_files = nginx_stream_files(parser, host)
    directives = [n.args for n in expand(router.children)]
    allowed = {"listen", "proxy_pass", "ssl_preread", "proxy_protocol", "proxy_timeout",
               "proxy_connect_timeout", "access_log", "error_log", "tcp_nodelay",
               "set_real_ip_from"}
    require(all(d[0] in allowed for d in directives)
            and all(n.children is None for n in expand(router.children)))
    trusted = [d for d in directives if d[0] == "set_real_ip_from"]
    require(trusted in ([], [["set_real_ip_from", "unix:"]]),
            "unexpected stream PROXY trust boundary")
    for required in (["ssl_preread", "on"], ["proxy_protocol", "on"],
                     ["proxy_pass", mapping.args[2]]):
        require([d for d in directives if d[0] == required[0]] == [required])
    listens = [d[1:] for d in directives if d[0] == "listen"]
    # Existing IPv6 ingress does not enable IPv6 Telemt egress or permit an AAAA
    # record for the new WEB hostname. Never edit these existing listen lines.
    require(len(listens) in (1, 2) and len({tuple(x) for x in listens}) == len(listens))
    require(sum(x in (["443"], ["0.0.0.0:443"]) for x in listens) == 1)
    require(all(x in (["443"], ["0.0.0.0:443"], ["[::]:443"]) for x in listens))
    entries = list(expand(mapping.children))
    hostname_flags = [n for n in entries if n.args[0] == "hostnames"]
    require(not hostname_flags or (len(hostname_flags) == 1 and entries[0] == hostname_flags[0]
                                   and hostname_flags[0].args == ["hostnames"]
                                   and hostname_flags[0].children is None))
    entries = [n for n in entries if n.args[0] != "hostnames"]
    require(sum(n.args[0] == "default" for n in entries) == 1)
    require(len({n.args[0] for n in entries}) == len(entries))
    for n in entries:
        require(n.children is None and len(n.args) == 2)
        if n.args[0] != "default":
            domain(n.args[0]) # Exact names only, even with the hostnames flag.
        require(re.fullmatch(r"[A-Za-z0-9_.:-]+", n.args[1]))
    upstreams = exact(stream.children, "upstream")
    require(all(len(n.args) == 2 and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", n.args[1]) for n in upstreams))
    require(len({n.args[1] for n in upstreams}) == len(upstreams))
    for upstream in upstreams:
        members = list(expand(upstream.children))
        # 3X-UI PR #99: the reviewed REALITY primary/cover fallback pair.
        # All other stream upstreams retain the historical single-server rule.
        if (upstream.args == ["upstream", "xray"]
                and [n.args for n in members] ==
                [["server", "127.0.0.1:8443", "max_fails=0"],
                 ["server", "127.0.0.1:9443", "backup"]]
                and all(n.children is None for n in members)):
            continue
        require(len(members) == 1 and members[0].children is None
                and len(members[0].args) == 2 and members[0].args[0] == "server"
                and re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", members[0].args[1])
                and 0 < int(members[0].args[1].rsplit(":", 1)[1]) < 65536,
                "unknown stream upstream contract")
    require(all(n.args[1] in {u.args[1] for u in upstreams} for n in entries),
            "map target is not a recognized upstream")
    owned = [n for n in upstreams if n.args == ["upstream", "twm_frontend"]]
    existing = [n for n in entries if n.args[0] == host]
    vhost = parser.root / "conf.d" / "telemt-web-manager.conf"
    safe_path(vhost)
    owned_site = site_vhost_digest(vhost.read_text()) if vhost.exists() else None
    owned_port = site_vhost_port(vhost.read_text()) if owned_site else None
    if site_digest is not None and owned_port is not None:
        require(site_port == owned_port, 'managed origin port changed')
    origin_port = owned_port if owned_port is not None else site_port
    # Legacy checks/removal do not claim a new HTTP symbol. Fresh/new vhosts
    # and explicit optimization must prove exclusive use before publishing it.
    if keepalive or site_digest or owned_site or not vhost.exists() or vhost.read_text() == render_vhost(host):
        nginx_web_backend(http, vhost)
    acme = parser.root / "conf.d" / "telemt-web-manager-acme.conf"
    if acme.exists() or acme.is_symlink():
        safe_path(acme)
        require(acme.read_text() == render_acme(host, acme_root), "changed ACME vhost")
        require(sum(n.path == acme and n.args[0] == "server" for n in walk(nodes)) == 1)
    # Only an actual top-level http include proves where the new vhost is loaded.
    includes = [n for n in http.children if n.args[0] == "include"]
    require(any(str((parser.root / n.args[1]).resolve()) ==
                str(parser.root / "conf.d" / "*.conf") for n in includes))
    # No competing HTTPS socket, domain, managed symbol or internal port anywhere.
    for n in walk(nodes):
        if n.path in (vhost, acme):
            continue
        if n.args[0] == "server_name":
            if host in n.args[1:]:
                raise NginxDomainInUse()
        if n.args[0] == "listen" and n not in exact(router.children, "listen"):
            require(len(n.args) >= 2)
            address = n.args[1]
            require(re.fullmatch(r"[0-9]+|[0-9.]+:[0-9]+|\[[0-9a-fA-F:]+\]:[0-9]+|unix:/[^\s\\$]+", address),
                    "ambiguous Nginx listen address")
            if not address.startswith("unix:"):
                require(int(address.rsplit(":", 1)[-1]) not in
                        ((443,7444,18080,origin_port) if site_digest or owned_site else (443,7444,18080)))
    edits = {}
    if existing or owned or vhost.exists():
        valid = len(existing) == len(owned) == 1 and vhost.exists()
        if installed:
            require(valid, "Incomplete manager Nginx files in /etc/nginx and /etc/nginx/conf.d/telemt-web-manager.conf. The Nginx connection differs from the one created by this manager. Nothing changed; manual review required. Keep Let's Encrypt certificates. / Неполный набор файлов подключения менеджера к Nginx в /etc/nginx и /etc/nginx/conf.d/telemt-web-manager.conf. Подключение к Nginx отличается от созданного менеджером. Изменений нет; нужна ручная проверка. Сертификаты Let's Encrypt сохраните.")
        else:
            require(valid,
                    'Incomplete manager files in /etc/nginx and /etc/nginx/conf.d/telemt-web-manager.conf; possible files from another server (restored 3x-ui backup). This check changed nothing; save a copy or remove leftovers manually. Keep needed Let\'s Encrypt certificates. / '
                    'Неполный набор файлов менеджера в /etc/nginx и /etc/nginx/conf.d/telemt-web-manager.conf; возможно, с другого сервера (восстановленный бэкап 3x-ui). Проверка ничего не меняла; сохраните копию или уберите остатки вручную. Нужные сертификаты Let\'s Encrypt сохраните.')
        valid = existing[0].args == [host, "twm_frontend"]
        if installed:
            require(valid, "Manager domain mapping differs in /etc/nginx/nginx.conf and included stream files. The Nginx connection differs from the one created by this manager. Nothing changed; manual review required. Keep Let's Encrypt certificates. / Маршрут домена менеджера в /etc/nginx/nginx.conf и подключённых stream-файлах отличается. Подключение к Nginx отличается от созданного менеджером. Изменений нет; нужна ручная проверка. Сертификаты Let's Encrypt сохраните.")
        else:
            require(valid,
                    'Manager domain mapping differs in /etc/nginx; possible files from another server (3x-ui backup). No changes; save a copy or remove leftovers manually. Keep needed Let\'s Encrypt certificates. / '
                    'Маршрут домена менеджера в /etc/nginx отличается; возможны файлы с другого сервера (бэкап 3x-ui). Изменений нет; сохраните копию или уберите остатки вручную. Нужные сертификаты Let\'s Encrypt сохраните.')
        valid = [n.args for n in expand(owned[0].children)] == [["server", "127.0.0.1:7444"]]
        if installed:
            require(valid, "Manager upstream differs in /etc/nginx/nginx.conf and included stream files. The Nginx connection differs from the one created by this manager. Nothing changed; manual review required. Keep Let's Encrypt certificates. / Подключение менеджера через upstream в /etc/nginx/nginx.conf и подключённых stream-файлах отличается. Подключение к Nginx отличается от созданного менеджером. Изменений нет; нужна ручная проверка. Сертификаты Let's Encrypt сохраните.")
        else:
            require(valid,
                    'Manager upstream differs in /etc/nginx; possible files from another server (3x-ui backup). No changes; save a copy or remove leftovers manually. Keep needed Let\'s Encrypt certificates. / '
                    'Upstream менеджера в /etc/nginx отличается; возможны файлы с другого сервера (бэкап 3x-ui). Изменений нет; сохраните копию или уберите остатки вручную. Нужные сертификаты Let\'s Encrypt сохраните.')
        valid = vhost.read_text() in (render_vhost(host), render_vhost(host, keepalive=False),
                                     render_vhost(host,site_digest=owned_site,site_port=origin_port))
        if installed:
            require(valid, "Manager vhost differs: /etc/nginx/conf.d/telemt-web-manager.conf. The Nginx connection differs from the one created by this manager. Nothing changed; manual review required. Keep Let's Encrypt certificates. / Файл подключения менеджера /etc/nginx/conf.d/telemt-web-manager.conf отличается. Подключение к Nginx отличается от созданного менеджером. Изменений нет; нужна ручная проверка. Сертификаты Let's Encrypt сохраните.")
        else:
            require(valid,
                    'Manager vhost differs: /etc/nginx/conf.d/telemt-web-manager.conf; possible files from another server (3x-ui backup). No changes; save a copy or remove leftovers manually. Keep needed Let\'s Encrypt certificates. / '
                    'Vhost менеджера отличается: /etc/nginx/conf.d/telemt-web-manager.conf; возможны файлы с другого сервера (бэкап 3x-ui). Изменений нет; сохраните копию или уберите остатки вручную. Нужные сертификаты Let\'s Encrypt сохраните.')
        if site_digest: require(owned_site == site_digest, 'site creation cannot migrate an existing vhost')
        active = [n for n in expand(http.children) if n.path == vhost]
        require([n.args[0] for n in active] ==
                (['upstream','server','server'] if owned_site else
                 ['upstream','server'] if vhost.read_text() == render_vhost(host) else ['server']),
                'managed HTTP vhost missing, duplicated or misplaced')
        managed, ranges = nginx_owned_stream(parser, host, stream)
        if any(spans is None for spans in ranges.values()):
            require(include_contract, 'managed stream includes inactive')
    else:
        valid = not any(os.path.lexists(path) for path, _ in stream_files)
        if installed:
            require(valid, "Incomplete manager files: /etc/nginx/stream-sni.d/telemt-web-manager.conf or /etc/nginx/stream-upstreams.d/telemt-web-manager.conf. The Nginx connection differs from the one created by this manager. Nothing changed; manual review required. Keep Let's Encrypt certificates. / Неполное подключение менеджера: /etc/nginx/stream-sni.d/telemt-web-manager.conf или /etc/nginx/stream-upstreams.d/telemt-web-manager.conf. Подключение к Nginx отличается от созданного менеджером. Изменений нет; нужна ручная проверка. Сертификаты Let's Encrypt сохраните.")
        else:
            require(valid,
                    'Orphan manager files: /etc/nginx/stream-sni.d/telemt-web-manager.conf or /etc/nginx/stream-upstreams.d/telemt-web-manager.conf; possible files from another server (3x-ui backup). No changes; save a copy or remove leftovers manually. Keep needed Let\'s Encrypt certificates. / '
                    'Остались файлы менеджера: /etc/nginx/stream-sni.d/telemt-web-manager.conf или /etc/nginx/stream-upstreams.d/telemt-web-manager.conf; возможно, с другого сервера (бэкап 3x-ui). Изменений нет; сохраните копию или уберите остатки вручную. Нужные сертификаты Let\'s Encrypt сохраните.')
    if not (existing or owned or vhost.exists()) and include_contract:
        for path, literal in stream_files:
            safe_path(path)
            edits[path] = literal
        edits[vhost] = render_vhost(host,site_digest=site_digest,site_port=origin_port)
    elif not (existing or owned or vhost.exists()):
        source = parser.sources[mapping.path]
        require(mapping.path == stream.path or mapping.path.is_relative_to(parser.root))
        edits[mapping.path] = source[:mapping.close] + f"    {host} twm_frontend; # telemt-web-manager\n" + source[mapping.close:]
        # Append upstream in the same physical file directly after the map block.
        shifted = mapping.close + len(f"    {host} twm_frontend; # telemt-web-manager\n") + 1
        content = edits[mapping.path]
        edits[mapping.path] = content[:shifted] + "\n# telemt-web-manager\nupstream twm_frontend { server 127.0.0.1:7444; }\n" + content[shifted:]
        edits[vhost] = render_vhost(host,site_digest=site_digest,site_port=origin_port)
    if keepalive:
        require(not uninstall and len(existing) == len(owned) == 1 and vhost.exists())
        if vhost.read_text() == render_vhost(host,keepalive=False): edits[vhost] = render_vhost(host)
    if uninstall:
        require(len(existing) == len(owned) == 1 and vhost.exists())
        require([n for n in entries if n.args[1] == "twm_frontend"] == existing,
                "managed upstream shared by another route")
        require(sum("twm_frontend" in n.args for n in walk(nodes)) == 2)
        managed,ranges = nginx_owned_stream(parser,host,stream)
        for path, spans in ranges.items():
            if spans is None:
                edits[path] = None
                continue
            content = parser.sources[path]
            for start, end in sorted(spans, reverse=True): content = content[:start] + content[end:]
            edits[path] = content
        edits[vhost] = None
    snapshot = {str(p): hashlib.sha256(s.encode()).hexdigest() for p, s in parser.sources.items()}
    plan = {"snapshot": snapshot, "edits": [{"path": str(p), "content": s,
            "old": base64.b64encode(p.read_bytes()).decode() if p.exists() else None}
            for p, s in edits.items()]}
    Path(output).write_text(json.dumps(plan))
    if uninstall: return managed


def nginx_keepalive_plan(root, host, output, acme_root, manifest):
    # Bind the explicit single-vhost plan to the original manifest as well as
    # the entire active Nginx include tree. apply_nginx rechecks both snapshots.
    raw = update_read(Path(manifest), 16384)
    value = update_json(raw, 16384)
    update_exact(value, {'schema','domain','public_ip','unit_sha256','nginx_sha256','acme_webroot'})
    require(type(value['schema']) is int and value['schema'] == 1 and value['domain'] == host)
    nginx_plan(root, host, output, acme_root, keepalive=True)
    plan = json.loads(Path(output).read_text())
    vhost = str(Path(root).resolve() / 'conf.d/telemt-web-manager.conf')
    require(plan['snapshot'][vhost] == value['nginx_sha256'], 'Nginx manifest hash differs')
    plan['snapshot'][str(Path(manifest))] = hashlib.sha256(raw).hexdigest()
    Path(output).write_text(json.dumps(plan))


def render_acme(host, webroot):
    domain(host)
    require(re.fullmatch(r"/[A-Za-z0-9_./-]+", str(webroot)) and ".." not in Path(webroot).parts)
    return f'''# Managed by telemt-web-manager v1. Persistent ACME webroot.
server {{
    listen 80;
    server_name {host};
    access_log off;
    error_log /dev/null crit;
    location ^~ /.well-known/acme-challenge/ {{
        root {webroot};
        default_type text/plain;
        try_files $uri =404;
    }}
    location / {{ return 404; }}
}}
'''


def acme_plan(root, host, output, webroot):
    # Reuse the WEB contract before permitting any HTTP mutation.
    nginx_plan(root, host, output, webroot)
    parser = Nginx(root)
    nodes = parser.read(parser.root / "nginx.conf")
    http = exact(nodes, "http")[0]
    acme = parser.root / "conf.d/telemt-web-manager-acme.conf"
    port80 = set()
    for server in exact(http.children, "server"):
        if server.path == acme:
            continue
        names = exact(server.children, "server_name")
        require(len(names) == 1)
        for name in names[0].args[1:]:
            if name != "_":
                domain(name) # No wildcard/regex/escaped/dynamic name precedence.
            require(name != host or server.path.name == "telemt-web-manager.conf")
        listens = exact(server.children, "listen")
        if not any(n.args[1] in ("80", "0.0.0.0:80", "[::]:80") for n in listens):
            continue
        require(len(listens) in (1, 2)
                and sum(n.args in (["listen", "80"], ["listen", "0.0.0.0:80"]) for n in listens) == 1)
        require(len({tuple(n.args) for n in listens}) == len(listens)
                and all(n.args in (["listen", "80"], ["listen", "0.0.0.0:80"],
                                   ["listen", "[::]:80"]) for n in listens))
        # Nginx selects our separate exact-name :80 server before evaluating
        # any foreign server's rewrites, Host guards or locations. Their content
        # is not TWPM ownership evidence and is never edited by this plan.
        require(len(names[0].args) > 1 and len(set(names[0].args[1:])) == len(names[0].args[1:]))
        for other in exact(http.children, "server"):
            if other is server or other.path == acme: continue
            if any(n.args[1] in ("80", "0.0.0.0:80", "[::]:80") for n in exact(other.children, "listen")):
                require(not set(names[0].args[1:]).intersection(
                    name for n in exact(other.children, "server_name") for name in n.args[1:]),
                    "ambiguous port 80 names")
        port80.update(id(n) for n in listens)
    for n in walk(nodes):
        if n.args[0] == "listen" and n.path != acme:
            if n.args[1].rsplit(":", 1)[-1].isdigit() and int(n.args[1].rsplit(":", 1)[-1]) == 80:
                require(id(n) in port80, "unrecognized port 80 topology")
    edits = []
    if not acme.exists():
        safe_path(acme)
        edits = [{"path": str(acme), "content": render_acme(host, webroot), "old": None}]
    Path(output).write_text(json.dumps({
        "snapshot": {str(p): hashlib.sha256(s.encode()).hexdigest() for p, s in parser.sources.items()},
        "edits": edits}))


def port80_config(root):
    parser = Nginx(root)
    nodes = parser.read(parser.root / "nginx.conf")
    print(int(any(n.args[0] == "listen" and len(n.args) >= 2
                  and n.args[1].rsplit(":", 1)[-1].isdigit()
                  and int(n.args[1].rsplit(":", 1)[-1]) == 80 for n in walk(nodes))))


def decoy_origin_port(decoy):
    require(type(decoy) is dict and set(decoy) == {'mode','upstream'}
            and decoy['mode'] == 'http_upstream', 'decoy contract changed')
    upstream = decoy.get('upstream')
    require(type(upstream) is str
            and re.fullmatch(r'http://127\.0\.0\.1:(1808[1-9]|18090)', upstream),
            'decoy contract changed')
    return int(upstream.rsplit(':', 1)[1])


def render_site_server(directory=None, port=18081):
    directory = str(directory or SITE_ROOT)
    require(re.fullmatch(r'/[A-Za-z0-9_./-]+',directory) and '..' not in Path(directory).parts)
    require(type(port) is int and 18081 <= port <= 18090, 'unsupported origin port')
    return f'''server {{
    listen 127.0.0.1:{port};
    server_name _;
    root {directory};
    index index.html;
    absolute_redirect off;
    server_tokens off;
    autoindex off;
    charset utf-8;
    access_log off;
    error_log /dev/null crit;
    default_type application/octet-stream;
    types {{
        text/html html;
        text/css css;
        image/svg+xml svg;
        image/x-icon ico;
        text/plain txt;
    }}
    add_header Content-Security-Policy "default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'" always;
    error_page 404 /404.html;
    location / {{ try_files $uri $uri/ =404; }}
}}
'''


def render_vhost(host, keepalive=True, site_digest=None, site_port=18081):
    require(site_digest is None or (keepalive and re.fullmatch(r'[0-9a-f]{64}',site_digest)))
    upstream = ('upstream twpm_web_backend {\n    server 127.0.0.1:18080;\n    keepalive 32;\n}\n'
                if keepalive else '')
    if site_digest: upstream = f'# TWPM original site v0.3 sha256: {site_digest}\n'+upstream
    backend = 'twpm_web_backend' if keepalive else '127.0.0.1:18080'
    return f'''# Managed by telemt-web-manager v1. Manual changes require review.
{upstream}server {{
    listen 127.0.0.1:7444 ssl http2 proxy_protocol;
    server_name {host};
    set_real_ip_from 127.0.0.1;
    real_ip_header proxy_protocol;
    access_log off;
    error_log /dev/null crit;
    ssl_certificate /etc/letsencrypt/live/{host}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{host}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 2m;
    client_body_timeout 90s;
    send_timeout 90s;
    location / {{
        proxy_pass http://{backend};
        proxy_http_version 1.1;
        proxy_set_header Host {host};
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header Connection "";
        proxy_set_header Upgrade "";
        proxy_connect_timeout 5s;
        proxy_read_timeout 90s;
        proxy_send_timeout 90s;
        proxy_request_buffering off;
        proxy_buffering off;
        proxy_next_upstream off;
    }}
}}
'''+(render_site_server(port=site_port) if site_digest else '')


def read_config(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size<=1024*1024)
        raw=os.read(fd,1024*1024+1)
        require(len(raw)==info.st_size and UpdateTree.same(info)==UpdateTree.same(os.fstat(fd)))
    finally: os.close(fd)
    require(not re.search(rb"(?m)^\s*include\s*=", raw), "config includes need manual review")
    c = tomllib.loads(raw.decode())
    require(not any(k in c for k in ("include", "includes")), "config includes need manual review")
    return c


def managed_web_contract(c, data):
    general = c.get("general", {})
    require(general.get("config_strict") is True, "strict config required")
    modes = general.get("modes", {})
    require(modes.get("classic", False) is False and modes.get("secure") is True
            and modes.get("tls", True) is False, "unsupported WEB-only modes")
    require(c.get("censorship", {}).get("mask") is False
            and c.get("censorship", {}).get("tls_emulation") is False)
    network = c.get("network", {})
    require(network.get("ipv4", True) is True and network.get("ipv6") is False
            and type(network.get("prefer", 4)) is int and network.get("prefer", 4) == 4
            and general.get("prefer_ipv6", False) is False, "unsupported IP family contract")
    require(network.get("multipath", False) is False and not network.get("dns_overrides"),
            "network routing overrides need review")
    server = c.get("server", {})
    require(type(server.get("port")) is int and server["port"] == 18080
            and server.get("proxy_protocol", False) is False)
    require(not any(server.get(k) for k in ("listen_unix_sock", "metrics_port", "metrics_listen"))
            and server.get("listen_tcp", True) is True, "extra listener requires review")
    require(server.get("api", {}).get("enabled") is False and not server.get("admin_api"),
            "enabled or aliased API needs review")
    conntrack = server.get("conntrack_control", {})
    require(conntrack.get("inline_conntrack_control") is True
            and conntrack.get("mode", "tracked") == "tracked"
            and conntrack.get("backend", "auto") == "auto", "conntrack policy needs review")
    listeners = server.get("listeners", [])
    require(len(listeners) == 1 and listeners[0].get("ip") == "127.0.0.1"
            and type(listeners[0].get("port")) is int
            and listeners[0].get("port") == 18080 and listeners[0].get("transport") == "web"
            and listeners[0].get("proxy_protocol", False) is False
            and listeners[0].get("web_client_ip_source") == "x_forwarded_for"
            and listeners[0].get("web_trusted_proxy_cidrs") == ["127.0.0.1/32"],
            "unsupported listener; manual review required")
    require(listeners[0].get("synlimit", False) is False, "listener firewall policy needs review")
    web = c.get("web", {})
    require(web.get("enabled") is True and web.get("carrier") == "https"
            and not web.get("carriers"), "unsupported WEB carrier")
    vhosts = web.get("vhosts", [])
    require(len(vhosts) == 1 and not vhosts[0].get("base_path"), "unsupported WEB scope")
    host = domain(vhosts[0]["host"])
    address, port = vhosts[0]["public_addr"].rsplit(":", 1)
    ipv4(address)
    public = ipaddress.ip_address(address)
    require(port == "443" and not public.is_unspecified and not public.is_loopback
            and not public.is_multicast, "unsupported public address")
    decoy = vhosts[0].get("decoy", {})
    if decoy.get('mode') == 'static_directory':
        require(decoy.get('directory') == str(Path(data)/'public')
                and decoy.get('index','index.html') == 'index.html', 'decoy contract changed')
    else:
        decoy_origin_port(decoy)
    profiles = vhosts[0].get("profiles", [])
    require(len(profiles) == 1 and profiles[0].get("user") == "web-user"
            and profiles[0].get("secret_mode") == "dd", "WEB profile binding changed")
    access = c.get("access", {})
    users = access.get("users", {})
    require(set(users) == {"web-user"} and isinstance(users["web-user"], str)
            and re.fullmatch(r"[a-fA-F0-9]{32}", users["web-user"]), "access binding changed")
    require(access.get("user_enabled", {}).get("web-user", True) is True)
    upstreams = c.get("upstreams", [])
    require(len(upstreams) == 1, "ambiguous upstream configuration")
    upstream = upstreams[0]
    kind = upstream.get("type")
    require(kind in ("direct", "socks5") and upstream.get("enabled", True) is True)
    require(not any(upstream.get(k) for k in
                    ("interface", "bind_addresses", "bindtodevice", "force_bind", "scopes",
                     "username", "password", "url", "user_id")), "upstream routing/auth needs review")
    require(upstream.get("ipv4", True) is True and upstream.get("ipv6", False) is False
            and type(upstream.get("prefer", 4)) is int and upstream.get("prefer", 4) == 4)
    socks = upstream.get("address", "")
    if kind == "socks5":
        socks_address(socks)
    else:
        require(not socks, "direct upstream has an unexpected address")
    return host, socks if kind == "socks5" else "direct", address


def config_info(path):
    c = read_config(path)
    data = c.get("general", {}).get("data_path", "/var/lib/telemt")
    require(isinstance(data, str) and Path(data).is_absolute())
    for value in managed_web_contract(c, data):
        print(value)


# The level is a record prefix, never a keyword in arbitrary message payload.
LOG_PREFIX = re.compile(
    r"^[ \t]*(?:\d{4}-\d\d-\d\dT[0-9:.]+(?:Z|[+-]\d\d:\d\d)\s+)?"
    r"(TRACE|DEBUG|INFO|WARN|ERROR|FATAL)(?:[ \t]+|$)")
PANIC_PREFIX = re.compile(
    r"^[ \t]*(?:panic(?:ked)?(?:[: \t]|$)|fatal runtime error:|"
    r"thread ['\"].+?['\"](?: \(\d+\))? panicked at\b)", re.I)


def classify_records(records):
    errors = warnings = 0
    for record in records:
        require(isinstance(record, str), "binary journal message requires review")
        record = re.sub(r"\x1b\[[0-9;]*m", "", record)
        require(not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", record),
                "unsafe log control sequence")
        started = False
        for line in record.splitlines():
            if not line.strip(): continue
            level = LOG_PREFIX.match(line)
            panic = PANIC_PREFIX.match(line)
            # Check every line, even inside a journal MESSAGE: an embedded
            # structured fatal record must not disappear as WARN continuation.
            if level:
                started = True
                if level[1] in ('ERROR', 'FATAL'): errors += 1
                elif level[1] == 'WARN': warnings += 1
            elif panic:
                started = True
                errors += 1
            elif line.startswith('MAESTRO: '):
                # Telemt's unlevelled startup banner (including private links).
                # Recognize its record framing, never inspect/print its payload.
                started = True
            else:
                require(started, "unrecognized log record prefix")
    print(f"logs: errors={errors}, warnings={warnings}")
    return 1 if errors else 0


def classify(text):
    return classify_records([text])


def journal_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate journal field")
        value[key] = item
    return value


def journal_constant(_value):
    raise ValueError("invalid JSON constant")


def classify_journal(text):
    records = []
    for line in text.splitlines():
        if not line.strip(): continue
        item = json.loads(line, object_pairs_hook=journal_object,
                          parse_constant=journal_constant)
        require(isinstance(item, dict) and isinstance(item.get('MESSAGE'), str),
                "missing/binary journal message")
        # Trusted journald metadata distinguishes PID 1's unit lifecycle
        # messages from Telemt stderr. Objective service checks cover its state.
        if item.get('_PID') == '1' and item.get('_COMM') == 'systemd': continue
        records.append(item['MESSAGE'])
    return classify_records(records)


# Independent certificate ownership survives removal of the deployment manifest.
def strict_json(path):
    safe_path(path)
    info = Path(path).lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
    require(info.st_size <= 64 * 1024 * 1024, 'JSON exceeds supported inventory bound')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as source:
        raw=source.read(64 * 1024 * 1024 + 1)
        require(len(raw)<=64 * 1024 * 1024 and UpdateTree.same(info)==UpdateTree.same(os.fstat(source.fileno())))
    return json.loads(raw, object_pairs_hook=journal_object,
                      parse_constant=journal_constant)


def certificate_record_value(host, cert_root, webroot, nginx_root):
    certificate_paths(cert_root, host)
    kind, params, mapping = renewal_info(cert_root, host)
    if kind == 'webroot':
        renewal_contract(cert_root, host, webroot)
        acme_state(nginx_root, host, webroot)
    else:
        require(not params.get('webroot_path') and not mapping)
    return dict(schema=1, domain=host, cert_name=host, renewal_kind=kind,
                acme_webroot=str(webroot) if kind == 'webroot' else '')


def certificate_record_check(state, host, cert_root, webroot, nginx_root):
    state = Path(state)
    safe_path(state)
    require(state.is_dir() and stat.S_IMODE(state.stat().st_mode) == 0o700)
    path = state / 'certificate.json'
    require(stat.S_IMODE(path.lstat().st_mode) == 0o600)
    value = strict_json(path)
    require(type(value.get('schema')) is int and value ==
            certificate_record_value(host, cert_root, webroot, nginx_root),
            'certificate ownership record mismatch')
    return value


def certificate_record_stage(output, host, cert_root, webroot, nginx_root):
    fresh_save(output, certificate_record_value(host, cert_root, webroot, nginx_root))


def certificate_only_state(state):
    state = Path(state)
    safe_path(state)
    require(state.is_dir() and stat.S_IMODE(state.stat().st_mode) == 0o700
            and {p.name for p in state.iterdir()} == {'certificate.json'})
    value = strict_json(state / 'certificate.json')
    require(type(value.get('schema')) is int and value['schema'] == 1
            and set(value) == {'schema', 'domain', 'cert_name', 'renewal_kind', 'acme_webroot'}
            and value['domain'] == value['cert_name'] and value['renewal_kind'] in ('webroot', 'standalone')
            and stat.S_IMODE((state / 'certificate.json').stat().st_mode) == 0o600)
    domain(value['domain'])


def no_managed_mounts(paths):
    mounts = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        mounts.append(Path(re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), line.split()[4])))
    for root in map(Path, paths):
        require(not any(m == root or m.is_relative_to(root) for m in mounts), 'managed mount requires review')


def uninstall_account_files(account, roots):
    # Inspect every non-virtual mounted filesystem without following links.
    # An unexpected account-owned object outside the managed roots is not ours.
    virtual = {'proc', 'sysfs', 'devtmpfs', 'devpts', 'tmpfs', 'cgroup', 'cgroup2',
               'securityfs', 'debugfs', 'tracefs', 'pstore', 'mqueue', 'hugetlbfs', 'fusectl', 'configfs'}
    mounts = {'/'}
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        before, after = line.split(' - ', 1)
        mount = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), before.split()[4])
        if after.split()[0] not in virtual and Path(mount).is_dir(): mounts.add(mount)
    # /run and /tmp may also contain unexpected UID-owned objects.
    mounts.update(p for p in ('/run', '/tmp') if Path(p).is_dir())
    uid, gid = account['user'][2:4]
    for mount in sorted(mounts):
        # Never walk an active managed runtime tree just to inspect outsiders.
        prune = []
        for path in ['/proc', '/sys', '/dev', *map(str, roots)]:
            if prune: prune.append('-o')
            prune += ['-path', path]
        result = subprocess.run(['find', mount, '-xdev', '(', *prune, ')', '-prune', '-o', '(', '-uid', uid,
                                 '-o', '-gid', gid, ')', '-print0'], capture_output=True)
        require(result.returncode == 0, 'account file ownership scan failed')
        for raw in result.stdout.split(b'\0'):
            if not raw: continue
            path = Path(os.fsdecode(raw))
            require(any(path == Path(root) or path.is_relative_to(root) for root in roots),
                    'account owns unrelated files')


def uninstall_safe_path(path, account):
    for item in (Path(path), *Path(path).parents):
        info = item.lstat()
        require(not stat.S_ISLNK(info.st_mode) and info.st_uid in (0, os.geteuid(), int(account['user'][2]))
                and (not info.st_mode & 0o022 or (stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and info.st_mode & stat.S_ISVTX)))


def uninstall_objects(paths, account, recursive=True):
    no_managed_mounts(paths)
    records = []; total=0; path_bytes=0
    uid, gid = map(int, account['user'][2:4])
    def visit(path, device=None, depth=0):
        nonlocal total,path_bytes
        path = Path(path)
        path_bytes+=len(str(path).encode())
        require(depth<=UpdateTree.MAX_DEPTH and len(records)<UpdateTree.MAX_ENTRIES
                and path_bytes<=UpdateTree.MAX_PATH_BYTES, 'managed inventory exceeds supported bound')
        uninstall_safe_path(path.parent, account)
        info = path.lstat()
        require(not os.listxattr(path, follow_symlinks=False), 'extended attributes require manual review')
        require(info.st_uid in (0, os.geteuid(), uid) and info.st_gid in (0, os.getegid(), gid)
                and not info.st_mode & 0o022 and (device is None or info.st_dev == device))
        require(stat.S_ISDIR(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1),
                'unsupported managed object, symlink or hardlink')
        record = dict(path=str(path), dev=info.st_dev, ino=info.st_ino, uid=info.st_uid,
                      gid=info.st_gid, mode=stat.S_IMODE(info.st_mode), directory=stat.S_ISDIR(info.st_mode))
        if record['directory']:
            records.append(record)
            if recursive:
                for child in sorted(path.iterdir()): visit(child, info.st_dev, depth+1)
        else:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, 'rb') as source:
                actual = os.fstat(source.fileno())
                require(stat.S_ISREG(actual.st_mode) and actual.st_nlink == 1
                        and (actual.st_dev, actual.st_ino, actual.st_uid, actual.st_gid, actual.st_mode)
                        == (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode))
                total+=actual.st_size; require(total<=UpdateTree.MAX_BYTES)
                digest=hashlib.sha256(); count=0
                while block:=source.read(1024 * 1024):
                    count+=len(block); require(count<=actual.st_size); digest.update(block)
                require(count==actual.st_size); record['sha256']=digest.hexdigest()
                after = os.fstat(source.fileno())
                require((after.st_dev, after.st_ino, after.st_mode, after.st_nlink, after.st_uid, after.st_gid,
                         after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                        == (actual.st_dev, actual.st_ino, actual.st_mode, actual.st_nlink, actual.st_uid, actual.st_gid,
                            actual.st_size, actual.st_mtime_ns, actual.st_ctime_ns),
                        'file changed during snapshot')
            records.append(record)
    for path in paths: visit(path)
    return records


def uninstall_static_objects(paths, account):
    """Controls plus stable DATA anchors, without enumerating runtime children."""
    data = Path(paths[3])
    records = uninstall_objects([p for p in paths if p != str(data)] + uninstall_update_paths(paths), account)
    anchor_paths = [str(data),str(data/'public')]
    if len(paths) == 5: anchor_paths.append(str(data/'public/index.html'))
    anchors = uninstall_objects(anchor_paths,
                                account, recursive=False)
    for record, directory, mode in zip(anchors, (True, True, False), (0o750, 0o750, 0o440)):
        require(record['directory'] == directory and record['uid'] in (0, os.geteuid())
                and record['gid'] == int(account['user'][3]) and record['mode'] == mode,
                'managed DATA anchor changed')
    marker=data/'.telemt-web-manager-generation.json'
    if marker.exists(): anchors += uninstall_objects([str(marker)],account,recursive=False)
    return records + anchors


def uninstall_plan(output, binary, config, unit, data, state, nginx_root, cert_root, webroot, site_root=None):
    paths = [binary, str(Path(config).parent), unit, data, state]
    require(len(set(paths)) == 5 and all(Path(p).is_absolute() and '..' not in Path(p).parts for p in paths))
    require(not any(Path(a).is_relative_to(b) for a in paths for b in paths if a != b))
    for path in paths: safe_path(path)
    manifest = strict_json(Path(state) / 'manifest.json')
    require(type(manifest.get('schema')) is int and manifest['schema'] == 1
            and set(manifest) == {'schema', 'domain', 'public_ip', 'unit_sha256', 'nginx_sha256', 'acme_webroot'})
    host = domain(manifest['domain'])
    require(all(re.fullmatch('[0-9a-f]{64}', manifest[key]) for key in ('unit_sha256','nginx_sha256')))
    vhost = Path(nginx_root) / 'conf.d/telemt-web-manager.conf'
    for path, key in ((unit, 'unit_sha256'), (vhost, 'nginx_sha256')):
        safe_path(path)
        require(hashlib.sha256(Path(path).read_bytes()).hexdigest() == manifest[key])
    for path in (binary, config, unit, Path(state,'manifest.json'), Path(state,'web-link.txt')):
        require(Path(path).lstat().st_uid in (0, os.geteuid()), 'managed control-file owner changed')
    require(stat.S_IMODE(Path(config).stat().st_mode) == 0o640)
    c = read_config(config)
    require(managed_web_contract(c, data)[0] == host)
    if site_bound_identity(config,data,nginx_root,site_root or SITE_ROOT):
        site_root = str(Path(site_root or SITE_ROOT))
        require(all(not Path(site_root).is_relative_to(p) and not Path(p).is_relative_to(site_root)
                    for p in paths), 'site root overlaps managed objects')
        paths.append(site_root)
    require(c['general']['data_path'] == data)
    require(managed_web_contract(c, data)[2] == manifest['public_ip'])
    account = fresh_identity(data)
    groups = subprocess.run(['getent','group'],capture_output=True,text=True)
    require(groups.returncode == 0)
    entries = [line.split(':') for line in groups.stdout.splitlines()]
    require(all(len(entry) == 4 and 'telemt' not in entry[3].split(',') for entry in entries),
            'supplementary group membership requires review')
    value = certificate_record_value(host, cert_root, webroot, nginx_root)
    require(manifest['acme_webroot'] == value['acme_webroot'])
    if os.path.lexists(Path(state) / 'certificate.json'):
        certificate_record_check(state, host, cert_root, webroot, nginx_root)
    extra=uninstall_update_paths(paths)
    allowed={'manifest.json','web-link.txt','certificate.json'}
    if extra: allowed |= {'telemt-release.json','telemt-generation.json','update-journal.json'}
    require({p.name for p in Path(state).iterdir()} <= allowed
            and {p.name for p in Path(config).parent.iterdir()} == {Path(config).name})
    require(Path(state,'web-link.txt').read_text() ==
            f"tg://webproxy?server={host}&secret=dd{c['access']['users']['web-user']}\n")
    require(stat.S_IMODE(Path(state).stat().st_mode) == 0o700
            and stat.S_IMODE(Path(state,'web-link.txt').stat().st_mode) == 0o600)
    uninstall_account_files(account, [Path(config).parent, data])
    fresh_save(output, dict(schema=1, phase='pre-stop', roots=paths, account=account, certificate=value,
                            objects=uninstall_static_objects(paths, account)))


def uninstall_backup(plan, backup, directory="objects"):
    value = strict_json(plan)
    backup = Path(backup)
    safe_path(backup)
    require(directory in ('objects','objects-stopped'))
    require(value['phase'] == ('pre-stop' if directory == 'objects' else 'stopped'))
    if directory == 'objects':
        require(fresh_identity(value['roots'][3]) == value['account'])
        require(uninstall_static_objects(value['roots'], value['account']) == value['objects'],
                'static identity changed before stop')
    objects = backup / directory
    value['object_directory'] = directory
    objects.mkdir(mode=0o700)
    for index, record in enumerate(value['objects']):
        if record['directory']: continue
        fd = os.open(record['path'], os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and info.st_uid == record['uid'] and info.st_gid == record['gid']
                    and stat.S_IMODE(info.st_mode) == record['mode']
                    and (info.st_dev,info.st_ino) == (record['dev'],record['ino']))
            destination = objects / str(index)
            digest=hashlib.sha256(); count=0
            with destination.open('xb') as target:
                os.fchmod(target.fileno(), 0o600)
                while block:=source.read(1024 * 1024):
                    count+=len(block); require(count<=info.st_size<=UpdateTree.MAX_BYTES)
                    digest.update(block); target.write(block)
                require(count==info.st_size and digest.hexdigest()==record['sha256'])
                target.flush(); os.fsync(target.fileno())
            after = os.fstat(source.fileno())
            require((after.st_dev, after.st_ino, after.st_mode, after.st_nlink, after.st_uid, after.st_gid,
                     after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    == (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid, info.st_gid,
                        info.st_size, info.st_mtime_ns, info.st_ctime_ns), 'file changed during backup')
        require((info.st_dev,info.st_ino) == (record['dev'],record['ino'])
                and digest.hexdigest() == record['sha256'])
    fresh_save(backup / 'uninstall.json', value)
    if directory == 'objects': fresh_save(backup / 'initial-uninstall.json', value)
    # Publish the ledger only with durable canonical backup files/context.
    for path in [*backup.rglob('*'), backup]:
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | (os.O_DIRECTORY if path.is_dir() else 0))
        try: os.fsync(fd)
        finally: os.close(fd)


def uninstall_refresh(backup):
    value = strict_json(Path(backup) / 'uninstall.json')
    require(value['phase'] == 'pre-stop')
    uninstall_quiet(backup)
    actual = uninstall_objects(value['roots'] + uninstall_update_paths(value['roots']), value['account'])
    by_path = {r['path']: r for r in actual}
    data, state = map(Path, value['roots'][3:5])
    for record in value['objects']:
        require(by_path.get(record['path']) == record, 'managed identity changed before removal')
    require(set(by_path) - {r['path'] for r in value['objects']} <=
            {str(state / 'certificate.json')} | {r['path'] for r in actual if Path(r['path']).is_relative_to(data)})
    if os.path.lexists(state / 'certificate.json'):
        require(strict_json(state / 'certificate.json') == value['certificate'])
    runtime = data / 'state'
    require(runtime.is_dir() and runtime.stat().st_uid == int(value['account']['user'][2])
            and runtime.stat().st_gid == int(value['account']['user'][3]))
    value['objects'] = actual
    value['phase'] = 'stopped'
    plan = Path(backup) / 'stopped-plan.json'
    fresh_save(plan, value)
    uninstall_backup(plan, backup, 'objects-stopped')


def uninstall_quiet(backup):
    value = strict_json(Path(backup) / 'uninstall.json')
    fresh_account_quiet(dict(pending_account=False, account=value['account'], roots=['',value['roots'][3], '']))
    uninstall_account_files(value['account'], [Path(value['roots'][1]), value['roots'][3]])


def uninstall_remove(backup):
    value = strict_json(Path(backup) / 'uninstall.json')
    require(value['phase'] == 'stopped' and value['object_directory'] == 'objects-stopped',
            'complete stopped backup required before removal')
    uninstall_quiet(backup)
    binary, config, unit, data, state = value['roots'][:5]
    # After quiescence every object must still match the authoritative backup.
    extra=uninstall_update_paths(value['roots'])
    require(uninstall_objects(value['roots'] + extra, value['account']) == value['objects'])
    remove = {r['path']: r for r in value['objects'] if r['path'] == binary or r['path'] == unit
              or Path(r['path']).is_relative_to(config) or Path(r['path']).is_relative_to(data)
              or r['path'] in (str(Path(state,'manifest.json')),str(Path(state,'web-link.txt')),
                              str(Path(state,'telemt-release.json')),str(Path(state,'telemt-generation.json')),
                              str(Path(state,'update-journal.json')))
              or any(Path(r['path']).is_relative_to(p) for p in extra + value['roots'][5:])}
    value['removal_started'] = True
    fresh_save(Path(backup) / 'uninstall.json', value)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    for record in reversed(list(remove.values())):
        path = Path(record['path'])
        parent = os.open(path.parent, flags)
        try:
            info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            require((info.st_dev, info.st_ino) == (record['dev'],record['ino']))
            if record['directory']: os.rmdir(path.name, dir_fd=parent)
            else: os.unlink(path.name, dir_fd=parent)
        finally: os.close(parent)


def uninstall_account_remove(backup):
    value = strict_json(Path(backup) / 'uninstall.json')
    binary, config, unit, data, state = value['roots'][:5]
    require(all(not os.path.lexists(p) for p in (binary,config,unit,data,Path(state,'manifest.json'),Path(state,'web-link.txt'))))
    require(all(not os.path.lexists(p) for p in value['roots'][5:]))
    uninstall_quiet(backup)
    account = value['account']
    with fresh_signal_window():
        subprocess.run(['userdel','telemt'], check=True)
        require(fresh_getent('passwd','telemt') is None)
        group = fresh_getent('group','telemt')
        if group is not None:
            require(group == account['group'])
            subprocess.run(['groupdel','telemt'], check=True)
        require(fresh_getent('group','telemt') is None)


def uninstall_uid_quiet(account):
    uid = int(account['user'][2])
    for process in Path('/proc').iterdir():
        if not process.name.isdigit(): continue
        try: text = (process / 'status').read_text()
        except (FileNotFoundError, ProcessLookupError): continue
        match = re.search(r'^Uid:\s+([0-9 \t]+)$', text, re.M)
        require(match is not None and uid not in map(int,match[1].split()), 'UID process prevents rollback')


def uninstall_restore(backup):
    value = strict_json(Path(backup) / 'uninstall.json')
    account = value['account']; user, group = account['user'], account['group']
    if not value.get('removal_started'):
        require(fresh_identity(user[5]) == account)
        return  # No deployment file was changed; never overwrite live runtime data.
    uninstall_uid_quiet(account)
    # Recreate only the exact free identity, never overwrite or modify an account.
    with fresh_signal_window():
        actual_group = fresh_getent('group','telemt')
        actual_user = fresh_getent('passwd','telemt')
        require(actual_group in (None,group) and actual_user in (None,user))
        if actual_group is None:
            require(fresh_getent('group',group[2]) is None)
            subprocess.run(['groupadd','--system','--gid',group[2],'telemt'],check=True)
        if actual_user is None:
            require(fresh_getent('passwd',user[2]) is None
                    and not any(p[3] == group[2] for p in fresh_passwd()))
            subprocess.run(['useradd','--system','--uid',user[2],'--gid',group[2],
                            '--home-dir',user[5],'--no-create-home','--shell',user[6],
                            '--comment',user[4],'telemt'],check=True)
        require(fresh_identity(user[5]) == account)
    no_managed_mounts(value['roots'])
    for index, record in enumerate(value['objects']):
        path = Path(record['path'])
        uninstall_safe_path(path.parent, account)
        if os.path.lexists(path):
            info = path.lstat()
            require((info.st_dev,info.st_ino) == (record['dev'],record['ino'])
                    and info.st_uid == record['uid'] and info.st_gid == record['gid']
                    and stat.S_IMODE(info.st_mode) == record['mode']
                    and (record['directory'] or info.st_nlink == 1), 'rollback destination changed')
        if record['directory']:
            if not path.exists(): path.mkdir(mode=record['mode'])
        else:
            source = Path(backup,value['object_directory'],str(index))
            require(update_hash(source,UpdateTree.MAX_BYTES)['sha256'] == record['sha256'])
            # A missing target is created exclusively; a surviving original is
            # verified and copied through a no-follow descriptor.
            existed = path.exists()
            flags = os.O_WRONLY | os.O_NOFOLLOW | (0 if existed else os.O_CREAT | os.O_EXCL)
            fd = os.open(path, flags, record['mode'])
            with os.fdopen(fd,'wb') as output:
                actual = os.fstat(output.fileno())
                require(stat.S_ISREG(actual.st_mode) and actual.st_nlink == 1
                        and (not existed or (actual.st_dev,actual.st_ino) == (record['dev'],record['ino'])))
                output.truncate(0)
                source_fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
                with os.fdopen(source_fd,'rb') as input_file:
                    digest=hashlib.sha256(); count=0
                    while block:=input_file.read(1024 * 1024):
                        count+=len(block); require(count<=UpdateTree.MAX_BYTES)
                        digest.update(block); output.write(block)
                    require(digest.hexdigest()==record['sha256'])
                output.flush(); os.fsync(output.fileno())
        os.chown(path,record['uid'],record['gid'],follow_symlinks=False)
        path.chmod(record['mode'])


def planned_unlink(plan, path):
    value = strict_json(plan)
    require(any(e['path'] == path and e['content'] is None for e in value['edits']))
    safe_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as source:
        info = os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and hashlib.sha256(source.read()).hexdigest() == value['snapshot'][path])
        require(Path(path).lstat().st_ino == info.st_ino)
        os.unlink(path)


def certificate_cleanup_plan(output, state, host, cert_root, webroot, nginx_root, hook):
    value = certificate_record_check(state, host, cert_root, webroot, nginx_root)
    require(hook == str(Path(cert_root) / 'renewal-hooks/deploy/telemt-web-manager'))
    # Certbot delete follows these explicit lineage paths. No defaults/foreign
    # targets are permitted for a destructive command.
    text = (Path(cert_root) / 'renewal' / (host + '.conf')).read_text()
    top = text.split('[renewalparams]')[0]
    for key in ('cert','privkey','chain','fullchain'):
        expected = str(Path(cert_root,'live',host,key+'.pem'))
        require(re.search(r'^' + key + r'\s*=\s*' + re.escape(expected) + r'\s*$', top, re.M))
        target = Path(expected); actual = target.resolve(strict=True)
        require(actual.is_relative_to(Path(cert_root,'archive',host)))
        safe_path(actual)
    require(re.search(r'^archive_dir\s*=\s*' + re.escape(str(Path(cert_root,'archive',host))) + r'\s*$', top, re.M))
    nginx_plan(nginx_root, host, output, webroot)
    plan = strict_json(output)
    # Core WEB integration has already gone. Reinstallation would create either
    # the legacy pair or the two include files plus HTTPS vhost; do not infer
    # absence from a format-dependent edit count.
    expected = {Path(nginx_root) / 'conf.d/telemt-web-manager.conf',
                *(path for path, _ in nginx_stream_files(Nginx(nginx_root), host))}
    require(all(not os.path.lexists(path) for path in expected)
            and any(Path(edit['path']) == Path(nginx_root) / 'conf.d/telemt-web-manager.conf'
                    and edit['old'] is None for edit in plan['edits']),
            'core WEB integration still present')
    paths = []
    if value['renewal_kind'] == 'webroot':
        root = Path(webroot)
        require({p.name for p in root.iterdir()} == {'.telemt-web-manager','.well-known'}
                and {p.name for p in (root / '.well-known').iterdir()} == {'acme-challenge'}
                and not list((root / '.well-known/acme-challenge').iterdir()),
                'ACME state is in use or changed')
        paths += [webroot, str(Path(nginx_root,'conf.d/telemt-web-manager-acme.conf'))]
    # This manager supports one owned lineage. Refuse explicit sharing of its
    # lineage, webroot or hook by another renewal or Nginx configuration.
    for path in Path(cert_root,'renewal').iterdir():
        if path.name == host+'.conf': continue
        safe_path(path)
        text = path.read_text()
        require(not any(token in text for token in (str(Path(cert_root,'live',host)), hook, str(webroot))))
    parser = Nginx(nginx_root)
    parser.read(Path(nginx_root,'nginx.conf'))
    for text in parser.sources.values():
        require(str(Path(cert_root,'live',host)) not in text
                and f'/etc/letsencrypt/live/{host}/' not in text, 'lineage shared by another vhost')
    paths.append(hook)
    account = dict(user=['','','0','0'])
    records = uninstall_objects(paths + [str(Path(state,'certificate.json'))], account)
    fresh_save(output, dict(schema=1, objects=records, state=state, nginx_snapshot=plan['snapshot']))


def certificate_cleanup_remove(plan):
    value = strict_json(plan)
    require(uninstall_objects([r['path'] for r in value['objects']
                              if not any(Path(r['path']).is_relative_to(other['path'])
                                         for other in value['objects'] if other != r and other['directory'])],
                             dict(user=['','','0','0'])) == value['objects'])
    for path, digest in value['nginx_snapshot'].items():
        require(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest)
    for record in reversed(value['objects']):
        path = Path(record['path'])
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.stat(path.name,dir_fd=fd,follow_symlinks=False)
            require((info.st_dev, info.st_ino) == (record['dev'],record['ino']))
            if record['directory']: os.rmdir(path.name,dir_fd=fd)
            else: os.unlink(path.name,dir_fd=fd)
        finally: os.close(fd)
    # Empty state directory only; never recursively remove manager state.
    os.rmdir(value['state'])


def web_link_value(manifest_raw, config_raw, link_raw):
    """Validate secret identity in memory; never include input in diagnostics."""
    manifest = json.loads(manifest_raw, object_pairs_hook=journal_object,
                          parse_constant=journal_constant)
    require(type(manifest) is dict and type(manifest.get('schema')) is int
            and manifest['schema'] == 1)
    host = domain(manifest['domain'])
    for name in ('unit_sha256', 'nginx_sha256'):
        require(isinstance(manifest.get(name), str)
                and re.fullmatch(r'[0-9a-f]{64}', manifest[name]))
    require(not re.search(rb'(?m)^\s*include\s*=', config_raw))
    config = tomllib.loads(config_raw.decode('utf-8'))
    require(not any(k in config for k in ('include', 'includes')))
    web = config['web']
    require(web.get('enabled') is True and len(web['vhosts']) == 1)
    vhost = web['vhosts'][0]
    require(vhost['host'] == host and len(vhost['profiles']) == 1)
    profile = vhost['profiles'][0]
    require(profile['user'] == 'web-user' and profile['secret_mode'] == 'dd')
    users = config['access']['users']
    require(set(users) == {'web-user'} and isinstance(users['web-user'], str)
            and re.fullmatch(r'[0-9a-f]{32}', users['web-user']))
    require(config['access'].get('user_enabled', {}).get('web-user', True) is True)
    # Canonical manager-written bytes: one ASCII line, one terminal LF, no extras.
    expected = f'tg://webproxy?server={host}&secret=dd{users["web-user"]}\n'.encode('ascii')
    require(link_raw == expected)
    return expected[:-1].decode('ascii')


def web_link_read(path, modes, limit, owner=0):
    safe_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == owner
                and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) in modes
                and before.st_size <= limit)
        raw = bytearray()
        while block := os.read(fd, min(65536, limit + 1 - len(raw))):
            raw.extend(block)
            require(len(raw) <= limit)
        after = os.fstat(fd)
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                                 info.st_ctime_ns, info.st_uid, info.st_gid, info.st_mode, info.st_nlink)
        require(identity(before) == identity(after) == identity(os.lstat(path)))
        return bytes(raw)
    finally:
        os.close(fd)


def current_web_link(state, config):
    require(os.geteuid() == 0)
    state = Path(state)
    require(all(32 <= ord(c) < 127 for c in str(state)))
    safe_path(state)
    info = state.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o700)
    return web_link_value(web_link_read(state / 'manifest.json', {0o600}, 16384),
                          web_link_read(config, {0o600, 0o640}, 1024 * 1024),
                          web_link_read(state / 'web-link.txt', {0o600}, 512))


def presentation_language():
    """Ephemeral context supplied only to human-facing manager commands."""
    return ('ru' if os.environ.get('TWM_UI_LANGUAGE') == 'ru'
            and sys.stdin.isatty() and sys.stdout.isatty() else 'en')


def presentation_color(stream):
    return (stream.isatty() and os.environ.get('TERM','') not in ('','dumb','unknown')
            and 'NO_COLOR' not in os.environ)


def display_web_link(state, config):
    # Keep validation-only CLI silent; only this explicit terminal path prints.
    require(sys.stdin.isatty() and sys.stdout.isatty() and sys.stderr.isatty())
    link = current_web_link(state, config)
    color = presentation_color(sys.stdout)
    header, cyan, warning, reset = ('\033[1;36m', '\033[96m', '\033[33m', '\033[0m') if color else ('',) * 4
    russian = presentation_language() == 'ru'
    rule = '=' * 60
    print(f'{header}{rule}\n                  TELEGRAM WEB PROXY MANAGER\n{rule}{reset}\n')
    print('ТЕКУЩАЯ ССЫЛКА ПОДКЛЮЧЕНИЯ:\n' if russian else 'CURRENT CONNECTION LINK:\n')
    print(f'{cyan}{link}{reset}\n')
    notice = ('ВНИМАНИЕ: ссылка содержит секрет доступа.\nХраните её в безопасном месте и не передавайте посторонним.' if russian
              else 'WARNING: This link contains a bearer secret.\nStore it securely and do not share it.')
    print(f'{warning}{notice}{reset}\n')
    saved = 'Сохранена локально:' if russian else 'Saved locally:'
    print(f'{saved}\n  {Path(state) / "web-link.txt"}\n\n{rule}')


# Approved v0.3 generator/templates are embedded so bootstrap still ships one
# immutable Bash/Python pair. This payload contains no examples or previews.
SITE_ARCHIVE_SHA256 = 'aad702e7f8a5a5caf1095d69304d9705e568717ea8ad8c0f502a44fb9eefbab5'
SITE_SOURCE_SHA256 = 'f4fba7a138b2986f1516271a356c0ccd085f719deab65b8189a65b9d8b3f48a6'
SITE_SOURCE_B85 = (
    'c-ri}TW=#tvL^Uf;#8qVQWeGIRkuv#j51SsIi-}cC1uytsVXFbWKfJ2$zVqWrDSUpI8XDun3ur-voHIwgMC|If&Bry|D=D(+Gl3&'
    ';T{o`l+}IC9$>aFRU#STS9805W`6h0RWy&%Fprvx)i(#<eESbimRb5_5YL}P^P6C?$|uRZ`|JGIZ}8u<G`@=G;WWtdFpr19Fu94+'
    '?JUltU>MFv@rc^Vf^m`tmp^@Y-=xPz(|8ah^XckoFi(Pcl;0-lbr24RQI<8S+4&poKBK21v^$v6ztG|$N`rWQlMJb=WZnpF<9re<'
    '=kcGHQ4kN4c@|KYL737&=#_awZ8U?+Nt^}rzc3g@S$s7Q7HN_v`DzjI)2C;b^zUEi@tk^^PNTFDTt?GqmIsS4A5I#<EWS#$Kbl22'
    '&*N=sftKScxLSrOeGx@XvmDgUY>}in4dQAMrdedanB=pm{qUzOncEL(@lX~G(<sl1&y!^y(`(~2nPEH=teyV$fj(ln-X5PH2Z#J|'
    '^V6qsJdHkm+G?gzmP~J=&8;R4Bbw)U^3~Dh5j}bL>pY<UYz&e-oX5j(x^ZB>lkaIxql~`%W#e^}&Vzp!{1nee$?ZlX*tncT!ATU3'
    'gY)Pr&hjY5mw#BsQ69Vu=gDG)&u`Kwng{P`3F7%iqiEUr&&DZDVd6A=66ZPX*-P5QD7^{uB;}^wCs{@Vc%P)SL04u3AEvbG!O?UU'
    '&corl9^OpDESn_DjGhm#q6{xzB;!25r10U75hfZ2r=Syjah@bOb#@Y8P4acEzD#DbWX@}VSKgxi1rO&RlVwT=fxC%9+Tdsu@JisD'
    'Bb{pSCQL{4)o)Jo8^dIpq`csp8{f9~x`S?Kqp|VrxI6AdA^wV5(cWkmf9(zWJKbnwt3gk8c6&Yg8&B?yd(jAgjdr7*(U70q@ArBw'
    'da`yN^m@15>vsnHdVk!G_PC>6>Zrx9cl$#c26xmR_I7%GezHx^^6#U)Xea9NlRN!>uXA5V-QG^ejI%G}jE2!j#<}0=@Ab5!&VFyu'
    '<K}7RQMAJy4Wr%Bj?TT;+uztKtsT)Et(@Qa=ElX04s(#k`7)eljo=C!LEIxvl3CW29a*H|FbDky<2ag*f<MUyGP9Z{$u&-RI3^ko'
    'a-uoj<c$6d^I#TU6Z7E4f^ig0gK2z2yB*KDW#TCBULFTOy*;`NUcNm#eRF(KS)ENfBt#9&z|i^>G#9LrWiSbEB5vm8Gzy6s&4`wk'
    'DYYJsZsK7?JTZuf#jZx-O2$NdHjTgwL0?%+vyMI!ql{+}#tRmgF*(xACgC8?W%`$IkAves9-sgG>gea-&C&U*<I|c!9tGg4@hHLo'
    's5k1LS0|!DN;?<Cjp*Da139*_VZv!NjhS($39+!b$^eX!{v~TE{F{Cz7E4<}&yM5I+U)t++56z~EO>K%_EXKc_{av#6|s87+;wZ|'
    'L`|b1MiV6CfR5;RIh9_wv05S;sDGl5oLCixhIW#4M6xVhVb-HqCPVLs^Wv9DGK;j6KYV<5e0h8x{P^zlRdDv2#(G@4h;Nc)L<E@J'
    'f}lvqq_i!(@idBfNMAOE0TKn!kVx>+u4hR+<#oicGN$El^rvN(%dRpNPNL}|m{<ms(LOT|RWig5^N=9oj$fRe{a89W3+9T<b!h#f'
    '&rOIZI%sccihLfKD9yLR74bC>5yRGBe$vnUqYTCT#Ed%QANY)Ii%iyEU-Pl!uZp34(SL8u(cyM>y;?7xj&CA}h2TB)KZ--*v>T^<'
    'kdAU<{`3jLLZs7KN~BNU9PxpEwal*R!`Xs1|KfU8h!T}c7qm-8F4W6`7gN$Xi2J7j&tgFQ0u7=U5+QGsH2zCs$1}$Mo$(QY#N0sh'
    '(>OPBY2zg+99bUI2}PgMR(-da&`)$8gHsVw8?QoAo-l>;C>%-S*Q;9+GKD-MAxi2Nok3lYvw;<{I>+_WXgCV@cbOx%!gjyY#b51S'
    'XQ#W5zrwv?d(;=+9qtVFMIf|>^dyUu_FiYN$KUNoqwc78kC2F3gWWwA2<>)zr^5oU)9(zs{N124+%X;PkB0k0?!L9(9&}hPwRgLn'
    'Zm2`r8IJDhXt+O65k?(#J1ki``<-5|%^mFxcA~Cy6zvU0dpwYKtG%y78g#o|p4(tBYK;bultw4CrNMI11Yr?(S*9@^Tf?iu>5Pwh'
    'A&;(>*y23l)6eH1pmWd=hBuDWEN8x)N7JdYTzz&p3FlXQB52FG{nzh~PhK$xxCmaK6H`5U4W9Mt=={f8et!#QACO8;Co>$7G9Tzb'
    'N#h}1a0QCLr8$Je*Ofil0SZ?mH8mzCRTT-Dh>GaX%Xk4cCi6cH&R$#`pOYy1>p%b3i{Rzi`wvH_@6PHNDTo){q!9=l8a?UD#Hm?Y'
    'Hw(qfte|uYh7a~XPmCoJ&R4K3bQ>^Dl0mm%so`Ql)67)tXG>B>WtbmNU(u?8rCuDpr+@tTbItf(6C0Hk8c-{=4W^+Hu^XA~93n6x'
    'wll&KiQZv%8?u3<(sW6ZCRj|uOlN>aCaD2YWb_i9)O2N8{pq_mZ!b@N4rIgMe0=xnxK42LUQyGuc(ZVUCP^a*l3SscBeud~$n7x8'
    '(`25^R?fmL=aXfc#-s~G!g({A={zFKgPI#cU%~zuC5R~Q?3CB+?eWnck54ZiDSyt0N#4ZKEuX?XnY&Wx4T(4_MxzlwG6Sva?;sJ-'
    'KL6mK5%UQ1b|O;Rn7N3if+F>iWAjCgSh|kMDkKeltx&=cj*W(P2^|PxhfKz~ktiD%;S^FrsMQlwKWghFI!SU8gFcCJwz7!P$J13n'
    '>edV&>!riRasd;WTBc>=ZUfPSNe<_R{X@Kyoka|(kPs{uAPl8fRsu+8%Y%1w(ws*)&ub+it2bn1gBo56d1{L~88wzRcr9pfmy^{@'
    '2PYgsh7CC=#?^T=j2F>8QfY709duX(jK|~sv9TC-#YQ6W6!mvhSnT$OYE6yDdl3thF>!b?a(dCupx?hoSnTe0hg}w6<KcKW5+kM+'
    '^+#+s^#=5Ms2#QYd!3Q(NQ|6)vZh!*^>=o{-rhYOh3#J0>)IKKvDKw<j`{WWPT1d*j!2*mx?;AC$ewEHkhG)Tn1=LN8|jG54%QfF'
    'NgAmc!L|jA4pF6r3>sjJX%don!4?jc2^EaNs>g9bFU-0I%WP$tg|v7^{PQJgqwh}NG}!wBmVff@<<aHws~V2=9=29SG@DP@<pOGB'
    'IjG`<zc#Xz<if0^{98jLkA@R=6%mWI77=mYP)2Hvs+6fObGR7GP4KbHqZcQ~wPI7b0t6>9!(lSRSYay=Ul##lS*Ny-LCl5KF65{e'
    'V=0vW?3#=k*XlHDPmjh?%1ysHJ9`zprhi~LgV!G~F4h?#*jBJ?QV~Q}52%%4R+yV+a6Ae%o6OY2cqCJr*ge~W#%eNhl&3p1qWCEI'
    'aDMcXEa9UQ9$fH`XCKc`k4|dFX1S$9J<Z?+bH0EGiwt)iBe)h1oTarfmm4rhNjZT~*FoFOmc5<-DOvGY(<oa`b1O8N7<E^_&Nebs'
    'qTdV45^*BiX-y#Es4UAY1zK@szu^ajEDK2`AAKS81)jX4b6VJwV|C_LJ$bI_cCab7oA^Md)_F>&7oWpH#1lLF3HJ8+@zJZ`D1iCB'
    '(Xb3-lZ9qpxGQeeZ&$R;+QJn?#&DWsR(ZXG6HcjVNd&zLU<+jd3E1H^eF}#uJbb)0NixH(gE$8(YaG*76SWZ;(2D0!$!N$VYKd0('
    't(kZR#qkSeYtEW)L1de-PlxJdVZVj7OXXNmyHR|D5hsQpiZ>=1!#6+^i}?M7t*TJxPL}#4hF^L)8u8&svk5DV#E#hY9gM;m5s~&u'
    ')_b@hg@x6;30Z2*;3af*I{Zndo`$P59Pt|Y!~dAU*QDHz21~paMt2H_I1Oa(Y>2KBI3KSEnD*y*MzSA%f|Q*Z#X@2T(eOH$N4M;r'
    'fELH<Y8Z^^tJ^5L2D2DLI1ulVRZejD9bZHf)ER7?%?-yYoKFX|IX4))xT!+3x=bLcp%5Lp_>3?)8tN@8r8F+klP=(h81yt*n6)W+'
    'Ar3ah4S_fU3!^L3{vyeR)|pj>Q&PRdl(ml+$CogLej>qhPQr+Y{^RAl(_@eBU&FgcCxnK?OnI4(!y#)@$x?}mI$)J_7Jn}0SiF)a'
    '3!>N+@oG9(BVzN~Mi5THuSN;YjfY2yDswcVcV1&X6M66#JU5RbB6^;5g}V9SgbcE)$&{?b9Nc=8hH$=byc-wZOScgkaf9{;K72h$'
    'G<*nZ97@p66cdO(!ydp=@-CS9HiP5YB40rZpYvLClOmSMmZCpN_0DMk%(&gr3dQkOSQi^_h71r#Kjp(GM-U@nnI6U|(clW~-E<aa'
    'GVxHxpM@lSvIX(sh?zqOQN-b#5$nv#Up~-+X7OJ{F0hv^k3Q#1CUKTG#0He6kN61CdJK8c#N<S{JZ0O7$cQ~C`ixmrJVx7T$<+0S'
    '9l%7qF`FUsR5b<`V4^v{JAHL_b{>2<IXb=ctT~r1X&RG6R&G3vKC>E;)0R&$1Zkg{TaG2*SXvmQ%x_@vi5IrmfoAXq<BG8X${*bI'
    '2m9ltVtT<^rJ<5&2<ItCg}DQmWeny*D>hnABY*EN7VKN#(ZS4P_6o*BivZ#mjYPKJ9|wsAdW`ve9xpOxuMqsCLXqk~YTPiSt;uL('
    'ZjyLZctKdF6TOkvBAE|MBl@R*vZEo3iFAWvhD1Twopciag+#uHFo}yoh%LzaCfc?KhYkpi_8`h{5&AO3P$K>h5zhUT>^N*QwXUp9'
    '1kH#Dbb-?kdWMgOk1`H5F~$WM*(5z~<7uu$2Dy}FM2^Mgjp<j`%!<upb(whq$)eJB%%M-3`5!?(v7XEa1BYK-*5F&?G>W#l8O!OI'
    'UuU4Xxhe+s2*AV6CIvjytc@|9q-1Ba*JGJw?DghTCb7JE$cvm>1&$4TCgvn&b?|5SRTdoET~0|;or=GFk;p_j7L(-&e~cm;#|&av'
    'SSZII?18NKp%0+Hi|jHHAZXed8$_ySgIw85b#(de>@+z0Bgu`Ui;Iu%Kj5=>GJld|S4e6Y{X7zc!W**S4Mz{-lZ7Z!Lm2N|DVEPK'
    'lX5g_2A8+cPUd!zM45`_ppTM3z<VrF5`EnezlehnWH%005soeC^KxcLzaYgpoJXX|Q^O>=WekxSFwvk2x>!~`95L&sb3m(39F+td'
    'I~!ow&^|%wknUy3vXB_mk`(HcMTbA|OIGLRISDc9jXgl@5?FA=#!*s=qbO6cj7;c|J#Y~`?9`uv0N#@2lTTJ=L711z5~|jv)OeY~'
    'PKdJudNP3?3)!ps3w3)PMGL4$)WbFyKW*a`5C)cP#l8?#TYXGM(<ZfO%$gU`g&{}wDpeyLzSoNgl!;#)ziLd&DvIQT+Yl`5lFWkO'
    ';{DOdiLb-JEg2H|rPs7K;W&~=9t#g~+F`AO5N=%-;YLLy4ihN{&iE|LF(jRZrvz;Rv9UNyrp%py(SUFqhcluGoY4f{>;*y;VA+GH'
    'mS9h!T=#6niZWD7xcb1=itlsMDV;H@oXCa<><W9HhBJ&1L7{-P8d3mniQy16$Ma<#iQHf-ddysl7tSF}HaW^%vM_u=3a~w9G#`#$'
    '@v_><ni0Xhn6M?CT+QRZgks?{DKvu<mGi98&#$IYNo6NnV<``?XPs0NyWxXnJSFXoh<!|QRAiZ`Da7)(h2>}J9_8~%y)N_wh{Qy^'
    'kR%s}p=4#nb$=6QabYw${?vm_>rl048B&ofm_;OX%^&IX!xsE_dUPH*e6qwBSH`D3ftwx5>DzERhC-5?PJq;zPM5S_Oi%+c+Am<M'
    'yvD8{(`HP_^n&Ea(v6AxK%@W=W1_XpH{Dhy=q1dGUXqkGuVqO*%h`vcDCJj^RQ;F(ggQb;zKe$*9t$kAEaH&#QIhBhoYQ3B5o;x_'
    'C7vfNt%UT5sYOs$z#HkSLYP5+ga$OnVdU{o9g!uY)9_&sUWG7y6B4i~o8TAMk+E;FkxXt_XK;PB2?_;SP9&ct>?zPTLz0g-8pWY8'
    'pYkDKBMfi33rT!9G<0D2<;3(RdavxzU;p{PX1WS&LM-xNv=r4q*De}PNs%k0a-FN5sPBWi>79T#Or&{u6JLo(`v|cZMBmSkUmu?z'
    'pT0Z}KAgQfy}a;<4>mMrGqG`5>t|r)Ui=I(En{&U(Gd)_X5d8(j0j<tAPyUn<}~hnITGbbR(C8bS{8Bf{2IC?pCB-8jts(+rUrhP'
    'vYIYoerm+wD%Kd!)0G;yvuK7H!HoP%B;?PUl;7()GZi+9)P83%tJKYO;jMoW2Fsl@hG}IuN4&+bHpn2)+(00oQx;WT>~BDvaK=6i'
    '<8>Vp8D3lVwIIr1@quNg)n(jUvYd_}FlMkm#BahJtI(UEPTBRggj9;<5DmSs?oNdHLKxZ+$>0U3=jGe8vkTb%7w_JGI5`e3&(2Ot'
    'lrs;B+m1vAu>{7ZvAdC#BO3cKUeKJpjWSML4#R4|ooP%*VMj@Jc1B`~41-COY3Ot))1r-~2Y9mnc9yt`m8yIiXcxl~Sq{K6TtzB;'
    '$auz+84k7bu87R@sru+0!8M#NVOD2Q`jsNH<%02sFu!pE{lOd=iz{QxAS97Dj%AA^);1vN2vbHhjbuUGMPZt(ktnI)WwW(bHB*b6'
    'O$jz3plr+_!7^|xud`sjoDJAF0;2jUVgnVuCd-kk2h93JPA<r1U222?s=_p$#To+ECC$L+i=K-OgTuzt-bw*M-!se-lvEUU6NsP?'
    'H$SrvHd=_XF)32GGi7Md;E12SeD~qF!0xz2c|ym24sjIX%tIQ4OqV}#_#>PHdMH1Vo}5oLFrNUW7Lc_8A3kZvL)`{-S&45cAhjmW'
    'Ci2D<{RDr37mfi6L~_$;MGSGlV)Ta9Cir1ML_~Kbwxd7YL{|};mYLDdua+r>`;tzA^CMiNv=1=upiz)%GE73%KkXb87L}rH(t*kJ'
    'psthKIjf>0=zSx$L|9e|9$^ZBDV;Wmg42P*5yEMiJ10bOiL?(Hm?g^vh*)TZRPscas97;yN-~2Wjm?W$POMFRaG5%u(3T9<4DX0u'
    'BHb=UQ$$%KuvMtjI*YNh2Lsa8ugQ2oh*YWj+yrUTsB9-61UVMnND6bb#9o79&C{k)4`VW!R=Q^F04rQpPW-|#jx|cfuI+@620N?X'
    'oFBh>cT55|xCG$w_~@Kt{_og>_0soRy%d|udaP*h#9<%?&uNXwHm0$Mh~{9iu>V5Jvb^eq5xSOB%5sG`-O3SD664~f6F>Ht_{GEv'
    'E%^+LwqiUbBN$9^8V}fA#vYn8Y%eWebOjt{wxA)>m}W~Xx$M(0&eNp~##q`k66%c^M>Hnp6w3h=_C=~+a*ItKE*FD@S}EHac#Ve+'
    'i8xm#`Xh`^xR=IBG6KpkoGP6_1df^khe(ZkWy(&{kr#<IdSS*c@s%;)Xs9CTX(=bLW?*D5mg$hybS1VIFgw_o;O$p&k6F@&Ku01L'
    'v!q3WpOkbNwRY#s=HM29H!3Uqq2(CZfrchcTyx0YHVN=D*^P+UGj$XH`0n!M+vC&V_1VYMS8QVV!kVmn@$=JQ^$aecr02zAT8(GS'
    'y+SII#GJumV?GiHItN2Z=GGlZjYYEsNCUn>EImZ2*-h<{RN&HnvcALWUam+#P}?jSF-M)zN{W()GYJ-e<-|hBvE+lSCIMtT?eviz'
    'TPA;1sEK%Up*kX(gyuC|R`fsWPB{W;`?>g;FK~EL<<U?;sV9!=g2({t8N;QBjR?_KG-iLF=2KWp+He@PqK)D+=A01gTIb_HcC6Br'
    'wSr+%7opnNxI+1P6UoKNF(G|uz4SZi)Q0Jmu)NqQQB@HuX5&Y;!bFT&&Yr*h`SR_1BBpaExbFo$7pW|jRnmo*TopbCVdx@NngO3w'
    '(ofj^#kz0di4`~7BxceArx`+j70#2XH)j%sH!Grs<*=;6Un~XpqcRGNh&WXm8;n~TXA4izBB!SCs;eqDV%3RpY4j4Ab@2?^xE#F_'
    'TU_SLnfN4b!Hm$i5$K3YF{YjbD-R^p)j+6*(OD!oMLZRl#@lekA|4SOoT<^O#FKw>@q6J7si&$tDs#_Zt)-;QC-bMO%)t{A<<e6K'
    '>m2H$!s&$JF6X54q#1_@B=qO#ZX8Pgb^a~HG5Zez2r1xs&^Z(!?%Fe?&(E1wvj{Y)KnQ5?Ci4hQ(wSt34O=Hq0|s!*AxN2g)Z0VC'
    'pW*1@e-$fxiC|uaBe`5~`c(7R`SE|eJU{v*aFj;{{T1yaUJc_4Qj?sT%o)qTjGY*H#MnZ4W)Nkve%9{^eEw(@t~h{6{E#f3+%%Of'
    'uMqUl0ykU(A7F+|8_wS<o*0i=GHFQXoP!!cQdp&Ms3@BnrQxlJgE>qRUUx&E4F6~S%uoyB%na9a_`AlHHM(z4qHEEHaKOR0z-|(r'
    '@`^YU<|(-j>~(-^UKME$3(0X{b4WE17S<X6nDIGvhI&rBlt-NJCb1n+^Oynsc?l3Bv3FSK0=yy#EiBMF?7%h=R8{Xc9XI-00snlq'
    '$7y)QNCXm5Of}<aa*N}F5lWy+!KFBH;?P#ifiunv<Fl7_V!lu8h(klhLL?a{o<ufU2XLq40S6MNBV~SLGBSXAC>*s=b7^xF3F3&+'
    'Os1v*FVk_H)3F-E{G!QZ%b59D(?DR#QGZM2C-FEp(P?9#8!xKa@L^;fcnmy<6y*U-M<h%dS{5QoS4=XH7KSzpMur^1kTk=HgUy0z'
    'f%s%?r6%s}0#KN>3;IB9h;%tm#$z_kH8M{m8;Z+=U5|M#Ve4foi&~1g(?&2mHaZ=xb;xu$AUZ_ks2GL<PMn|^$N5;-m9z+r`WVCp'
    'Od8#Ljh{C(7H-3&EUATJ_2d%!f{4OWO+j$OG!owcqnKIe!J7L>1{WA$qLoBlVjCRsmRJW49hGcItcoXLfDxg4tQD(BwrrA$c`y`U'
    'shcbl`W=~=AJUzGiO7p^<_t&=gSRt;=*9I5GGyf~ccN81ethIe73gFFOovr<LQmO2*n0@iGxKA(>gTzejAXnZ;N0AxfQ&}s(4$FR'
    'B`)tFlU$A#KwbrAyg=G6oZ#yXd$^5=1rxLqhMy={5+B(i2j&bGouzI#*ZeRw<F^f3U11r{(B6?Tk&Ngt7*=M%PiDc0cm`n0xrbe0'
    '-zw-5;cDeMh)2SgUgU#02vF8snfHQ6T4ygtxnQv*_`sVuP390GoXHF|$r&u$SCZ^Uui1SSlAVc7z?c%FW5di<Z@2oiBuJ=^wh1^~'
    'o<Q7*6hTOU_~OXmuaxK5oH3Sj1?^Qs*p>i45KB&IEf*7s*fH#ylNA|p7myLl!?jDrvXTX%s4z@O&ESG`fbGF*n{|O0H0Fgcbhk`I'
    'RzfZuN?Wm8Iwn>>0$|;vMn-pW<^|vyI42=*C_GmnDK>wENll$>IGh?Iu_R~D0lrx;@NF1dBS%BiW*v#LV-+K2FibcC2<1^R_h!<|'
    'Z<B4JA1J>ZIm4FQP8>bZjUj7PllM4VK@dA0Y!hFc@bb+fxG60-MIEu;$smPC6|h@zV~V`s$dZB)i8~nC3kT;4s*?!(=(G5{Ot_A>'
    'hL_<s&LYkq31%3gq#&^;Drbw1HXh+dh0Q4x0z~)dIJKoh@mQEhN~Y!qO+&DZ%sK>C1`VFpnWK7n!B!#%(sjK;FwA&#*h@VN7c_D<'
    'sM2V<GR8WBAuGkzF^@8+DsgOR0LNKtU{5TJxmavOX=Gtt|F~q)NvMx4f*~IyjwC08Khaz>)sRU5!5OEUERY#F=aOnvFm&;jaA3ol'
    '!Or+zsEN-II0g}lPhAuMLAy|cKy#Te3*u8TXfj)-WWI8cd1c_X&4Bp+n5z*Wny>x_;@ZTGMN9Q4+(mgYTh*|Q9bN$>hZ%u(;c3b_'
    'I8K}lmb^yZZ2(=u09Oey4-tSS_ThN>mDXXa(kMuHAXZPW4JU?m*8;nKtAwvDLB4dUN}{ts<`~~f5%Fyl;IV9}+pU^GD#}?rQ|lR;'
    '3=Ck=$gmG4(&JF?I1=%|zH)<BEAk=iQd$oK2iF)xEZm4mk>t^k7XfJy5{A<V9UY;Gm~l*qwAIGf$H5gM#%r)8S|l}Ku7K=voor^7'
    'q#LL?OF96LqH1t4!;D3n6TWTX0T#!a#=_d|5=;b+gV-u;NRgU~41xJSG*Lok-4ON)=(dN)p-E><AG4x3h=iyZhoAAe8x%1z4w%E='
    '78raaENhj|c^WU&52&Jz=}@?`kRvlMPm}cmPX*!C#;`333hT3I5z>_=3@|u@(u9L(03(7qDxpb?-Ocb(gDav#JA?vEPY#mQq{U?*'
    'MaHVT=NIqH7P(QxZ&~N%WIabfLr+t7WFp$eQCP}1RWoA}Gy1(iJ8OVlXp2l8oDkJ0nLA2&7mJ&uZdBLC&%x9)E^(rHh%}?CD9>t5'
    'h0IN$(==2lEF>N!NR9Y?=9mVKOp@r8WAbMU(Pk$C_?dFXsKlQI^^fDPB<UK?1^j|!ku1+7UVy*6O2b>R{MnQfLn<>dVu5ohl1`2<'
    'bR9tarV@&~FqnTddlNAcK*!E%BBN;z3K;_bz9h0(6=YeCh!;#zqA@IwAr$y1UD1J1`;<njHZn($0Y)fJ6^jlS1mHd#bdIN1ovrw9'
    'r`SXr{bilRWPs#wfH4t}kaM@0@n7Z*;WqD$eQIO)#zD;z(u7lo%n>!{9gZ1wC-9i)mUfzv?XEu`-jPUQ`(trchtp*!iKavji@9$P'
    'd`L+#96F#imL;Gk2GS`MLWzxcUmQ%%@*xY^nMHw4SdiGJUD<~75b)NNeg-~h3`Zmo>j;ku(APZ@VM?0M6j*(DtQ4le$1NtA7Fvvj'
    'P&dn~c~rNr?4)FMmc<cU&ysJ=dX$2M-W%|Jq$y-&&71Rxfndly4f6h2xur}u1`WM54Rt;yKL>GX8=I5G6xTc)@g_Qg(*|uK6<kj?'
    '5p6fly`YK{Yhg)IHWDnf%tS3UeaJ+@5D4N`T11Hec%brI6yB|xM&T3z@|8(j8mIB-DsqmvM05>YzsL>DmV*quF)z75Ax@^zI0qZc'
    '+?XL7_oPfncv*b(9Nki|0OG93jKDBvpf8dN$Qt2gSPHCVCZVLT6jqgyTev^Ox#Q$Q#DSyZcI;$WvBvsBXk%iQMZ$BpVJ2AK;ZlyL'
    '8?j^-Aplboykqf!S_vHThVF2~kEY8E-ZGH|23KAUWEVafc81WgLTGsr4zD#dcWJCiur~b6u{F--4_RmUQ<xfbNQJ>w%@8&~(kMx<'
    'LK5mS?@HL$#C#>V?08MB>s6cuR#;7vK_JE&1Q9j{?qJoVlZ5#oFBI)?gWZ{?PgVJeYG)xN3^J>bv6q$!9*iMk=iz)PnZS}}LY&Rr'
    'p|PAgqt77ZqXB$FZ5j%P`@u^CHWsl3Loub2{jga0qSc`Gh@C@h8n*TxS!H6;$>y2xHJwk<{#c0K8kYjXmM~m27hdyjXd+8-S6wAq'
    '1Sk<^u$<2$urK(-ZowD|imF7fEmgfz@Mw`C2J9jR<3#1)$bjs?k(7K9MQIpEnmX9{2ue8G)!`&ktsI1i+Z6!dl5(geEN$2TK#mNd'
    'Bc*C=Bh?^}Ok^AKy~OJztlP`My(E%i_opn5m|E;L&SZSm4O2Tq3HbQxDg#t6PFLF`DR53Xx+&gv8wCZS2odv{XF)cRV16i@h_u2X'
    'Sy(5CZK%;!NN@v;1h^rG@QU2UxfJd$Tqf6w43{=aT_iIa{l&+~z(1f68G%};tKTFySoz`U+p?ODp_(UGoY+@TlOM9Sq;x?i0Y=!L'
    'mm$KRHWAnfVtT1ElbDNXff0m5)H?%_F>z}P4*X4>9L7B*u~OD!$Q*IO?~aSi322K}X#8~*WDSo>LfSO2h5)1l+`vdP@j)7>2U7YI'
    'MiuMcmy!c$C6MFA1;;{(K)+6-2nJGG;Mn2km@YGK7-HQ;Y#qid9YDX^$bF#Iu&!!%zmSTh#u4j~*&^}Wa__~9s@Z<<4Ejm99O|@H'
    '1?*Uac9DLrkR7NC_)ZoTI32hRn7zZb%?Y5eJq8N9F}2G`%1fv-nlFt?<wUUG6=CZ}z)pS}yAGi%&e?;hg)y@{U9uaPt7Aqh0g{<$'
    'HjX%&Wd6BW@(POh0?(Bkk2$7`$_iYh6E!&_RxdeR-7q0+E|@un-@a*6);}GcTppjF9({cv8_^77zG{N@+@@or_8XG=e?s=;Pi_*z'
    '1%0iU4$os{QqH+-P%f%kl)8a$-Ur4^7HN>?Ek<45CPm>3IA9q(9~BWzO@1HE;vztvE$5A(=nb0a0AdD7@nAGW;2Gx<XqvbMWiXHD'
    'Qhe49lrjsV>DpKek50k((VxXXt<D5yM%*vkyAp=D1&SOIk8(LZb&5!GJPQG4%gc=IMA-rL*KyTBMi(l2AkN)^^VtE#6r5ISdvbO-'
    'sPXE`Nn8yLLdwk3JE+z_$C)S0VI)dmm>lyd%WMPJ^~d=%V+qFH7_X$!Fid2pS=3uVBnrOiZ4&7M-?q8xq3jPVvSsA~tQ^;c)IgXE'
    '0p~ENuxaC7%sCyzb$}WVIS1}sC3_+kjqb7T>p&G~&7tPK=aOA02^G9MHI+Dy-J?(hrP-~E=Z`rP1tk_#4yr7d*jdP2xG1s!9gjz$'
    '@CW1ClROHkH&Bd<te+|8^(h<!y}&Jp5G7flaNEtqJg{WQv*b!u?5%PsiX)qxq^eR_j)I0qIF}$|OrNN@!Bx1(itHWPd~A}&TVZ=-'
    'O9R(50F^VgklEY}#|`FlQYx!~S*Ia%eq$>~H<FXZnZR*)HBVG`<xrP*7-Cc4MXP&g7LCN<00uN3Sz^0mFb>I_DO^?Okp$tb?#*D8'
    'tl&G^vaXGXR1mJCD}Y_jxsHJY<S;bM%*#Cs@5aXI!>mQ)Orh;17YVtr5y&De2NCWhaGIJDr5sahe?Nfr_-OM-S&J}G1XGF3)54uX'
    'WL)RLJpq@+gMw#_Gg_FD*$@<NU~tGH5yg;C^e8p4WR^p$jTTiJ#4U<^b^s+A<!O8tBT}c7OSv&FhBk<oO_zn?A12Vj?AQPihK|Z_'
    '9ApLsGK*AvCBao<il8bMMfjYBJ4if(wx!5?lvbSb55#(hFdErO!bKpOfmE7M&2i3k6gW{o0$d%KX`CW(e^lBYCaE|rr5?m0@g#y9'
    'Ct;=x@yQi_n6jZHS^pq*39x^wZ)=SbQ}V*DkC%wc-qaiDV#0;6JFMpx$-GX~-)PJxR~Ln7N19S1YK8+Jv?sz8J{7?zI;=|GBD8L_'
    'QT78P-aTJcU@!smb+3d3qr@5lk>Z-_jH;TC+-=N#Cm^a&F^trpdl=-9u-{Nn7FgjAXO|bj(dnz;1F1*ImvfKAk8}0o&*IN`_!Z;Y'
    'K(7hWGJL%Tq+~rq)0OeT4kybws#L<*3kFjLEF*0loKc`tiuH)+u44%`fBAeFG$j2qcauAr+hs2K7?_O(d<9zXnMRg|Lz*(5+M=?;'
    'sybeFNrTG)qVB-9f{XYs5%Q<78R67lbMz6<$I~VAdQPWGTppz7-yN$PI#YF%({v2h3jSFsp5%aqZ{jNucjj_UkyjjqGRJ-tp$>`T'
    '?}=xy6yl^Pw=`tUl3lq{<W16^l-Cp`8$8wv+BU)j3`!u7%eiS(aLU#{jKkXyXaVq*cCl2@p<IM#8m~i$*@OH5%1Q$lxkc2-nKt}V'
    'v)jP}QO9cg#n0PZPFky|6x9BjU04GLmBVVOICE(olUW>cs1@#6)_p7vMOZ3VAxPNx^vjhHBZ^Z&XsPSKM4?dcK|yrljIjkRfKq{Z'
    'YCP##wq!7MaeM%@a!E_ZZ_B<A%biO>{v+%V*E^UbtFQp;ho(4dgXwnLlr86SFz}`qwM0S_TeUMTK<uU*$#hj{<1R>z>rP})+ZXYu'
    '(5n4$&&9_&CbH2nr^~^>)Q3^HSGM3vNi3}dXq6c?lk`ZQ^(3;VM!=qFQTuP|%2f}QMUzL+->GRHLOd9(+AQ)8gA@T6tRxy(f=K$s'
    'jBJX*Q&P)U@~9kB2MA|s_ySh}mwQonJmk_d?0e^ktEkS|aLMUJWQ&y0D^mSkO8RBxQ_VKO+1Zc5(Isa%&?z9^fA*R`d^kUQadQ0L'
    'Jr7Q;gV0it7KkyTnT+)b2U$6BMHI<~VvlX<LWpalS?QQKTcvO#XbB_~Q&+caeXS5F$x!%mujg7E%;vq>rLU+)ac<#)65cCLx5y!A'
    'T27f1sVP@@6&nsip3qr@Gq8Yo2+fEpXf-!eA|){;(h8v0LM!;z)THsCNDiLRsBxq%(m3a2P;o=Nbd2?a*F`w8gi1`DRf7hpoGv*<'
    'O|B5G2&9-1mn>G;9d2Rw(NGdptTK5m2usf>W;6lgp>M=El6oghgmW$|CR!AeCWh;xALYbxs-&X39YuA0<}WXUxQj<_eW`~bkw@&U'
    '8yJ9%S0>w7O2Puwiqu^2^W&Fi=daxJ@iJUUym(U1yJV^E0}~5qtrRJ;MaR^>vKV}}GX)mKwvz^GobZK&<+K_&JWNx+44etvxJmb>'
    '2G54%ivr`wp-8E{!TG_$D`?cp&<x^2Ojc4Vq(qP?xVp(6K<sJ2xv55tWl%G;Tum{M*4R*-hvgG$+%j75hgp@oMIIk7760)#t~pa)'
    'wLoGja1KabHK&Gnk-J$Gf=+Gpj<Mh~xxYvY1c^u2ttja@g#_!S&{57380tBc<C2+NB-1*>iHh+1fM&t>!<g$ukRi?<L<bSZH3p=l'
    '-rUK>F_2lUq>BqOP{82i?2SvRAK+*YHBy0im83tC6<_#VWc+@Vg0%PS+Lj<RQcjAr>6|!t9=e)~P_)6Bv3tjXklNDV3T^PHKvtW9'
    'fo4OkYtSh^l~0V{#<z$$E8VTX$k<PZHERe9Oy8|=WjQ{pMMYs))bV6g5}S{t_f`Fvg~_UksmwHT3nzdFM{#~!L9=1aeOt3uVp&|y'
    '4Yz<;f21o%#pHD=^x1IC(5xAh=dthjvvfF0n2Sf#sY|(Bn?tHLmuff>S77ievsYn5>g9xEAI1**dMqcc3EKP)obZt<LN4f(DV{BL'
    'a8d=gEmKn7M$Wx8r=a;dx26R(S??GyIhIL7oG#ORg>81U&}@+?DnyDHYYhnN5^M$^$f^RX1n3YYv;^Uz72C)(qA74x1<NOh5vGLe'
    'mB#M5S_&(y<4`hrDh91`WD*&wyE&zJOa>Mw`Ku{WFb7+f)r(>jfHQ?Bv%^L%b#SnHbVL}3o(<D@AhKWS6g8GikRGKBMlq+xvu3)S'
    's@Pzb=KE%uErtaP=la(k^4rG_n4(%Zcw;)nTo={6486q_fb3NfC1Ps*{&T-*kyAv+Mar^6)jbbq8pUEQq=fBfLBTjMMj<-DWaP7B'
    'bIqy>irP5EI0O+{>{3yy%P{u07-XV#$VxD2r>NUC)_G~D_Tuf?xv2(vaeQ&X)wNuzuPdvHqTT?pv;U}JVoj{n8s?eX`b};bF0M{w'
    'p-YM==8PaA!?~&YtllybZlo7IHBebCod*OjCxkG9(<AptJ!Hd(!=^?#|9}uSFfaxAf*IkNp-q})kFu20D5}G0CZ>yIj7@?_$`ELr'
    '3LdfWJXC00W)lTL17)ihaCnBQgF_27=xY=`#uCKP?!*h}*Krec9piLeaBmi|w}zd7nE*#M)KZu{CP&239P~Kxr#sc1ED66tu975O'
    'd3ga6;e(puu8G0ayULKbK3SJ{shnd0$@~Fe{cDQ`V|O^$7Gjl7VN8jrDj(h+5!E6T#aF2O_;Y<E$}Kh)jjkf&inrWP7^@N9HfIbT'
    '0+0e&y-+q{DatS|mh){~wlpahn=_Tn0+eDU9>-}Wz&P{GGF;qOVEaqC6{RSWR`1?38oe1ccXD4Tt@+4=ZbGT6$A#&zAy?Q{4bN+V'
    'E(GZWOK-8s;gpl=6}ZmMc!xzg_NI&TwkhEm*9#d+%!z4H!f1?IwgtzBaXK`)VWP$vR6c7dh=JN;W;TeVrA8!8yX^Ai43l(ZsQktt'
    '3eySco-<#=_VXT0nXCKV0{qDlfeE`LpQ^VlEI7SDVVJ}EMFFfR<`U(gtK6Y$t~-y+Q>@a9cc*7BKb{<&2hI&k_0AN&;m$9NMS3`U'
    '^~S>L*uRewJ5sk#>PkW_WFK|mh2TX-6+WSi3@0NYWgfzlk#!2oH{3?*`DUt4*$}i|Dxua<iQ$bZH4uX}MG&<PEW(w!c-~`EPfOC7'
    '{bGnOZNex>-MSSMHyB_cf<hjdLX1jDaz#;mE_N13sn|g3oQO=A4ln?4MXg@uK%9;6W#b5HRAlneEq#&Z(+mXCJ#}IYKy@21_i}E_'
    'EelA!q-gsZwz+Icd_j^+#F1RyCoSZHVns$LvV&sR3YT%V{*}k3oE-V(H?)j<Iv06ouR!8k!cJd7qyG8qBMRdGyw)oy6v_I5Z?ZEM'
    'MlD&d6rR*jNKnHa&Vw7iDuh`r!(C$L)y+V$o^e{FJHTzlE29J~wgN-es-z%inw3#Qu{hu+8>+A>Siu*t6l0f6>PfkvU~pv7B-`w^'
    '9gBCsCeLZzWG^qxsDzb-7<a$`p-V}BwQV-|0)=5z)C|V18&WWNKK23%)#G>*$ueIqTp-2Nt$Y9$lgdJvG&!S9J7qUSo8!C*qG{Tw'
    'lDn@|9FhrAQhFpbs-&%g=Ba}T#t5~Nhd6c}+_K)#<_3lqlT{{xjsy_gGUOc<WQ}TU)6MvJTA{~c%47uv8yCk%7iXtOCx~?db#~#0'
    '|51xm{GmnF(nRiwq-l#v0n-}VYHhX4hI{`VBHwDC=~fkdZ4eHxulQA|_rxco4D4`8WXQU|^@dH9N(@;$MolUOMx4gP)V9f17HP-?'
    'Iv1^#)lMhB$xr-be~BP?Dy~N3xT~lPbvaIAY{Ez+c{&$Rqx#2zbdxf-q$qLmf~j16y3CyXN!K(i8F^R-Tx4fTq&p=0vZ(qfMXa@k'
    'wUl|Z85=T2lgUIpzhR+N#YBp_uZ+NEY^FsSnBirQNVhsNFBO9Lnv3@5dS8V&>jvRfac?78ddH`i?~YD9%5`;q8V|CQ^m0M1DTqwr'
    'hRKQ=rA+7I&C!^iRJTdkAy7mIi;PP#42YLxdXofKoq*qJ&U)}7jzn>EE^{nM#H1}771A)}54Ik);hr^ByhmVU1737w4{=8IERbZu'
    'w6K@V)dFKKwJpd{qig{@m?j*2W0o&!6JKypaYJjBcS$o-m~o)xP(&mfounbrk;r;S9hKsi&3`G5VKIe{d%*hT<R&V6yR^q>1tvLg'
    'DypqSQ%1B^Oo0I?5>(@(TErwM3_T7c!hBignJX>za)3I-VUdewgq>AYUwr&II3Y@Gn43C-_h;wFB^5zSb(t();Gz_hHwkf2X`i?K'
    'f~}k@r<%PYON)FO)$EETZt^XGi6*Z_>an0lM^h=Nrq!`+wvgwyH3nwRiBE|p0>CZ720eC_BS>1b%n-gn&spQK!Zv$axbwv>z(g_z'
    'T1c@7%k@<+lzL%v_y<iS0-P7W&frfJoe<a^Oi686PZ~(nUGkik3z)saci%)Tx33Lqhxr>z7=iRJQ_-qz@mdp%mB@5)tKJ-mky<oY'
    'fV8DDxq9lvQ!Wx(@BZ-gUQwA@3gRM*ijo|no+Dplt|HP3QU*F{v6kPHGALDc^|Ck?G`4sl4zaB?O2_QotDlaKe>8UxdY*_$%(YWZ'
    'J-ci{HqdZlF*^)xv9)!jvfh+tGpa49YwPWzf_R)-%RyUJ9~Q230n%$+sk<vzw}YzL4Z+O3$miq2yB?K5Nm;RavEVTkiAStD;GVT1'
    'lB`SxKQ@p4ybMjRjHO<Li!{Ctiwe2Hxl?La${jWWb4h`u6LNG0Nz77YSG>E_vgB%v&2*gn8+Y7);G_^Op-Zat@S6CYk~hP(xFV*l'
    'zH5u_))j}fuQ$w%!zjS3V>k7;;9MA9M+mBDW>Bf*uG9#YSxBYhu};mUb+J2eVrDo;*dZxkVzOJpTq@Trr+G?hF_|JuJ~^CISi1eo'
    '=Bh|^0nx!y(y?ZWN_ks}aEZd82~DIjoE-nhcP}Jz{qBSBjd+W^SQ_ROF+2q?vCI|zhYTHNrmUZg^*34P0kA$K{I9Oe8Ve2aDm4_)'
    'N;{;bre(1+;Y@<K<QjDB1$XN*bH!*qF;c&h=*_Jmy(x!IssYQ7atY*Yz<2CXr<^Os#ez*i?V_A%xXk~b|J^$Ve(_#=PBo3#P=hU#'
    'Wpnd|9{iHZ9(F@Y<4W?Q$bThDdugTo<{u)P!DQ~uEULP(6^a9EimT{dr`+teG8-mlttCA#kg(RjQ4l=W(H6KF4a3uvMgJi#Ktsy`'
    'O_D4<^<3t0Uf}q=L@%k&IgJ`x$Z|}YoTM%nS;;23_@Rv4qasOF88>h+Oz58SgjtoZ7X5H^dU^iynj9bD{h~lggY2|G{6;VawumuP'
    '@GQwpE-fY%yDmD0)NE%awBTkcM=Q>xM67wjaSx5Z#T?9)``v&GknBpc?G^Zj7NO21HB&1l1-AUQf2*x#C<a{IG>=U&a+49y9L<{H'
    'l3eT*?zWg3v+Smlu^b}FY~Wg*e+tvA5(3wRT25{i|B4CTNFELHa-+fwmVEa_QP*=xk&@6-x|CusQ@{s~G(Yfa%1J*8G_T%^D6wR='
    ')?uBa9fLOU{T3#7POsO^Y!=;9ILoztt$U-n?TO$yrt!7O;x84n<`h;<RrV@d+pCHhdnLd{uEGmQfhfZlmuKfkZ;ly#Z7-WF2=@*9'
    'at6Hec$}$11wQL!(bbX*Jn03ilHo))tK7{APbVkjMbk`@0UG|r#x_GfQxCbZd^zJlG9Tdrov!?Fu2h9VK!j1fBj|6EH7Au?{ac@%'
    '^5jK2dr?Q5DU*XnlH4S+Oo~nyN&f{u5ib*rO@=L1AajiOF!khdw=7&OcJ=N_SQlE$<i_+YG3ial0=AM_z?-ZJa1u?i`=}k{5**ht'
    'H_H@fT8@MLOR8`eFmpYD@?*rd;9#my#mL;gTtwnc^@!wl{+MKRQHHBGNUO)cAc>*5ubs39Typ*P7*NqOl<vPg_FWFE0?8?P-+JSA'
    'lv}7L=cijisjdZnycv85^8)baZVTv#Z*+?d<R>(slA`7!@{>@jL<(;y*q#<kDuH^jE%*8ZO~PiD2ad_}<ht($Y?_%17^0hSk?>8K'
    'P*S*9II<AsGJv9lyDGbq@2!Q-CBvAD9n_`p*b1`od^jnctlUxZ{o4mzn3+O_*}Y(u1zW1!FI}Vc-Nm8Kx};ZfSL$Apwl%42L@|<z'
    '+z#YoJiVqw>$cmIBo<krsz~tFR&}pU-V~eH$&)VM&nX4m4Twpc&Thm~($!g>8?OYTnvYIv&_G3|fRrV`;%aWAng}4xtSCsp1<cJA'
    '&xYVlso4?IYI7-Zpk`tyiWsNB8X7h?V58KXy9P_GA@(_*Ev3*0cs|2$D|v#3*2My4jOE-dC?QrF7gVqXA5EzO);pJT27g2&Q;%e{'
    '9E#)u)jt(zh#j&%lj}X7T5rO5X4WAi2I16ZBU>DtsT9m!%C%RH1jW74!z3*bpL_`br>R*?vs1-cZscKCXSsxY5kQV-f=HFI7oOdW'
    'j387cU_ZXzk{yL<sB|TTE>Pc^X&t%Db40K7Vl2)?!12o-F5_T}HW)&-MV|DU+~PKB+Fe|p0<iu?@aF6c@#LSXO08<~Qubaj`ApxY'
    '-h;iOU~aH!1x(f@L8n@c$#p~U3)MA-TGiD>M=RXymR6&<vfUJQtM#)<X$N*Y$OQ>*5fq6K(}DBrL73w<Le5#LE(-4+3byVve4vTF'
    'a(qknm@Q+&VN*U?C4jbj7a5zAp}q1=i!~tp`#I;pjH4$RAR1p5r3q5y`WLcEF;~(r1=8GG3m{NH_TUso#brSyN&%M#79CeNS9NyI'
    'IfC_96q^`JzHL18k^$`l3bJRfYPfPt3-|J#*YD0RE?tU){BUTAqtFQ1DT>m+a6-aKT)IVUYS+pzFr>spA@ovWxr?H3!nop~oR5&q'
    'O|{<Gm-l)-jfCY`UqWdkmJ2W7rE9nv^vGK2g1)nQBV!vl-uP55beibo-PM<1V<t{`3q654=nhB=I%!oBNMI4?nm*0fRu`*dNQ<~s'
    'gKt^>OH`;yBHxWPc2#FYrhqgRTT<h)b3vd=u`*UXwDQa~E?~69o-92Ah371}DHby|ZW+e1`?YCVp4dE$`|FT6B}jzBvkkbtfObq>'
    '(lW6&t#Mw|6cJohj%!>SXbg3yB`?Yr6k(U@a2m!lsV<U6vxGIYu_peTyv^pXbKv7Y5q*=@_3r4TuG$C_ySacU6o4R{0Js)d3Le>L'
    'g1NQEt$D{$JAo?_alqKioEwP61oRRgwGt@=J)a_57rx2`?$3H@$iNMbQZB!?A2hkBKoFNQ4Yjy-`AQ=mFFXGv(?ZTvku;rEGU;yh'
    'u4~afnnfP2mx`jPhiZ)*;o>PgK*biN`R!E(;i#y1)HLz$MIs3S=1w2up3=M;ximwo6Szw$a?Yj>XlWWQnG(%7ak{CsU<}-)CbN$#'
    'N*aF@P(pSBM|Nhur^e>?Nph0TB8!wQDhz^eZ334o5IaS&6a%7(rHlqcSTf(oqlvOYR?36zZIVEv!0M09EhCbR|62vDujhe-gz6sQ'
    '>sEz|7=QEc(M8QA&_!&xh$LFPk(`I?RWop$bI$#i4YB^pmp$A2kgM45V%;n5K8-0mp?O$+v4V0vXq>I2E5j_x^cWbgk}ff+q*VQV'
    '%~h;wY*fnYI>{r2U+#J(Q${&+O@WQBBo{d5i|Z6YtL&k`wuD8xB%2(#PZHcClnkxmFwEpOBTm8LnrP;_O$%ZyMt0^*ODaQ~GN?sx'
    '9|vO*Y2BLy7b&{1V&gP19#hL33iS9>T4M$0ac&LYy&&bs5GWKVzZi84CW05#(r6I_{KaQ{MwK$GPm!c@#)O|MNVbS|ibHnjSeJ0|'
    'nUuraTtZ*04~qwJM`zA$;O1O=CWs_o7lD-WRfiTFF4{$?7f+cuI13j8^TYcR&@9Fxx0;!nqLRqT`UvZbO~)oEyS~`Hyi9$oz-CtE'
    'MUX+uvW?`(L8=wqTg}>HY1M%ia}L9(={hb<o`fZM^|w3e=x$v|sjtFLvx<(P`o$<hrJ&&^(lVm01JPrYMZo%Mia%(R6d`@4L23>0'
    '-NVb2J`|12!<$X`J5dW&g5;&vHa41nO5*wEc;i_ZOwwq4`0F=!=$cr@Wb4bX-)#J_xe?%AiEV9w9)M~?zaT3Mj~yP`0Q{6TWMgCN'
    'hw;X9ZiQW+TVI|%37>C>Plldv$Tcmrl&_91kAC6t{r1bog6ot1=8WE|FrVOTo^B4vdL7xBkg1#C24IvfB9g|Hry)QR(cvlWTthQ`'
    '7TA9NrZn^M#>U38e;6ghd_^oAtNQ#I{t3=;MU#x?zkWmCP@B)65vfQ55FJ4JX_=3=_wXx!k5mQvQqr%|{MT>fiV0pRG9_t!1PZXt'
    '9~uFQ$dKZ;ok8Ruw#)4}!}glu^>luOVBc`mP);hy_<n<tVvkr^=9&j0HXGh`BL>@Uoun$)i4wn*2gQ4Y>q3&$ACxZsFRkDBojfLi'
    'EL(4OL#nzD^G)9DU%#=N`s+8p{UWrK(Vttt=(hg0^(FY90&ar$8`LAsKAQsIMJJLv&hizVAl&Fi<59Xr$-d?=%P<h<(Rj!!iEYLw'
    '-0|`xySe(|^K4qYI}UH~T$6ry#Ot58_1n_h^bfrKM5qSj2^~JmaAvRr+xQAkg!cRFI$jhFeG6DSJ#azaDpD0Ijq~$t6yKCuyCrMb'
    '5GkaJ_hX(cq$h0}n%`&k-Czg3N2kdZk2~X%sg<9$A${ogzy7!X^Vt(TBTqi}_eg%gK#A!H$KZ2LO}&STs(0BlSwFu6V{%NChT%@s'
    '5dBm;lt@@Py?rDgCKapVH=jjz2(lbR!00v}Q3JZFcUXSv0Uw_~Bdas7teSj@#h~S;VQ|5k@=WE+XN%|V@slH`JdO=bJ$vR@J$tgC'
    '!AY|is41{u<M62XVbg@|r5}<9-88ea`&q68Kx2N*t0DvW>wo&sycthqMyBT{SOTmO_#JV;g4vRm=CN7BWtqtu9_zE%{}DLs8EM&4'
    'Jy(*W`0fC)W$1i5xhBBaHf+*W!<uV~nr0RG>-lQ?(R|g~H~(YtRhsbMjjN)qX-K+z&aE-h-Te(;l>1q2ljb-Q4q3-)ORP+qxr(RE'
    'Pyf4~YJXR1MundFtkY}nPG22=IHrG`nnYPH_!J0N`RhObui9vEbaE0%X26A>{zr4>!dR|w=0$a2a(N@Ye402IOf7T9DX6ULH=hmC'
    '=l{rdoTk{Z`6s3E(-?_TE9H{B_SI$3eXM*BD{2s?X0@Lmod!pjCr1~2=kd#r=kLxwUKmjC`GqUQyk^K&Vq+)A$$5T$6wqP@uZ~~x'
    'zu%snzx$`NQ!8b7LBCGKppQbptd*gQ=a*7Q79~c!3wcktG6Wom$dr+_vI4=aJwWY?zo1}H>jc6BVnI#P|6erRBN{UAa*Kw&LY@&M'
    'zK%U{F>nsB;a^rZ=qCP;B^h+me>dr1+8d{|KV>dtencr1QM~yqbBOab{_zCWJkEb6llNy&iAFG=3)}#v{nvl~uNT4j@zJZ}bDz(Y'
    'G<?$=zJ6HAw+n&I1&?xfIu^A){z}!|c&aMm;dg4^c5&(J$7<i^QdBv9dS?NBMo6QgZJ+DSGX|PxLPy2X6u@>x&vtS6V5=w*R9s~9'
    ')oL~zLZ83|j9<n$HIjwv%itK&C*Dqve@+_H#`WPWTx`;!H1N`v`~d4H3l0N67^Kb>c_bdY&BC#UmbGF0$L%zWhAFNi!{|86b8{Na'
    'H@TOsE!*ClulSAUQonrDX`m4kQGgHOkyh~R(ChnIP_*U@APwPI{v$kE$7!0Rn;Y@`CY;8ja!d^wJI=&8#CFKd{o-^}%$t|t@X!s4'
    '6}@7w4p|~;kgjACPNFm^pZDUIZD2gsSkC~RfFFbUufGrvI0`P_LoIW4xPLtRcz$|xVhC^2ettJ0I;Vd-y4F-q`rY&k6Sg}P9t7BD'
    '=5smqI4nswa~S8;)e$&aAQ#iIm7*%-fBG-3IbUuO^X2{=Zd|oRxd`95&LHIjvZz~0RdAmTp10bxSgjtNqvz)8sG&g~<F4c)y-+gU'
    'oYOvzuMp^~X+BJOpW+!=Yv~Z&(s;~bBZqK_1pQzodvP<g`)pAW(!bt?t6HH88pAMTMFFblyOWcT7nkQpm&dPyi_4F%enx$eH|NL4'
    'q)a+b@&_6^{h@SNM{?<M8d>oo^(_rV9HkjvkQDLc%Ue=?k3XCo0sHXpm^=8ArJm&V+lsC&UvI~_gy&(J*P3mO;HP(&G>%I$RE{q$'
    'emXn1L!5M;KO!hihoJ+8|Mv_`I}}r0WRwKYJi+Q68(CSVQNDV>&ZhhP$W)J$)YHMr3E9##x|oL4r<7o}Um{+kmRfPug35~|T`7Gl'
    'gC9IU{=As#bwKJ1<D)w;=T^t=)t4`Z-=X1it$1hng1s}fO&hkvH&9b%_~y2%MUwkL7WRk~xuf$y^EbtP^)(}Q${`oy?b3LKkeva)'
    'Cw;UCyg2vXo6){Tz*R%?el1Jj9u=uZVsIOEE4PuPyp6y<j#>7&QLDtaXSV)Cad^f~rl_R?KG$lS84XbVh94zE{=fZh;KX15`G29|'
    '6>Z(?HDom^1U4w$MkPO6&(LygGc{IZjMPk&M;?|m4oAlR_DkzGN4wzb(m?JFDF;cX_b>5c(=^nulH64ZtboQpnrX!6YE#>RV#sZ6'
    'HQHN_8X-nzefVgj(2+Mh3wEobEjW;Y$7l;M@9T60^Zho|wOWtRHS+XQt0nyL?4%hKL{YC1u(K*+hg6+bfS*Hw993Obp>p>%t^<LF'
    '6t05@)B+xfrw`Z)TI{UnOc({Wajhs{6{s>{G|2TSzE)h{(2hW>Pjk*lftcpZWvMr%^@dm{F~uqB_KIHL7Dh|IzI=Oheu*PW`$Fdx'
    'Ndp%oY>$2S$=bt@_U6fLVbWmzxK{PY4~`JL7l~rT-@gGgiX%1G`JIkzb%hO6|C{upMJ7Bmd}y(%qSqxRM|7cr&*|~e`SHai{hP$_'
    'i!)b}y;cCBTLl@!XXJwD5?qK%vyM!OA0ZjN8QVw*6nd{-iOtKQ1}RH*Te+A?+?cAKY^y0{<jXkJD3St2FKBwCKe_VmgQ?OXEEG@|'
    'GovHxhr(4PQeEBetYMMP9;T{55dEI{_;o;vsq}a%5OY7ib2TJ~7J-2<qqkKbgk-pYfhrHkNSf!Sn8Z`J9>p*eD36wJ`HJy>rBEwG'
    '!T-lXtsJI%NSv(~SA`R)Dze<)>cy6Mf*nOFxn$?xU0i%T4o?5?|HBbsb&{-BY<V4v?do#_-yKu+ajCic{341RBz3`k3by5EmDRMR'
    'r4p$zVHTl-5B5b^-3%Dt3jqRVj{w5u(FLh{`0MD^KaxSXR{VKuu!#8v!>^TuE*Qj!@j-Gsbrb*j0v4OEU{9`Vu5z-Rbx~d(A?yB$'
    'yRQ$3Kf4&qf$>$U;Y#K&H4N?skqV!uK=X?r$a&=5Fqv_x7vBTQ7u(_zLhlOO@iJ2m_K5N1d}sGPl;s+EdaVRc-x1oCN(KHUiAHQo'
    'lA;C3*(<QwWR0fGzPy`OjoHB*%%k6mom8Zm`@#{!efjaji?gHiSI&spL(0|zlYvdU1X$mW7ey(plSM-rfXHWJmUH5eq~>y&{rSj@'
    '_iPc_D|_)$?T{<S&J}$p?=CM-P&bum@WL54Us=rpS=WtWb&44@<9-{3d80`FH5Kmo&oojv<kG!U%?w=q3U*|^dG{bO+3=^M;t^?I'
    'Xz<mU$Ng~5f?)nuNN1gz=4NlvSY4aef^Chb?!T-Nk!!`H2?rFy@%IVFuMvtW5bFYz_X$PM5wADJmVEJWGdsR`tcp6d&DF9sp7~@U'
    'K9IxU7rg@3ARE!#Z;jyl>dmm;6NR_h>!ij{@Be-n)cfjnK<mBrUNZ=dmK^qeH{!B4jXuh0Z|>nOdF(m1*btkyfpm?mAy|t;vxvWV'
    'UF*W|lUUyG<(=U8Ka!OC#06=+h5V)1u-_gT0x;P*hYlXLIQLa2Cvob9gz;N<u?^fysIH^2SOlx&KntLD>x*+Ni?hWiC2nj^8jCH?'
    'T$nFsoE^O>(`;{T)j1!kPD@?0`-6gH#sAO2i;xQuxtCY)fiDmVvN;7L0g4;G=dIha8r%n)#8HIQa;ef_uaC%Jpb9cPTHNn;H8Z$M'
    'W0`?`etu`R2jCd}?wLYFtRGwgE6#<;g(ks6=jU|~9(0G*1}?P6hepq`5yM|Re+gL2(iBH93G#VDO5MNr2U7OYnkyH5;pusyPw?SB'
    'zv%~cgc>!~vvltDkud}G&>eDSnIehB|I+^Lk>0X<4_1xig;$VHfSxQUn|I(l+%tCXacAuBdAi(@8C$7(Qs9wLfYHW<RLOqe@EqIA'
    'XaW}ani`>rQIS))$)Z3Tk}JbiO_0y-l=QUq&)1wVcNPxD?Xf3JEcx@}_lR7c-*dDoeKJDKB8dO5;IIGfztjK!H^T?l9xC>nX=rtw'
    'ujw`W3QS&wIjFUsqsy}M@d1a-g<Cq>H}~q!QQ0hi{0X|}gw&WV(PEvcj^Fg;+{Fj2&ge_AsQ-dess7BEL6y(VdYN?jx5}cQGzV7;'
    'rB01vn5jpTz9}jMX`m!qcUns0|Ei;McB+=G7`E?^-@kbDiLsjrdr$+`jL&)Cu$0$3nisbAkH^O!OcBV3&@JaBSj!qq^Mf(){_{h|'
    '-KA?()t#YxwD`xJA&XzXxq>=xRC(Mo%2#SJfR0rAE7ZamvxSI=C7J0)iG4^p{5E)DVE`uV&jq2vTXkg4rI7o@AK!3-Q}$E}bn6(3'
    'k|q9?JxxdQpf1NG$_{@i`4(fYq=q*(`#)%VWl!Sg!*-|tL;U?t$NzqE*lzcK*o?pLw#}>Gw|BR`Yj<1zgL%9->~&h(lahy02i4@O'
    '^hRJzm|Xx&*ZaHAUxHr09sJ?$^LDrQCAjPE^tUHZb`F~DF@5^H-QJ~tQOjR`{f5-3DZpg&1l}~h1^61!zB}HVFZL?|Y0?kfU%z?s'
    'e8V3NuZTZ_?e?DZ@k6)sC3uN1+I{(EyZ@zuQS6&1+Vm`c(`lP;T6_G`5ABYAvnMYVU-aAZj@!>a74x|RL4A4Dj5?2<QP+$`2e;QU'
    'W9i7?_IhUg{jQ9z_(E5qyJNoT=`wVSN$WRmN8Xgo=`j1Yo#1+cd__MtyPdC?tfN@*JqlL98M>-Ex5ZC=a}|7^P3Mel%Jap+lP9;g'
    'x6RvbGfA(WbXu*}6LEQ(?shvZgdX{RT>9AG!ABs1UnHODbBnB5dL-cQpFiX4i|>6k#anyMnhdVKU`Efbf=8@{N9)g@>Af;TwAtn6'
    'hj_iS*F#VEtG&;SKlosKXOAB&=w-JP(9dso`mOi$M$qm5vES_%+c64Jt}zYKOfP7+`0XcG&!6Ffwnb+8>f640JAE_#4lhi~BWPDC'
    '9*aSe5Zn5Nn=A%J6h@4p|A%gWFX-*Hf}M5?pC3gy{qp)@z_i(gxOm9kh-X|odq%@?$d7cndpYZFm8Ev~e%K_|*>3F@yt7NpbEmtr'
    '^>lUEZSl`LyY|=J_SSd3erwBbC`}JH+l_X!*XV5h5`WkI&HtG%;wspyO9RAU&A#06VFV4_r7n#X>sZj`U9(LikH710ecx;!G&|!j'
    '<-@p`#D|-9PWxNiot=N92eESgp5GZBf`!`>((@0_u01%rZF6w;@25WZP}fo5!yWYYybe4bTGPoIiRc~JZcsk$)OFC^`(wYo^S<5f'
    '2GsrAoz~9RblmAF8_S9AGgSM62FUknY~B%Bd<oD8HM~{jTs70)@79oFWytN_y>P!9(EnQc-}c^4*zcKd+Chut>rO3?!S-G~Fh57='
    'xa@hCJur48`<-CFeM0>N?e>1qX?Fr*Pu(_sY;|k4ym+zS>e8z3p7i&KoprjwPLJN(-K}F(S7m1PtyBL;6<i6zx$!&2bt58Yc~pr%'
    '?bT_1pAS3z9<;k&_q$HF1*X*LcSPO$Zny6ocy8O_G9LS{vKjui(*+ahZhhbXV&p&@`(8&m7z5PGU8pLg7E(J~>of{yhxS@7XZknI'
    'c-9_;juGOm-ec6<>REiS<@QehD_d^&xn*C-b9*A>d#ysq@0iW)cJCJ}&331BFlf7pRkZ%lCK=z`ZPTHkfA94E(C_clXDs#}e*azC'
    'a@`De_DhSyGiX^g#bY77agXR|=Yfv8rla<*U8<elLrcZOx1x%VAIU0jt68a%PDJU#Uk~lUUWH_O=u6w#ZyA!=d!U`&D(UT6`snm_'
    'O*{Pu+UfVp%o6;y(>vK|6Fuxd&REzlz5?1}7%rH#EaAcM8sBM=u;}cc>~#9n_|D(lxI2^HUP;&VqJ;4<F>VDDM^r}q>o@rCxzv6P'
    'gKlSg5r2-R!A}hM&I0791)DG4f7p)a+wWeUZQ<(c(KH@#c4t#wSIt&5SE+3$U)=_W!G!+bRl^<wO0Nb)QJ-)8xTyi`Ef>>hbFe}<'
    '1D;}fP#<niQHyi2x$*7BmW>F`uN#A_275)2-9FDbv50yoVTgE6zI0j@(rL2YZt(xy0pXd?#WS~M1$*?lF<Kpx8QO358!P^o{{Zjk'
    ';o!>u_90hI;j%daYFZF3@w{1m0;uZ4&CSv0A39s#x0-wXA2vs;AKLi4PrCE>ohR+qZtz2}X}{j<Z`;T9kzOZw7PPC4$DAKBKG0bJ'
    '8(a5GILJ0PKmV}W+9vt^jEn>x@cy&U&pQ1Bc~$nse><8!WCb~Wj6Q!)gC4EEAFZCX>ExgXn#MLyfalDAJ#V*L2ltP5^YeB`-&$?&'
    ';*V$dk1~sDhLm;=ogvkBwA*@?cAk+PdEbC|5jy;2XZN0AXq!xno83ldZ;O{;@7bzY<VpuZ@XhEmuCUnL{GK2C<=|ku{ad3$d#~qW'
    '6b}yNyf$$az~;uYcX9mo?K}GCyLTInUaN82n0()9v>V+{qt)nrfBXG}{>}e2XAs$~ht$vyd}=qP=PmuTxq16Tx4re`NtdXu_x;4z'
    'mHe*XzJ0qv4U@6C^@IP*3;GX6wSnPq?>r!c)wuhuMyIp&1OHhtJ}$os^)6XT8N!*VtCU4r_0NMp@Ds$V<liWUte^y`b+(BjS)7h+'
    '7mprx>OU16PG8`<RvBOkqv*5CK4>@B0VCYS@w=DSw!BtKaENs<2p9gK&6K-bi-0g5U~Xfh>hO~GesN(AD8J8`4qIC>4eq{Zumyhc'
    'L!Hv-mks`$ZT!~2OU<h&-;}R5%pxlvcV1yq_FvJ5>`TCVdT%UN-t+v0c{oh-!{R4gfVYLU<-fR`Jf_2S!Kx^g{(aDtdO!;8L;tbZ'
    '6Mxl-jt@VOG68}v`lSza%!xL$%_^qlbv%uZ`A2Ddyn#wRnHEAsqT4N(TE3%JzBv6fXV;@RMWhV4MN^Z_h(!)-eBzs;ZP7EQYm?|-'
    'P88PC3rG_-(pd_yT|o>ufG1h)8hDcvRWSjT>Ynu6fH>Cb30~N0@=QM=_j6N6_`}Apzs@%r(R`QyOn11!l^HC^Cz>q)%0AqDdwhQU'
    'WW#*UHlFZko@|)n0UKLQR6v!s*R&=V)X@kVd}0ik?3ayqr$25qHeS4;e_WiszNCL0y?l9mdPxLZQq{acnLjMdY~${3;|K2Hhm9{^'
    'Hl!QvoL9jeuCo@Vp>@k3@0Rhpej9$|3Z(zN8T-0sYg9LV#dsbra2YC+Qnh5Z)~w{KkIZeWa*Hu>`X%Yc)0K0h-(oqKYLY{y%G1?!'
    'wU}gDU0DC)6&dzI8STBG*MHgW2c3Pg0t0;93)(v`d;38b>U%(c@H6*^Q)r&+!b6@ZO3l6Obhzmby6o))Y}Y^3Qm5+2*=RWPbBo4$'
    '^Xt-VdPmeH{f~WEm|w4Z)FGo-y<7o5<IYdUP&VOu#`0?KsNv<>fwH@0$69YU=-=$jw!7Qi$<E{ES(;f<YP95c?pjN*YrPwt-@Qo>'
    'wA}9A<J_=Qubqvv8nn)PH=TVfM`!=0-I?udw>$WEkN@cG-_yz3!QW$)nuS!U3?uJw{1t91-!rw-3*b^H`K8#)VBJ#uNgNT~s(<QE'
    '&ZcToU(}3s8IV(K#pgZv_I^h0H$eZe4Tz3fvXBku(zi)=f8wh1_b?7zEO*6uI#Qrs%G!ofQV&`lD+hp<)8C2_;R38$i-RHOCU4tT'
    'XJZ(Mo5sckNg&LMD)yB#zPWLNyU{o$ZV-h);ALD1`lrZTXF86#uv^GA-FS#RmUFK!=mte`D=Ac4x_i2GzkBIW^0nO=50~@eW4=Q`'
    'OPw=jEY2(toNr<PUVOxt4Y+HAiKI^H6XS+fye80Oa_=@${JgdK;(~R#wkqFUp?PtK#m;&PyiiN8)e~LBqqR+ErhjAcrwzBM-%|*x'
    'S_f)vlW9W4nt2V*6V|u<w}=BcrI-|*w5G6<*VzL_mYz6Ome#%ZsESKZ{E|yvTTTHbE!|_FMYPXjVSI`w>Tzlxa$#SeeLOYkCH_Jf'
    'jFys3fzr}KTA(3;KY63DK%ys%MRHG+rO*OLB!z^$QafN|TlaG^+0JJEIrph^yzy;t$J_LUTKPx^bvwk}Ne99A^!Zhsg-9qpxQ|tS'
    '8+=IP8z^0T0X!~WkH@$iCD8kVmvZ$fA68p=Uvw>mf=O8iYmbb|rTmL4d5Hz?DDsC!oo9Zl2?>sY*W_<DttMG@i*N(Qi^iDL7lmTk'
    ';BXs<EvQd$^&#l1`a3k&YA-UqPng%IArVr32t%6P0Wg(l{ZklATkMuB+^+H58e|J<`Dy_c&^$`7_-^SB_>{U8*$zK_B98LulQDdo'
    '#0*KRmd7_Ywvo-ZSmqlIQ<jj;vIcHZINU&)1ybbm6<?`tZpo1n`ANFkSlcM?$3{ah={kfzqj?>z$e7fYC7~gln%jq>EWQ$q;s}=o'
    '8>3)-54;WAV#zl6e8VhW_q6Wzqo2nXKKfzg#n(SePi2RTChrkmq4^iijKjO@gBzamb>oK3UeL49FrIBXbZE#~e(-3!QT7inR`OIq'
    'p`b<i&JyKTlW!;8WLx>hC=+lSeKBV&TTb&s>+a&$g;pB;w;VZ4#4HSH1^MQmGGe5o<!q5{N)yBsvSmus&xUb)_&Ovbyb*J0;KPoP'
    'HjUuZCkT~KpU7hW^a(`%>67u>3d#RE|EBScwUwV(HOUHrZw|gWz?D&V+q4(g2X}X50e|`O6kETDQu_Sj4S$51PM=^D^Jh_}=^L?+'
    '`8#mVgKv9#{heM!AED`rM|67@f8K=i2C;yfFx}+Nw#c;kuE7ytacykT8h(E_NIs)@3bDh3L4qqlsol?Cz>e?ebSBg3_8^*&<Vn(l'
    'Y(^uWd_li=Gg{qve$aY~i!85Lw?2@rcqUs<c_ar#?@z}l0mfPDtAis1)f;c4=}m+LltxB_+9s9|kDqSeMgvlFw)t`C5o5!}zu`2-'
    't-oJF2^by3^9j9@Kjo5EqiC4OX*__H@FhIp%SyKOVuw3T2R`U7J_lK%-n~t;vRhB}_w8gnCS~QIxA^=eo?X#AKa0+B&~CN9dpe3U'
    '+S}CuS7-UsL@C0%1xlZy-*7+;FZ1ZB4YMEcUm%8`H@DmU)^}U(dfnn4_ooZF{*l^We17^DIimDI8kb4j6%F#-nneL|cYwVeG@&~a'
    'F7w2;-3t26o$t(hd9t_@+vK3ly_#7e%k?R(^3{Bs&)or*CQ6^;_KtXr3ahL_9dKzTqKo`Cisnx(*&vVdpj}#DEb7+Nt8j79!J0OU'
    '!sK@@MZAf~%8J9r#w9LSB8ht&oF^oKHyT0~{Oqj^dXP*<@&&5?9CZ3L1!gtrHb#aCZ#P@Lel&Y<W*Aqy<ByBe9q!DV$Yy%VUMBy|'
    '3f(i2yHu|SL07s<vwtcZ#eeFmrKDjkvjZXxcShY}M6_9`;CT0#nRIrj;i8##*L>84+iA5*%?9C}#!(NNJAF$pw4y=lDbpt}X+(4f'
    'YOB0`FoCVqD1ZHnd*#G$wu|-yw1OoxU1-+foim+Qb)TE<UD{=40L2;MyFP}*D!lCg+uFKkPDpaNo5e`nm&Njq29p8)v2EBpYP&9H'
    '^X#BKPJ?!{)gPzp_GS0GVr6-0gB^$FOv$yo%G~y7Zl(EG&Vf5c!^_sKhdb3^(stIC%!S!vv$wbS+~_xVZ*Cj=L_0puHYZfhWA(i4'
    ';=C~nHN1t+pf}z*E~uP7EjZTBzQeFUyg|zw;-ZPdi7pB3fdsrhcKc3)JuGi^*S|E2DvSO>vZtnI=VV+U>Vqzt#S6@H4_va5k`=bq'
    'c+SJ)#_wmF=(@}Er%sfE@6(AW1OiPq;2Gb?Yea~YPI-w5_+ynbdq*lg&GJC1)8Y2S&33cX-}0YD6+Z6_?l_#uRFb^ApXEH_(3?4%'
    'XB<gkOH1BW53|#6yN)+>?&A&4_V(#C{(~SmsLM*v!Qig$lxYL05Mrk^WYS^ptoVIu)g`Mekmb*5C)Le`?zdHv551l50{kCm1mubx'
    '9K)cU#G?_*VAA3y;fTJ$NSJJh&D^UF?v%8_(&z)IKaT37C$6^#noS0OBI61L_YU}OULxYp+XLKzw~hO#4`!rN$BXHz(r8gJvqo>y'
    '-S2dGGf4x6%JB3d39v)EyiN;sm8+oLFZKu(0`GK<K?3z^%VSg<+l2^CkG<T_0UnyzzG43kzc=I8G&W0O;H0$S`+Jz8SLpMOPXP0`'
    'g0oo;+;=!|3l~@>L9btFBbapV*2{t#9$%I$P<a|Xk}F`)TQ$<7UzHy1t{GTcMT0-4#a&4fJiV7gIGfK^%I+Q^+S6zeh52T;K{8&H'
    '*!EtjndhOaG<5cM>-e=CX|q>YjG(huR=ioh*o*xRWDH7z4(&N-Rtya}M3%(`%}&-(!sP|Q7o{Pq2&lJHSn|6K98|S4Zij_K!~16N'
    'puX0QX4OV&`Rh8;m)9oUhbWQ<(Jd=YN}v@|t076ENTZwV^67G!yo_Su&bL=lPIhWY(jK-}fWdt!t)C;7a2n0eTnY5<(ME?MwH?R-'
    'qR-9!?;33DIsI>UzYF#{kE6mG^{B#DyrEXNRnEWz<k2apLz*edpgwB5mD{upx9M0dmVNUFaZV#1It*~H)vD}Tr&B`>U56TauBIwA'
    'TEn~hWrglbNmDARJr0YKg7gndD6`SM4pV5q^EaFGWiF?s{-yffqc)+_sl2^tlv*pPm7U5a^y}1kuZ{5T9;bkNRNc}lR$%Ulz})E;'
    'w)lNwzOF4Zf?^8mSeEw|&)st*J$(%Od-{-h*e)bFW(9uLuU`af`~6;V-h()YnYh=f7w5aeJnbpltDdsfo@GU~V_e*?@b5a7qs+F_'
    '3}pIaq&)FQ8tP_?rF_uEs_`jc>(tQ8Zch}fnk7Z6rdrZ-qnJIS-(6^o)TdaXoyQTP9Z*LIxVvW;!o1gUj5IBEv|hkIbe4D5%=cl9'
    'P~>lKjr^_p>k0<T0GxFlKR_2d6++wVuO&3uIh19%dxXxWyfllZ;{z^6?%I%@);hxA;#l`<IrsQ?>Q4PV{VX2b6;}>A`&?CCdUoA}'
    ')b8o^K}Pr$jz6yuQ;oN#Q}3;Lw4@Y2Q?Rq%rQ?ktSloGrKKs?{-7Efkj}T8LIPW;|cUz7@*6!a-0?(1(YnA+4vT~-OTDe+Bb#-o3'
    'r<va`A9h;x&UmkRPix+-YR%50VcD}L0`p;ySm|i`UbV7c0h{>i{6Ea1Q5<f%As?8>TX!Xwv>A~bi(&8aJ^o?k@~+13Ia*AVU~df@'
    'xx?GM`|CUDfTq9HO=P#{&V%DdPH3nuFvL{n7`APuOZVLI*%3DAA0vOM%Ml0HrNpY{?%H!$1c@q9k^7gsFn^eF$;$Wrx7Yf=+a1zt'
    'AnmvA-Kbux&PVA|UBAw$D6WUKBfrnJ&~|z(yMK0SIkc<rT0i!Bozxk8ueXj2A6)Zpf4#6M=}7gBu_<E?OuO}f{!!6V)N;CyRLkb='
    'mm1^5JLG(^`va${j!O6xdA`zl9>(+gyrS&)WL3b(%9h8g_G+x=7IcCyCGde_1?!*(w+Mt6*n?pjg|h;CFqkg0i3>i+!mFqbda$$8'
    '-|vkdf*zo=t)RXCuYo<_nfMM7?*88@_y8+gfgW`K1)vAL`=JM{jogDb@Gehu2i9-9vX!)|?|f%+@v2;{c=xa6QQv>8E?wtla4%@Q'
    '`+eTA@;H4h)fj4}>EHT_s)UNg7vtRm`8BSvu5pF!ud&o=393QyvPY~mfFQoBo+#%WmB1M)ScJ9hl~htW1CDJXI;Fo0RS3kI1!hsd'
    'Q}oI9z+R1tQEuJ0VcL%(pVn7l59<0f_=)N-B?v{8rIi^E*G9*-$uIV!VJo{X8L|HKcx=PoICYi5ey>$=R@Bn6-y!1_t;(_s?Qr)y'
    'hC-B2`NPM|5$W}mP;||CVRv6`XZK6If$6l=s;4&<5zESE`RnjEyWe1yH2O^(Ypmi{)w8zNBgeeCE3P9^s4F}4{1KkF8V`$+34QT8'
    ')?EeSsmHytr<$$%R^_PHa94*L3HqX<2*?p}?LpuE>-zRzz3;YklgI<I%VXZ=p`EYkhwmJ@s|5UNMPtigL+;zE{rU)t2Ymp4F4&hA'
    '1={Y8qO0=h)w@jYst|?>8lk)$tWw&bq8yY*@C)s64HAL>2HhF1^p(hj+OGIOSJf&Ra=*~ZnS9sjpLUn9iS3<7U>G>=Rl08F&bO$('
    'Mh{}ksbA|Tt8`QG89j<U)(zPA>vZdpSfx8$zCH^7_W*5FhC$Nbi=-hsAN2MdoTiXmZHJE#U5@bVvM0rf+!s_Nk^0KeG+MvrRMow}'
    'w{UF_C-Jnf|Cxkabx%)2`>;3Lx`&@v<GO|Zw#L`F4z*Kl{`bR7*gwAp1YC;s?^?HZ$BF8fhf;~`R~c<d2)faWPQR|r!Ch^*&I$JW'
    'm(r};avx1v*j&4i3frCUg1!EIVPN8gkKiBumS=bHfP(vW|7(=1U3d4jZQXp`+W;=8C$wFi;34FxquDU{tyO8-g~|8!TMvlM8X(7B'
    'xyc6u{*K?_p0G$sU4Uv;hfucmH~cpa1H9jW?1`G!uV`8iZ+@rsfbhUbz6ulI>6-lZqETw?f!IY!fZ(0ykBGq66|=9w#96aM7HzNp'
    'wHA)sz7w{Pc*R4er60iUdECQm_yO=h?QyJA0Ux(c#!@k7Qr+aFS2lJK{Rf!u2@H-0&*-j)2iWhIf!{v+^TzP7IZ}D?v8HWj-^BX&'
    'yjZ_@UiMl(6OR^;X_v7VHmcuxWK_Qt!Qb_~YA6m}9ttjtkiC&uZUE3zX&de_U(rOF<93DPKFn~-q58_;zCK95@5Ja!o2dc%O7Q(5'
    ';mGW-+p8fDHzxmkMAv-_>vys6wg_4QEpXpoU}x#fy%El+cI*9R-s-tnJXYPRCy8W!O)S0dkXff7`iFJw8jt5X2b(j3+7*AC<7F+&'
    'ETZ!DT|PoWe0>;R!nkXr?ydSQt3`5@WA5fKB9{9Y&F8+b`a>$~?+LU&<XP!gQ_#vNnVL}A{+@)=Jpbgq;q?1li>wwiXr<rx^}%Z7'
    'w_mHN*F+b~BF5(L+#_CChpr9Ccl`NEV8xHgmm()#2(ZRGZfyRCT-&W`IKfvrOO_Sv;X1JI<F;yz4@sR|EzdCSwJMH7*8_CVWB%^%'
    'J-Fw){+`3_<`Sv5z{VR>ioccp7>`&1YeY95Fxksd|AI&FL$_#^-4d<e>GP;s{&hCLcNU;!RLoRgANAZ;d*7|I^R&Ia8Y^=RFLFaV'
    'y|Ov6Zht(r->L>B60v9cL3Bf}<-f^VVf|~}y$X(@PWw_GvtOt3Lu%V|y#|EPsd7$x%p5{$J$$kR^HVrf5&Nx0FI3Gop90nx<7%<p'
    'v$qGbFJ&l$t?^U`W`Hv2fEoDN0?a^zi>5A^VHRhlItt)z2j7lc<KB4ZAut2p{?`IC@JxI#1BUu<2Fy^lhxt;EGMJ(NFI7jOsFYB}'
    'HOQm})6n5Y4`Li}W1(EF_!uj%!<vPM952D;ZYGYw+x8Sn(N@tRTQ-(q!VvDZ{%%fZyPz47#`Wqc7-#FLH^MbUCxg4CQE)AU#{$L6'
    'p4N4FeicK6)x;W`qC)#-)vn^H?}lXBdn6{IyDOw1%P+va`-5hjW9s(De87fN+iW@YYOLB)H#PoKz6r-ZRmC~fZ!Nnl+*zoeXQ`c?'
    '5Kc-#Ddy%T5mx6_PRuF8&DeYE_w2(J8l_*?MKG8<*CrdvhOXUzT2IwI?oA@vTf1qF&mAqIe9v8xh~M%cP4Y;dB-25d-u<31+}EI<'
    'x{_$pDZ4)_TeCi_g5eGm>JzoFNH<+WaOH{@{hhC=cwrQqUj5Ov$W(#bi<xD56@}fhaQQ)Q3cY(wR`i;q?^*SxufGr4VyD@H!*dOY'
    'YNw|5g^dSwBo|-G->{U4MlOi1*Y^>g^(ibBQjoSnxy`hOXA}Sm>*`rs<bqiuXIR@NYrI8!E{q;8blSDa&XuF9n#?_AB8n}O-tVbV'
    '(eCTix%9;SC##m7)zz9ndr3No^BQ!+y?_j7_9)d5PPeb{Z`54V;<;fSkivrhH(aLIaF-_7WqfA2B#<+%G6o_<Nwa*L^)!gueiiso'
    'tuR!ALXcWYTuPTcB||Vt=d|cmJ*==Y>k!HN>&o)1A=!Cy`}eK9(A)Vv_=x_x5SNbe`6#||PU()g9rQ;{eP>2nWU>2e@-UOCWo|_u'
    'k4>@b|Be*9cCR?_=*xH5%eko(+VMlA#Y%;DH3-tbEh9`8tQsEuQmpw`K}S4IeXEdMrC8~H%j*JB-ZeUlb;;O#BCiZY>vvXnaOvB{'
    'h?MF%G`w;T-iVE^wN9s6U-ZFg=CS1!I{US-i*COZVyvyY&?(^&C6}%k!@Y2#IuhOKSF0;HM^vKKCH-&RF|7~Q8f-FJ{n`|LfpG=>'
    '*4KsO*Hx|SSD=ONu&S0u)pxLNQ`>u`wrZGz_j_1li`BsxRM1rYar;hA=HsHJUL?8N^7DE_s~QULR7$K>8~fYS<@Z>F>_da>t*L*r'
    'SJfc*{qs>Xu&?FX0*v>H|M;yw-T~q#&3D*zV6p1P6n9#7U+em*B!qocc8H+2y8G4q_fEMx#L6Eg2DbA3!(Th<zcKaQNZ`HdruxfL'
    'yS)#mx?9iiy6s&XP=5^a7zrgoXYan2gGU~|qQI5WneJ)x>k`|`Wq8U!B<_aY2<+gxPX=^rtk8D96xOusF()qjurcOp9$LNPQE~U8'
    'k7``I#>jU9+p6@{1+t%(!rtY;_9M7x4HI1(*KP@{@2g|m_a23+^Ktj#*mgNZ{PC8o8}fck9yw=EZ{4{*<~43*2KIZrwa!u8(fGFG'
    'yeb@4z3&|N4yTQ~u9vlW&j54*{N}2G4~5`sM2B%U)Q7$ID(g^*1em!N&TCZGf9l4lzCQTrgB1GT)j7CrzFNs?+o<>){Q>}<@3y4o'
    'r^#&{1L&0!)cW_ha`!6f1GT%}FS#k*v~S6=_wfT|A7OP)kIb=Gz+_<_SE;O!|KekDl7(8XRb596VqZQO5AOS>;XToK*SK>{wpQQQ'
    'dcQJ*e64QVZ>^K_4~?=`YL^WhiIwuLdAJd6vHIrVn{WT&$udiy4C48dXnqqcR{12EcYmGBg|%nnF&0s;tk_0KHTd(A8pv0{a1sr#'
    'vu5xyi?ZMYzvo|hJO6dgSKF8lGjlCQG?L3N_@0{L;&i=2F>7$;e#9QP7iluUy*JT#91p|cs`2aml%|9`KJ(~GB99GR0CX8m@p<+H'
    'f6Q_XS|n-SG*kI?uJ`Uv!fZl=EI#M6>92FXAP0ZS-3F<-rT6XS`xCi?LZ889RG6dwj*A9uQ)y)X#8zRF`quy3+0{0;Z6o2of{v#{'
    '(&5pRV!3yksyWR?Z8MWLH@4?KoTO?fiMH9uvPw#hQpf+j`|N@cNP@OgkK>SdSpbX0zLC<iC&K9#AZ)sRMAM`Q?UIVXC~j0j6O?U+'
    '=a=vP^L`YT7qj8}%hCC-!^_b{$cUPu`uW2zquJ=~yUP#f?}qO~Ln5re0_r;;t6;G64<9bofT!-y1g~QTXg*Sf_o*L5@~~&J9$s9G'
    'E@!_Ee;Hi>)X9b(4AlYphpr7|9$hye@S0E|6_BY=RY0rg)&g#M6r>P_s8Mh476MUm*pw1E1W+Qg8L)n4Gar7c4F*{3Hfc`lG7V^~'
    '`!wIq05_DUR~6t!?mz@0{t9SXcL|1UD!`~+zDS*w+0t3OO|ISL00}}(T&uY0I12SMGe->oY=M^L8iOH@9OZPV7aw)Sfr~eEC`lk#'
    'fzhm)nW3U9Kw@Wk1rjycZgWhYaXzHhvF<3@Y=Evy*Hu_nDqyf)FTt*Z-(DSX^{^8q6&_PCNC6>)o?g&GH@jtd66hF~O@4Wf%Xkaj'
    '<CzV1j9KK1#*jcfK@%C2S`;adCeJ5Wz~Ru!U42BLL+idgi~~uzvcr`*jq!I{UA>nry*6s4h*pW9M~#TJV*6>W7pTENF_x+4B3%mT'
    'tAP!ct+xa{Z#vF?B<-zT_=q@r>BH076N2yTh>8jeEI=YQYcnV`AFAF)L^d!*z$4W96W2itFf!^Qz`$sPyyTXT`oo3`1tL~4R2{W5'
    '@JJf2h7=yDsIt>Q*~<6}(U9(;VtiQ(UfCecGG?s$hWKFV?Z;5*WijEPG8W*Pq!<HsG*gq+YG%}wjSLUN(VV`m9)v8~MOndy#urd-'
    'f!CAb;`1#IxF3W{3}&r+tiG4Fa6(9n7uy*;MZg4i{u$5WIIef3g-eGWxea?31zCMv7WkCYs<`z5nzoAdW#Fw~a2U(FG(*k?(N&r*'
    'eIe~`z~A{+@2nRq{i4;~C$?Cug$n?P`E?*YufZ>ijMs$O6O3kAF}6TYrrg;<SpdUBoPC0L*)w5CrX3)o5MYRI=rD0el5R%YhAU7+'
    'deJTpo*%?myn*s#v$1@9u&u@i5h&!&QxqX{4^CSE?Tr8Bu_&(6+j+|9l=tLEvx}1Kmf4;67{T$(bq><EIPu)bx@oD!=@_DUST7G+'
    'wo`)%*7nddD1(QJC#Av-p!j!sTYzj80!k|e#~!(8^YrOVvFE*86VYUo`Z=B5G|3k?eqJu!kB;92X1SprEr^hW+4!Bn%{U01;4`Wp'
    'R3~Pp$&eap^q}0FD>t>qhhbuF{%AzQBOHb*Pk65~AlNqRzK&lE=uBZ<x)sgK!XuvQtMb;kFAi6Nts}ZuRLfDrE2*tb`iwjMsWmJe'
    'VI#)UAaE1G!>Vk(OPjS7^2RbWXGp#tV0Lj3aZ&Kq$qD{aWSQ{o@5y~4GTA5ZER>10&dWNQwzN&?=ZpWQ|J#?7U^0p5_YFqTWS(E{'
    '9JsWDas?a2U#uy>;&D8+OWtsabBmY?JCnT5*4=4mEWfC)2I8umFu`a=QCYU}L9dk`+^=S=rA&fCF%<A0p5jEip6<7f{54Rl?fNQR'
    'xr{#|)7r>X^isp$Dk=~3J0AYy|Fh|<$>foKX}5^(lZN@<65D&F0>V5>xwonB^3`Ng98V^`5DiiL?kUoCZ^@=s2m~)<6+-YDtMKwX'
    '@yg0rL`YXan%39;frWw+-J*#>1covqEvmH+LsUOwHn|&sm`N4;UUYKu(2lqLsBQZTSBl(2eWl5#icshkwVD=cFNP%+(?a*-{@E1t'
    'rRz8j<FF(DrZ1cq(jJW+z-jnOdDU4I?V(j*Zf#f1Gk~{ztfZGcQ;kil(`Hd|lXQD${@nAT-|0j)_rDSw6eR294p&12`iXAR{W7CC'
    'g}rDi`l92WCsfLxaUwIHQpwWJ@~n`8^{M-Pvf8D#X3VeWh){spSyqp;e)g(64OQnXAT`+S^`e;Pm$7;!FZXq*dV!^dxf@41d+N~X'
    'M*r$Uo$V2B#8FI&tS7#v@9)Xv#&}H~q&sqPe5|_BDG#w{c3#gd;+mDk?$%F^=aM%F=V<pQDP|d(G;17nJKeL8h=14Vb@6}vUAG&Q'
    'C+mhd5GvX+nx*EiFI-`!k(kMy=3M~QaSx}}PIKw0_#md&fo1q0t8c3jahaVp5gxlD9O~)-)Y=MxCPu7e2c{)paW!*7&P%A~*Kp~s'
    'XvgJir&%>}^S)EKjhyJ-bPNaTH0lxe1je-_8$8`zMzbl1$*b4%H@r8-&|i^#7~)9%nB5aYtQ2UWmf6)+DhZy&c9*Qw#s7XP?V9Ae'
    'kuPV2Xg)SDfsw@{S8ABl9g@3^U>REJL01}1gz8v$N&ZG~5dWN_!_@BukE{)P2U?s!z!CVHNrtI&THJ$&IyEt(PHbzcCQfYTyX_XI'
    'PV&`EcuRX;4xq)^i@k2R$O7WbYp+gijMk(_j$5ZDEvBuuLX+khy><jaJSd(Z(I&|r(KY6&JGN6sR4pU|p?(lh%qi6LgJvYbdv*|o'
    '*DgO3hK8nQKTasAR|KL26{qQ!;~JqO6&A{1?VhJha?Gtb%BY5f{7RaU8@VIPdlp-na3tl%=1Ir%v#cp60G@NXHSerG;o9jr4cx+x'
    'J-LzXIMpe{7R>Xyc70yC3M{o=otN&D+sz7j3@dZVPk2sDW#Q2ccL>J)PPfeU7HPVM4M|NZOQ7oYqpRpLg|bQV&u>e7bVLLNH{kMq'
    'O_N)q6vuU8va_a!0&ET=#AA)YI8)y;`}l6^?5`slQm=j%G+XF6CA$3xS0mjM?b+SO`U4*P7$9&v&D%PcTIVB++bZ4T1^a?ExNMrq'
    '?`Bl270x|Pi&z*{35gR#>uThkUpf^nb()Y4E3mcX#CglzW|b{qI1bNVdCq9VvZ0P1vPZ9;Bv01>h4+PM#lW4XNRlbMIQ%Kkwrpt^'
    'tKE_x(}LZ&Se62#$n#jkNYI9F?X~N{UGm_SWW0KFy{p!IwiO|)Y^!v!+NS$Oy4jM2UZo?9P>k~YE^kO_QP>`Okv3w4jJ&@gGoAD@'
    ')9^h#DivtX;1hhw+QAX80xs|UcX)BpSFcrhQbQ!2%D4JXpvRQPlAtO&RXATuatP)-3d*TSp3LJo?D#|4kQ-!!pec9j?2lcF&%$`d'
    '$+n>BIoxOkr+@ql(6)>W'
)
SITE_ROOT = '/var/www/telemt-web-manager'
SITE_FILES = {
    'botanical': {'light.html','watering.html','plants.html','field-notes.html'},
    'night-sky': {'tonight.html','moon.html','constellations.html','equipment.html'},
    'kitchen': {'recipes.html','pantry.html','techniques.html','seasons.html'},
}
SITE_COMMON = {'index.html','404.html','site.css','illustration.svg','favicon.svg','favicon.ico','robots.txt'}
SITE_SOURCE_FILES = {'generate.py','validate.py',*(f'templates/{theme}/site.css' for theme in SITE_FILES)}


def site_resources():
    try: raw = base64.b85decode(SITE_SOURCE_B85)
    except ValueError: raise ValueError('site resource integrity failed') from None
    require(hashlib.sha256(raw).hexdigest() == SITE_SOURCE_SHA256, 'site resource integrity failed')
    values = update_json(zlib.decompress(raw), 256*1024)
    require(type(values) is dict and set(values) == SITE_SOURCE_FILES
            and all(isinstance(v,str) and 0 < len(v.encode()) < 180000 for v in values.values()))
    return values


def site_identity(directory):
    directory = Path(directory); safe_path(directory)
    info = directory.lstat()
    # Production requires root:root; inert fixtures follow safe_path's CI EUID convention.
    group = 0 if os.geteuid() == 0 else os.getegid()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid() and info.st_gid == group
            and stat.S_IMODE(info.st_mode) == 0o755, 'unsafe site directory')
    names = set()
    with os.scandir(directory) as entries:
        for entry in entries:
            names.add(entry.name); require(len(names) <= 11, 'extra site files')
    require(any(names == SITE_COMMON | articles for articles in SITE_FILES.values()), 'unknown site files')
    rows = []
    for name in sorted(names):
        require((directory/name).lstat().st_gid == group, 'unsafe site file group')
        raw = web_link_read(directory/name, {0o644}, 180000, owner=os.geteuid())
        require(raw, 'empty site file')
        rows.append((name, hashlib.sha256(raw).hexdigest()))
    return hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest()


def site_generate(destination, theme=None):
    """Run the verbatim approved generator once; never replace a destination."""
    destination = Path(destination); safe_path(destination)
    require(not os.path.lexists(destination) and destination.parent.is_dir())
    require(theme is None or theme in SITE_FILES)
    resources = site_resources()
    with tempfile.TemporaryDirectory(prefix='twpm-site-source-') as temporary:
        root = Path(temporary)
        for name, source in resources.items():
            path = root/name; path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(source.encode())
        generator = types.ModuleType('generate'); generator.__file__ = str(root/'generate.py')
        validator = types.ModuleType('validate'); validator.__file__ = str(root/'validate.py')
        previous = sys.modules.get('generate')
        try:
            exec(compile(resources['generate.py'],generator.__file__,'exec',optimize=0),generator.__dict__)
            sys.modules['generate'] = generator
            exec(compile(resources['validate.py'],validator.__file__,'exec',optimize=0),validator.__dict__)
            metadata = generator.generate(destination,theme)
            validator.check_site(destination,metadata['theme'])
        except AssertionError:
            raise ValueError('generated site validation failed') from None
        finally:
            if previous is None: sys.modules.pop('generate',None)
            else: sys.modules['generate'] = previous
    for path in destination.iterdir(): path.chmod(0o644)
    destination.chmod(0o755)
    return site_identity(destination)


def site_vhost_digest(source):
    values = re.findall(r'^# TWPM original site v0\.3 sha256: ([0-9a-f]{64})$',source,re.M)
    require(len(values) <= 1, 'duplicate site identity')
    return values[0] if values else None


def site_vhost_port(source):
    ports = re.findall(r'^    listen 127\.0\.0\.1:(\d+);$', source, re.M)
    require(len(ports) == 1 and 18081 <= int(ports[0]) <= 18090,
            'unrecognized owned origin listener')
    return int(ports[0])


def site_bound_identity(config, data, nginx_root, directory=SITE_ROOT):
    c = read_config(config); host = managed_web_contract(c,data)[0]
    vhost = Path(nginx_root)/'conf.d/telemt-web-manager.conf'; safe_path(vhost)
    source = vhost.read_text()
    if c['web']['vhosts'][0]['decoy']['mode'] == 'static_directory':
        require(source in (render_vhost(host),render_vhost(host,keepalive=False)),
                'legacy decoy and Nginx vhost differ')
        return None
    digest = site_identity(directory)
    origin_port = decoy_origin_port(c['web']['vhosts'][0]['decoy'])
    require(source == render_vhost(host,site_digest=digest,site_port=origin_port),
            'site ownership/hash differs')
    return digest



class UpdateProgress:
    """Presentation only. Deadlines, samples and transaction authority stay in Engine."""
    def __init__(self, stream=None, language=None):
        self.stream = stream or sys.stdout
        self.language = (language if language in ('en','ru') else presentation_language()) if self.stream.isatty() else 'en'
        self.enabled = self.stream.isatty() and os.environ.get('TERM','') not in ('','dumb','unknown')
        self.color = presentation_color(self.stream)
        self.stage = None; self.line = False; self.failed = False

    def end_line(self):
        if self.line: print(file=self.stream,flush=True); self.line = False

    def event(self, stage, legacy):
        if not self.enabled and self.language != 'ru': print(legacy,file=self.stream,flush=True); return
        if self.stage == stage: return
        self.end_line(); self.stage = stage
        labels = {1:'Verifying release',2:'Compatibility check',3:'Preparing safe update',
                  4:'Stability check',5:'Restart verification'}
        if self.language == 'ru':
            labels = {1:'Проверка релиза',2:'Проверка совместимости',3:'Подготовка безопасного обновления',
                      4:'Проверка стабильности',5:'Проверка после перезапуска'}
        cyan,reset = ('\033[1;36m','\033[0m') if self.color else ('','')
        print(f'{cyan}[{stage}/5] {labels[stage]}…{reset}',file=self.stream,flush=True)

    def wait(self, deadline, start, total):
        if not self.enabled:
            remaining = deadline-time.monotonic()
            if remaining > 0: time.sleep(remaining)
            return
        while True:
            now = time.monotonic(); elapsed = min(total,max(0,int(now-start)))
            filled = min(10,int(elapsed*10/max(1,total))); bar = '█'*filled+'░'*(10-filled)
            green,reset = ('\033[32m','\033[0m') if self.color else ('','')
            waiting = 'с — Подождите…' if self.language == 'ru' else 's — Please wait…'
            print(f'\r[{self.stage}/5] {green}[{bar}]{reset} {elapsed:3d} / {total} {waiting}',
                  end='',file=self.stream,flush=True); self.line = True
            if now >= deadline: break
            time.sleep(min(1,deadline-now))

    def sample(self, sample):
        if not self.enabled:
            message = (f'Проверка на {sample} с: процесс, cgroup, маршрут и текущий журнал исправны' if self.language == 'ru'
                       else f'Acceptance sample {sample}s: process, cgroup, path and current journal OK')
            print(message,file=self.stream,flush=True)

    def finish(self, message, failed=False, russian=None):
        self.end_line()
        self.failed = self.failed or failed
        if self.enabled or self.language == 'ru':
            text = russian if self.language == 'ru' and russian is not None else message
            color,reset = (('\033[1;31m' if failed else '\033[1;32m'),'\033[0m') if self.color else ('','')
            print(color+('✗ ' if failed else '✓ ')+text+reset,file=self.stream,flush=True)

    def log(self, message, russian=None, stream=None):
        self.end_line()
        print(russian if self.language == 'ru' and russian is not None else message,
              file=stream or self.stream,flush=True)



# Universal updater. These components share the canonical, atomically installed
# helper with the older parser APIs; bootstrap continues to install one pair.
UPDATE_SCHEMA = 1
UPSTREAM_REPOSITORY = dict(id=1125007401, full_name='telemt/telemt')
UPDATE_MANAGER_VERSION = '1.3.2'
BASELINE_VERSION = '3.5.16'
BASELINE_COMMIT = '84e5b827a6619fb2e09ad3d09f253cdffe04bc2f'
BASELINE_HASHES = {
    'x86_64': ('e6f46b2f3becf29bfd555cec8a059e429f7c082c1af402499b3a7940cf8ebd34',
               '1954f18faeb9f5838e9444880f2ffb00704c6bd5b2836bc86dd64611537d49b8'),
    'aarch64': ('1e1bc87f05923b9673cbbaf34a3e50f7fdcf7d496cd24efcdb34c278ed18a659',
                'ebaec212fd5556ceca7fb0fcc4d3d23c01a8883d20a4cbc567219022d57c2a0b')}
# Only these two reviewed identities may create/adopt baseline receipts.
# Historical 3.5.12 records retain their original identifiers and hash policy.
REVIEWED_BASELINES = {
    '3.5.12': ('c4555e25f39dd5be200ccf6353f7d82bfcf89131', {
        'x86_64': ('92bfaa6177d87790bae79caea08d8ddddd0ca3ebc95545c1d62374897592c6c3',
                   '53da315a9f61975913235f72c4adb413313089b966ffcca700653b4663d3d964'),
        'aarch64': ('16bfd0e78b746171b0434c935ca953358c88b43cfb0091d7b74cb982424202a3',
                    '308271c73ece5d748aeab21680c10c2bea153ba29c83135b1b84aa79a394173c')}),
    BASELINE_VERSION: (BASELINE_COMMIT, BASELINE_HASHES)}
LEGACY_RELEASES = {
    286377748: ('2.0.0.1', '2026-02-14T13:29:46Z'),
    285764063: ('1.2.0.2', '2026-02-12T16:30:28Z'),
    278074445: ('1.1.1.0', '2026-01-19T23:20:01Z'),
    275857798: ('1.0.3.0', '2026-01-11T22:02:40Z'),
    274860393: ('1.0.2.0', '2026-01-07T15:21:06Z'),
    273844763: ('1.0.1.0', '2026-01-02T16:40:50Z'),
    273320189: ('1.0.0.0', '2025-12-30T02:32:21Z')}
UPDATE_PHASES = {'STAGING', 'PREPARED', 'OLD_STOPPED', 'SNAPSHOT_COMPLETE',
                 'CANDIDATE_ACTIVATED', 'CANDIDATE_RUNNING', 'COMMITTING', 'COMMITTED',
                 'ROLLING_BACK', 'ROLLBACK_COMPLETE', 'CRITICAL'}
UPDATE_INTENTS = {'STOP_OLD', 'MOVE_OLD_DATA', 'PUBLISH_WORKING_DATA', 'REPLACE_BINARY',
                  'REPLACE_RECEIPT', 'START_CANDIDATE', 'COMMIT', 'STOP_CANDIDATE',
                  'RESTORE_DATA', 'RESTORE_BINARY', 'RESTORE_RECEIPT', 'START_OLD',
                  'NORMALIZE_LKG', 'MIGRATE_BASELINE', 'PUBLISH_GATE'}
UPDATE_TERMINAL = {'COMMITTED', 'ROLLBACK_COMPLETE'}
UPDATE_HEX = re.compile(r'[0-9a-f]{64}\Z')
UPDATE_SHA = re.compile(r'[0-9a-f]{40}\Z')
UPDATE_ID = re.compile(r'[0-9a-f]{32}\Z')
UPDATE_CHUNK = 1024 * 1024


def update_json(raw, limit=1024 * 1024):
    require(isinstance(raw, bytes) and len(raw) <= limit, 'oversized updater metadata')
    return json.loads(raw, object_pairs_hook=journal_object, parse_constant=journal_constant)


def update_exact(value, keys):
    require(type(value) is dict and set(value) == set(keys), 'unknown updater metadata schema')


def update_digest(value, sha=False):
    require(isinstance(value, str) and (UPDATE_SHA if sha else UPDATE_HEX).fullmatch(value),
            'invalid updater digest')
    return value


def update_version(value):
    require(isinstance(value, str) and len(value) <= 128, 'invalid release version')
    numbers, pre = semver(value)
    require(not pre and '+' not in value, 'custom/prerelease requires manual review')
    return numbers


def update_timestamp(value, optional=False):
    if optional and value is None: return
    require(isinstance(value,str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',value))
    time.strptime(value,'%Y-%m-%dT%H:%M:%SZ')


def update_architecture():
    arch = platform.machine()
    require(arch in ('x86_64', 'aarch64', 'arm64'), 'unsupported updater architecture')
    return 'aarch64' if arch == 'arm64' else arch


def update_fsync(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try: os.fsync(fd)
    finally: os.close(fd)


def update_write(path, content, mode=0o600):
    """Anchored durable publication; callers never pass candidate paths."""
    path = Path(path)
    safe_path(path)
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    name = '.twm-' + uuid.uuid4().hex
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=parent)
        with os.fdopen(fd, 'wb') as output:
            os.fchmod(output.fileno(), mode)
            output.write(content); output.flush(); os.fsync(output.fileno())
        os.replace(name, path.name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        try: os.unlink(name, dir_fd=parent)
        except FileNotFoundError: pass
        os.close(parent)


def update_write_json(path, value):
    raw=json.dumps(value, sort_keys=True, separators=(',', ':')).encode() + b'\n'
    require(len(raw)<=64*UPDATE_CHUNK, 'metadata exceeds supported inventory bound')
    update_write(path,raw)


def update_read(path, limit=1024 * 1024, modes=(0o600,)):
    return web_link_read(path, set(modes), limit)


def update_hash(path, maximum=128 * UPDATE_CHUNK):
    """Stream regular files; /proc/PID/exe is opened explicitly by identity code."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= maximum)
        digest = hashlib.sha256(); size = 0
        while block := os.read(fd, UPDATE_CHUNK):
            size += len(block); require(size <= maximum); digest.update(block)
        after = os.fstat(fd)
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                and size == before.st_size, 'file changed during hash')
        return dict(sha256=digest.hexdigest(), size=size)
    finally: os.close(fd)


def update_names(directory, maximum):
    """Bound enumeration itself, before sorting/allocating an entire directory."""
    require(type(maximum) is int and maximum>=0)
    names=[]
    with os.scandir(directory) as entries:
        for entry in entries:
            require(len(names)<maximum, 'directory exceeds reviewed entry bound')
            names.append(entry.name)
    return sorted(names)


class UpdateRedirect(urllib.request.HTTPRedirectHandler):
    """Check every redirect BEFORE urllib opens its destination."""
    def redirect_request(self, request, response, code, message, headers, new_url):
        UpdateHTTP.official_url(new_url, redirect=True)
        return super().redirect_request(request, response, code, message, headers, new_url)


class UpdateHTTP:
    """Fixed official endpoints, bounded bodies, normal TLS verification."""
    @staticmethod
    def official_url(url, redirect=False):
        parsed=urllib.parse.urlsplit(url)
        require(parsed.scheme=='https' and parsed.port in (None,443)
                and not parsed.username and not parsed.password and not parsed.fragment)
        allowed=('api.github.com','github.com','release-assets.githubusercontent.com','objects.githubusercontent.com')
        require(parsed.hostname in allowed)
        if not redirect:
            require((parsed.hostname=='api.github.com' and
                    (parsed.path=='/repos/telemt/telemt' or parsed.path.startswith('/repos/telemt/telemt/')))
                    or (parsed.hostname=='github.com' and parsed.path.startswith('/telemt/telemt/releases/download/')))

    @staticmethod
    def open(request):
        UpdateHTTP.official_url(request.full_url)
        client=urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context()),UpdateRedirect())
        return client.open(request,timeout=30)

    def request(self, url, maximum):
        self.official_url(url)
        request = urllib.request.Request(url, headers={'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': f'telegram-web-proxy-manager/{UPDATE_MANAGER_VERSION}'})
        with self.open(request) as response:
            final = urllib.parse.urlsplit(response.url)
            require(final.scheme == 'https' and final.hostname in
                    ('api.github.com', 'github.com', 'release-assets.githubusercontent.com',
                     'objects.githubusercontent.com'), 'nonofficial upstream redirect')
            length = response.headers.get('Content-Length')
            require(length is None or (length.isdigit() and int(length) <= maximum))
            raw = bytearray(); deadline = time.monotonic() + 180
            while block := response.read(min(UPDATE_CHUNK, maximum + 1 - len(raw))):
                raw.extend(block)
                require(len(raw) <= maximum and time.monotonic() < deadline, 'upstream response bound')
            return bytes(raw)

    def api(self, suffix):
        return update_json(self.request('https://api.github.com/repos/telemt/telemt' + suffix, 8 * UPDATE_CHUNK),
                           8 * UPDATE_CHUNK)

    def download(self, url, path, size, digest):
        # Archive bound is 128 MiB. Metadata bodies are small; binary payload
        # streams through the same TLS client directly to an exclusive file.
        require(0 < size <= 128 * UPDATE_CHUNK)
        require(url.startswith('https://github.com/telemt/telemt/releases/download/'))
        request = urllib.request.Request(url, headers={'User-Agent': f'telegram-web-proxy-manager/{UPDATE_MANAGER_VERSION}'})
        deadline = time.monotonic() + 180
        with self.open(request) as response:
            final = urllib.parse.urlsplit(response.url)
            require(final.scheme == 'https' and final.hostname in
                    ('github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'))
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            actual = hashlib.sha256(); count = 0
            with os.fdopen(fd, 'wb') as output:
                while block := response.read(UPDATE_CHUNK):
                    count += len(block)
                    require(count <= size and time.monotonic() < deadline, 'archive download bound')
                    output.write(block); actual.update(block)
                output.flush(); os.fsync(output.fileno())
        require(count == size and actual.hexdigest() == digest, 'official asset digest mismatch')


class UpdateReleases:
    def __init__(self, http=None): self.http = http or UpdateHTTP()

    @staticmethod
    def release(item):
        require(type(item) is dict and type(item.get('id')) is int and 0<item['id']<2**63)
        require(type(item.get('draft')) is bool and type(item.get('prerelease')) is bool)
        tag = item.get('tag_name'); published = item.get('published_at')
        require(isinstance(tag, str) and len(tag) <= 128
                and (isinstance(published, str) or (item['draft'] and published is None)))
        update_timestamp(published,optional=item['draft'])
        require(isinstance(item.get('target_commitish'),str) and 0<len(item['target_commitish'])<=256)
        require(item.get('url') == f'https://api.github.com/repos/telemt/telemt/releases/{item["id"]}')
        require(item.get('html_url') == 'https://github.com/telemt/telemt/releases/tag/' + tag)
        return dict(id=item['id'], tag=tag, published_at=published,
                    draft=item['draft'], prerelease=item['prerelease'],
                    target_commitish=item.get('target_commitish'), url=item['url'], html_url=item['html_url'])

    def enumerate(self):
        repo = self.http.api('')
        require({k: repo.get(k) for k in UPSTREAM_REPOSITORY} == UPSTREAM_REPOSITORY,
                'upstream repository identity changed')
        result = []; inventory=[]; seen_ids = set(); seen_tags = set(); versions = {}; deadline=time.monotonic()+180
        for page in range(1, 101):
            items = self.http.api(f'/releases?per_page=100&page={page}')
            require(time.monotonic()<deadline, 'release inventory deadline')
            require(type(items) is list and len(items) <= 100, 'malformed release page')
            for item in items:
                record = self.release(item)
                require(record['id'] not in seen_ids and record['tag'] not in seen_tags,
                        'duplicate release identity')
                seen_ids.add(record['id']); seen_tags.add(record['tag'])
                inventory.append(record.copy())
                if record['id'] in LEGACY_RELEASES:
                    require((record['tag'], record['published_at']) == LEGACY_RELEASES[record['id']],
                            'historical quarantine identity changed')
                    require(not record['draft'] and not record['prerelease'], 'historical quarantine flags changed')
                    continue
                if record['draft'] or record['prerelease']: continue
                value = record['tag'][1:] if record['tag'].startswith('v') else record['tag']
                require(len(value) <= 128)
                _, pre = semver(value)
                if pre: continue  # A SemVer prerelease is never stable, even with a wrong GitHub flag.
                precedence = update_version(value)
                require(precedence not in versions, 'ambiguous stable release precedence')
                record['version'] = value
                versions[precedence] = record
                result.append(record)
            if len(items) < 100: break
        else: raise ValueError('release pagination exceeds reviewed bound')
        require(result, 'no stable official release')
        self.inventory=inventory
        return sorted(result, key=lambda r: update_version(r['version']))

    def latest(self):
        first = self.enumerate(); inventory=self.inventory; second = self.enumerate()
        require(first == second and inventory==self.inventory, 'release inventory drift; retry explicitly')
        return first[-1]

    def freeze(self, release, arch):
        require(arch in BASELINE_HASHES)
        raw = self.http.api('/releases/' + str(release['id']))
        identity = self.release(raw)
        require(identity == {k: v for k, v in release.items() if k != 'version'}, 'release identity drift')
        ref = self.http.api('/git/ref/tags/' + urllib.parse.quote(release['tag'], safe=''))
        require(ref.get('ref') == 'refs/tags/' + release['tag'] and ref['object']['type'] == 'tag',
                'annotated official tag required')
        tag_sha = update_digest(ref['object']['sha'], sha=True)
        tag = self.http.api('/git/tags/' + tag_sha)
        require(tag['sha'] == tag_sha and tag['tag'] == release['tag'] and tag['object']['type'] == 'commit')
        verification = tag['verification']
        require(verification.get('verified') is True and verification.get('reason') == 'valid',
                'GitHub-verified signed tag required')
        commit = update_digest(tag['object']['sha'], sha=True)
        if re.fullmatch(r'[0-9a-f]{40}', identity['target_commitish']):
            require(identity['target_commitish']==commit, 'release target differs from signed tag commit')
        assets = raw.get('assets')
        require(type(assets) is list and 0 < len(assets) <= 100)
        ids = [a['id'] for a in assets]; names = [a['name'] for a in assets]
        require(len(ids) == len(set(ids)) and len(names) == len(set(names)), 'ambiguous official assets')
        basename = 'telemt-' + arch + '-linux-gnu.tar.gz'
        def asset(name):
            entries = [a for a in assets if a['name'] == name]
            require(len(entries) == 1, 'required GNU asset missing')
            value = entries[0]
            require(type(value['id']) is int and value['id'] > 0 and type(value['size']) is int
                    and 0 < value['size'] <= (512 if name.endswith('.sha256') else 128 * UPDATE_CHUNK))
            url = 'https://github.com/telemt/telemt/releases/download/' + release['tag'] + '/' + name
            require(value['browser_download_url'] == url and value['state'] == 'uploaded')
            require(value['url'] == f'https://api.github.com/repos/telemt/telemt/releases/assets/{value["id"]}')
            digest = value.get('digest')
            require(isinstance(digest, str) and digest.startswith('sha256:'))
            return dict(id=value['id'], name=name, size=value['size'], url=url,
                        api_url=value['url'], sha256=update_digest(digest[7:]))
        return dict(repository=UPSTREAM_REPOSITORY, architecture=arch, installed_version=release['version'],
                    tag=release['tag'], tag_object_sha=tag_sha, commit_sha=commit,
                    tag_verification=dict(verified=True, reason='valid', verified_at=verification.get('verified_at')),
                    release=identity, asset=asset(basename), checksum_asset=asset(basename + '.sha256'))

    def recheck(self, frozen, require_latest=True):
        if require_latest:
            latest = self.latest()
            require(latest['id'] == frozen['release']['id'], 'new stable release appeared; rerun Update')
        record = dict(frozen['release'], version=frozen['installed_version'])
        require(self.freeze(record, frozen['architecture']) == frozen, 'frozen upstream provenance drift')

    def download(self, frozen, directory):
        directory = Path(directory)
        checksum = directory / 'archive.sha256'; archive = directory / 'archive.tar.gz'
        for key, destination in (('checksum_asset', checksum), ('asset', archive)):
            value = frozen[key]
            self.http.download(value['url'], destination, value['size'], value['sha256'])
        expected = (frozen['asset']['sha256'] + '  ' + frozen['asset']['name'] + '\n').encode()
        require(update_read(checksum, 512) == expected, 'checksum file is not an exact official entry')
        binary = directory / 'candidate'
        extract_binary(archive, binary)
        binary.chmod(0o755); update_fsync(binary); update_fsync(directory)
        return binary


RECEIPT_KEYS = {'schema', 'origin', 'repository', 'architecture', 'installed_version', 'tag',
    'tag_object_sha', 'commit_sha', 'tag_verification', 'release', 'asset', 'checksum_asset',
    'archive_sha256', 'binary', 'installed_at', 'manager_version', 'transaction_id',
    'generation_id', 'trust_policy'}


class UpdateReceipt:
    @staticmethod
    def validate(value):
        update_exact(value, RECEIPT_KEYS)
        require(type(value['schema']) is int and value['schema'] == UPDATE_SCHEMA)
        require(value['origin'] in ('official-release', 'reviewed-baseline'))
        require(value['repository'] == UPSTREAM_REPOSITORY and value['architecture'] in BASELINE_HASHES)
        update_version(value['installed_version'])
        require(value['tag'] in (value['installed_version'], 'v' + value['installed_version']))
        update_digest(value['commit_sha'], sha=True); update_digest(value['archive_sha256'])
        update_exact(value['binary'], {'sha256', 'size'}); update_digest(value['binary']['sha256'])
        require(type(value['binary']['size']) is int and 0 < value['binary']['size'] <= 128 * UPDATE_CHUNK)
        require(all(isinstance(value[k], str) and UPDATE_ID.fullmatch(value[k])
                    for k in ('transaction_id', 'generation_id')))
        update_timestamp(value['installed_at'])
        update_version(value['manager_version'])
        if value['origin'] == 'reviewed-baseline':
            require(value['installed_version'] in REVIEWED_BASELINES)
            commit, pins = REVIEWED_BASELINES[value['installed_version']]
            archive, binary = pins[value['architecture']]
            require(value['commit_sha'] == commit
                    and value['archive_sha256'] == archive and value['binary']['sha256'] == binary
                    and value['trust_policy'] == 'embedded-reviewed-baseline-v1')
            require(all(value[k] is None for k in ('tag_object_sha', 'tag_verification', 'release',
                                                 'asset', 'checksum_asset')))
        else:
            update_digest(value['tag_object_sha'], sha=True)
            update_exact(value['tag_verification'], {'verified', 'reason', 'verified_at'})
            require(value['tag_verification']['verified'] is True and value['tag_verification']['reason'] == 'valid')
            update_timestamp(value['tag_verification']['verified_at'],optional=True)
            release = value['release']
            update_exact(release, {'id','tag','published_at','draft','prerelease','target_commitish','url','html_url'})
            require(type(release['id']) is int and release['id'] > 0 and release['tag'] == value['tag']
                    and release['draft'] is False and release['prerelease'] is False
                    and release['url'] == f'https://api.github.com/repos/telemt/telemt/releases/{release["id"]}'
                    and release['html_url'] == 'https://github.com/telemt/telemt/releases/tag/' + value['tag'])
            update_timestamp(release['published_at'])
            require(isinstance(release['target_commitish'],str) and 0<len(release['target_commitish'])<=256)
            if re.fullmatch(r'[0-9a-f]{40}', release['target_commitish']):
                require(release['target_commitish']==value['commit_sha'])
            for key, suffix in (('asset', ''), ('checksum_asset', '.sha256')):
                asset = value[key]
                update_exact(asset, {'id','name','size','url','api_url','sha256'})
                name = 'telemt-' + value['architecture'] + '-linux-gnu.tar.gz' + suffix
                require(type(asset['id']) is int and asset['id'] > 0 and asset['name'] == name
                        and type(asset['size']) is int and 0 < asset['size'] <= (512 if suffix else 128 * UPDATE_CHUNK)
                        and asset['url'] == 'https://github.com/telemt/telemt/releases/download/' + value['tag'] + '/' + name
                        and asset['api_url'] == f'https://api.github.com/repos/telemt/telemt/releases/assets/{asset["id"]}')
                update_digest(asset['sha256'])
            require(value['asset']['id']!=value['checksum_asset']['id'] and
                    value['archive_sha256'] == value['asset']['sha256']
                    and value['trust_policy'] == 'github-verified-tag-and-official-asset-sha256-v1')
        return value

    @staticmethod
    def create(binary, transaction, generation, frozen=None, arch=None):
        architecture = arch or update_architecture()
        identity = update_hash(binary)
        version, commit, archive = BASELINE_VERSION, BASELINE_COMMIT, BASELINE_HASHES[architecture][0]
        if not frozen:
            matches = [(version, commit, pins[architecture][0])
                       for version, (commit, pins) in REVIEWED_BASELINES.items()
                       if identity['sha256'] == pins[architecture][1]]
            require(len(matches) == 1, 'unreviewed baseline binary')
            version, commit, archive = matches[0]
        value = dict(schema=UPDATE_SCHEMA, origin='official-release' if frozen else 'reviewed-baseline',
            repository=UPSTREAM_REPOSITORY, architecture=architecture, installed_version=version,
            tag=version, tag_object_sha=None, commit_sha=commit, tag_verification=None,
            release=None, asset=None, checksum_asset=None, archive_sha256=archive,
            binary=identity, installed_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            manager_version=UPDATE_MANAGER_VERSION, transaction_id=transaction, generation_id=generation,
            trust_policy='embedded-reviewed-baseline-v1')
        if frozen:
            value.update(frozen)
            value.update(archive_sha256=frozen['asset']['sha256'],
                         trust_policy='github-verified-tag-and-official-asset-sha256-v1')
        return UpdateReceipt.validate(value)

    @staticmethod
    def read(path): return UpdateReceipt.validate(update_json(update_read(path)))


@dataclass(frozen=True)
class UpdateLayout:
    # Prefix injection is a Python fixture API, never a manager CLI/environment option.
    prefix: Path = Path('/')

    def path(self, absolute): return self.prefix / absolute.lstrip('/')
    @property
    def state(self): return self.path('/var/lib/telemt-web-manager')
    @property
    def data(self): return self.path('/var/lib/telemt')
    @property
    def binary(self): return self.path('/usr/local/bin/telemt')
    @property
    def config(self): return self.path('/etc/telemt/telemt.toml')
    @property
    def receipt(self): return self.state / 'telemt-release.json'
    @property
    def generation(self): return self.state / 'telemt-generation.json'
    @property
    def journal(self): return self.state / 'update-journal.json'
    @property
    def permit(self): return self.path('/run/telemt-web-manager-update-permit.json')
    @property
    def stash(self): return self.path('/var/lib/.telemt-web-manager-update')
    @property
    def backups(self): return self.path('/root/telemt-backups')
    @property
    def dropin(self): return self.path('/etc/systemd/system/telemt.service.d/50-telemt-web-manager-update.conf')
    @property
    def recovery_unit(self): return self.path('/etc/systemd/system/telemt-web-manager-recovery.service')
    def backup(self, transaction):
        require(isinstance(transaction, str) and UPDATE_ID.fullmatch(transaction))
        return self.backups / ('update-' + transaction)
    def trees(self, transaction):
        require(isinstance(transaction, str) and UPDATE_ID.fullmatch(transaction))
        return self.stash / transaction


def update_private_directory(path):
    safe_path(path)
    path = Path(path)
    if not path.exists(): path.mkdir(mode=0o700); update_fsync(path.parent)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and info.st_gid == 0
            and stat.S_IMODE(info.st_mode) == 0o700, 'unsafe private updater directory')


class UpdateTree:
    """Bounded fd-based inventory and streaming clone of a stopped generation."""
    MAX_ENTRIES = 100000
    MAX_BYTES = 8 * 1024 ** 3
    MAX_DEPTH = 32
    MAX_PATH_BYTES = 16 * 1024 ** 2
    def __init__(self, uid, gid): self.uid = uid; self.gid = gid

    @staticmethod
    def same(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
                info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def inventory(self, root, seal=True, durable=False):
        require(not durable or seal)
        root = Path(root)
        no_managed_mounts([root])
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(root, flags)
        records = []; total = 0; path_bytes=0
        device = os.fstat(fd).st_dev
        def walk(parent, name, relative, depth):
            nonlocal total,path_bytes
            require(depth <= self.MAX_DEPTH and len(records) < self.MAX_ENTRIES)
            path_bytes+=len(relative.encode())
            require(path_bytes<=self.MAX_PATH_BYTES, 'DATA path inventory exceeds reviewed memory bound')
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            require(info.st_dev == device and info.st_uid in (0, self.uid) and info.st_gid in (0, self.gid)
                    and not info.st_mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX | 0o022),
                    'unsupported DATA ownership or metadata')
            directory = stat.S_ISDIR(info.st_mode)
            require(directory or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1), 'unsupported DATA object')
            opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                             (os.O_DIRECTORY if directory else 0), dir_fd=parent)
            try:
                require(self.same(info) == self.same(os.fstat(opened)) and not os.listxattr(opened),
                        'DATA identity/xattr requires review')
                record = dict(path=relative, directory=directory, uid=info.st_uid, gid=info.st_gid,
                              mode=stat.S_IMODE(info.st_mode), mtime_ns=info.st_mtime_ns,
                              size=0 if directory else info.st_size, sha256=None)
                records.append(record)
                if directory:
                    names = update_names(opened,self.MAX_ENTRIES-len(records))
                    for child in names:
                        require(len(child.encode()) <= 255 and child not in ('.', '..')
                                and all(32 <= ord(c) < 127 for c in child), 'unsafe DATA filename')
                        walk(opened, child, child if relative == '.' else relative + '/' + child, depth + 1)
                else:
                    total += info.st_size; require(total <= self.MAX_BYTES, 'DATA exceeds reviewed bound')
                    digest = hashlib.sha256(); count = 0
                    if seal:
                        while block := os.read(opened, UPDATE_CHUNK):
                            count += len(block); require(count <= info.st_size); digest.update(block)
                        require(count == info.st_size)
                        record['sha256'] = digest.hexdigest()
                if durable: os.fsync(opened)  # Files first, then their containing directories.
                if seal:
                    require(self.same(info) == self.same(os.fstat(opened))
                            == self.same(os.stat(name, dir_fd=parent, follow_symlinks=False)), 'DATA changed during inventory')
            finally: os.close(opened)
        try:
            # The root descriptor remains anchored even if a pathname changes.
            parent = os.open(root.parent, flags)
            try:
                walk(parent, root.name, '.', 0)
                if durable: os.fsync(parent)  # Persist the DATA root's directory entry too.
            finally: os.close(parent)
            require(os.fstat(fd).st_ino == root.lstat().st_ino)
        finally: os.close(fd)
        result = dict(schema=1, entries=records, logical_bytes=total)
        if durable: require(self.inventory(root) == result, 'DATA changed during durability sealing')
        return result

    @staticmethod
    def validate(index):
        update_exact(index, {'schema','entries','logical_bytes'})
        require(index['schema'] == 1 and type(index['entries']) is list
                and 0 < len(index['entries']) <= UpdateTree.MAX_ENTRIES)
        paths = set(); total = 0; path_bytes=0
        for record in index['entries']:
            update_exact(record, {'path','directory','uid','gid','mode','mtime_ns','size','sha256'})
            p = record['path']; require(isinstance(p, str) and len(p) <= 8192 and p not in paths)
            path_bytes+=len(p.encode()); require(path_bytes<=UpdateTree.MAX_PATH_BYTES)
            require(len(Path(p).parts)<=UpdateTree.MAX_DEPTH and all(32<=ord(c)<127 for c in p))
            require(p == '.' or (not p.startswith('/') and all(x not in ('', '.', '..') for x in p.split('/'))))
            require(p == '.' or str(Path(p).parent) in paths)
            require(type(record['directory']) is bool and all(type(record[k]) is int and record[k] >= 0
                    for k in ('uid','gid','mode','mtime_ns','size')))
            require(record['mode'] <= 0o777 and record['size'] <= UpdateTree.MAX_BYTES)
            if record['directory']: require(record['sha256'] is None and record['size'] == 0)
            else: update_digest(record['sha256']); total += record['size']
            paths.add(p)
        require(index['entries'][0]['path'] == '.' and index['entries'][0]['directory']
                and total == index['logical_bytes'] <= UpdateTree.MAX_BYTES)
        return index

    def clone(self, source, destination, index, normalized=False):
        self.validate(index); source = Path(source); destination = Path(destination)
        require(not os.path.lexists(destination))
        source_index=json.loads(json.dumps(index))
        if normalized:
            for record in source_index['entries']: record.update(uid=0,gid=0)
        require(self.inventory(source) == source_index, 'sealed generation changed')
        destination.mkdir(0o700)
        source_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        target_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        def parent_fd(root, relative):
            result = os.dup(root)
            try:
                for component in Path(relative).parts[:-1]:
                    next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=result)
                    os.close(result); result = next_fd
                return result
            except BaseException: os.close(result); raise
        try:
            for record in index['entries'][1:]:
                p = record['path']; name = Path(p).name
                src_parent = parent_fd(source_fd, p); dst_parent = parent_fd(target_fd, p)
                try:
                    if record['directory']: os.mkdir(name, 0o700, dir_fd=dst_parent)
                    else:
                        src = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=src_parent)
                        dst = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dst_parent)
                        digest = hashlib.sha256(); count = 0
                        try:
                            before = os.fstat(src)
                            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1)
                            while block := os.read(src, UPDATE_CHUNK):
                                count += len(block); require(count <= record['size']); digest.update(block)
                                view = memoryview(block)
                                while view:
                                    written = os.write(dst, view); require(written > 0); view = view[written:]
                            require(count == record['size'] and digest.hexdigest() == record['sha256']
                                    and self.same(before) == self.same(os.fstat(src)))
                            os.fsync(dst)
                        finally: os.close(src); os.close(dst)
                    os.fsync(dst_parent)
                finally: os.close(src_parent); os.close(dst_parent)
            for record in reversed(index['entries']):
                path = destination if record['path'] == '.' else destination / record['path']
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    os.fchown(fd, record['uid'], record['gid']); os.fchmod(fd, record['mode'])
                    os.utime(fd, ns=(record['mtime_ns'], record['mtime_ns'])); os.fsync(fd)
                finally: os.close(fd)
            update_fsync(destination.parent)
            require(self.inventory(destination) == index)
            require(self.inventory(source) == source_index, 'source changed during clone')
        finally: os.close(source_fd); os.close(target_fd)

    def budget(self, root, binary_bytes=128 * UPDATE_CHUNK):
        index = self.inventory(root, seal=False)
        space = os.statvfs(Path(root).parent)
        # Snapshot + isolated rehearsal + pristine candidate + quarantined failed
        # generation, metadata and emergency recovery headroom. Old LKG is never
        # deleted merely to pass this check.
        required = (index['logical_bytes'] + len(index['entries'])*space.f_frsize) * 4 + binary_bytes * 2 + 512 * UPDATE_CHUNK
        require(space.f_bavail * space.f_frsize >= required
                and space.f_favail >= len(index['entries']) * 4 + 1024, 'insufficient rollback space/inodes')
        return index


def update_generation_value(receipt):
    return dict(schema=1, generation_id=receipt['generation_id'], binary=receipt['binary'],
                receipt_sha256=hashlib.sha256(json.dumps(receipt, sort_keys=True,
                    separators=(',', ':')).encode() + b'\n').hexdigest())


def update_generation(layout, receipt=None):
    receipt = receipt or UpdateReceipt.read(layout.receipt)
    value = update_json(update_read(layout.generation))
    require(value == update_generation_value(receipt), 'generation/receipt mismatch')
    marker = update_json(update_read(layout.data / '.telemt-web-manager-generation.json'))
    require(marker == dict(schema=1, generation_id=receipt['generation_id']), 'DATA generation mismatch')
    require(update_hash(layout.binary) == receipt['binary'], 'installed binary differs from receipt')
    return receipt


class UpdateJournal:
    KEYS = {'schema','transaction_id','phase','intent','sequence','old','new','snapshot',
            'immutable','service','supervisor','created_at','error','lkg','restored','kind','normalized'}
    def __init__(self, layout): self.layout = layout; self.value = None

    @classmethod
    def validate(cls, value):
        update_exact(value, cls.KEYS)
        require(type(value['schema']) is int and value['schema'] == 1
                and isinstance(value['transaction_id'], str) and UPDATE_ID.fullmatch(value['transaction_id'])
                and value['phase'] in UPDATE_PHASES and (value['intent'] is None or value['intent'] in UPDATE_INTENTS)
                and type(value['sequence']) is int and 0 <= value['sequence'] <= 10000
                and type(value['restored']) is bool and type(value['normalized']) is bool
                and value['kind'] in ('update','baseline-migration','baseline-install'))
        for key in ('old','new'):
            if value[key] is not None:
                update_exact(value[key], {'receipt','receipt_present'})
                UpdateReceipt.validate(value[key]['receipt'])
                require(type(value[key]['receipt_present']) is bool)
        require(type(value['immutable']) is dict and len(value['immutable']) <= 256)
        require(all(isinstance(k, str) and 0 < len(k) <= 512 and all(32 <= ord(c) < 127 for c in k)
                    and isinstance(v, str) and UPDATE_HEX.fullmatch(v)
                    for k,v in value['immutable'].items()))
        if value['snapshot'] is not None:
            update_exact(value['snapshot'], {'sha256','entries','logical_bytes','generation_id'})
            update_digest(value['snapshot']['sha256'])
            require(type(value['snapshot']['entries']) is int and 0 < value['snapshot']['entries'] <= UpdateTree.MAX_ENTRIES
                    and type(value['snapshot']['logical_bytes']) is int
                    and 0 <= value['snapshot']['logical_bytes'] <= UpdateTree.MAX_BYTES
                    and UPDATE_ID.fullmatch(value['snapshot']['generation_id']))
        update_exact(value['supervisor'], {'pid','starttime','boot_id'})
        require(type(value['supervisor']['pid']) is int and value['supervisor']['pid'] > 0
                and isinstance(value['supervisor']['starttime'], str) and value['supervisor']['starttime'].isdigit()
                and re.fullmatch(r'[0-9a-f-]{36}', value['supervisor']['boot_id']))
        require(value['service'] is None or value['service'] in ('enabled-active','disabled-active'))
        require(value['error'] is None or value['error'] in ('interrupted','validation-failed','recovery-failed','cleanup-failed'))
        require(value['lkg'] is None or UPDATE_ID.fullmatch(value['lkg']))
        update_timestamp(value['created_at'])
        require(value['old'] is not None and (value['phase']!='COMMITTED' or value['new'] is not None))
        intents={
            'STAGING':{None,'MIGRATE_BASELINE'}, 'PREPARED':{None,'STOP_OLD','PUBLISH_GATE','COMMIT'},
            'OLD_STOPPED':{None,'MOVE_OLD_DATA'},
            'SNAPSHOT_COMPLETE':{None,'PUBLISH_WORKING_DATA','REPLACE_BINARY','REPLACE_RECEIPT'},
            'CANDIDATE_ACTIVATED':{None,'START_CANDIDATE'},
            'CANDIDATE_RUNNING':{None,'START_CANDIDATE','STOP_CANDIDATE'},
            'COMMITTING':{None,'COMMIT'}, 'COMMITTED':{None,'NORMALIZE_LKG'},
            'ROLLING_BACK':{None,'RESTORE_DATA','RESTORE_BINARY','RESTORE_RECEIPT','START_OLD'},
            'ROLLBACK_COMPLETE':{None}, 'CRITICAL':{None}}
        require(value['intent'] in intents[value['phase']], 'invalid journal operation/phase combination')
        if value['snapshot']:
            require(value['snapshot']['generation_id']==value['old']['receipt']['generation_id'])
        if value['phase'] in ('CANDIDATE_ACTIVATED','CANDIDATE_RUNNING','COMMITTING'):
            require(value['new'] is not None and value['snapshot'] is not None)
        if value['kind']!='update': require(value['snapshot'] is None)
        return value

    def read(self):
        self.value = self.validate(update_json(update_read(self.layout.journal), UPDATE_CHUNK))
        return self.value

    def publish(self):
        self.validate(self.value); update_write_json(self.layout.journal, self.value)

    def begin(self, old, receipt_present=True, lkg=None, immutable=None, service=None, kind='update'):
        if self.layout.journal.exists(): require(self.read()['phase'] in UPDATE_TERMINAL)
        transaction = uuid.uuid4().hex
        self.value = dict(schema=1, transaction_id=transaction, phase='STAGING', intent=None, sequence=0,
            old=dict(receipt=old, receipt_present=receipt_present), new=None, snapshot=None,
            immutable=immutable or {}, service=service, supervisor=update_supervisor(), restored=False, normalized=False, kind=kind,
            created_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), error=None, lkg=lkg)
        self.publish(); return transaction

    def intent(self, operation):
        require(operation in UPDATE_INTENTS and self.value['intent'] is None)
        self.value['intent'] = operation; self.value['sequence'] += 1; self.publish()

    def result(self, phase=None):
        require(self.value['intent'] is not None)
        self.value['intent'] = None
        if phase: require(phase in UPDATE_PHASES); self.value['phase'] = phase
        self.value['sequence'] += 1; self.publish()


def update_starttime(pid):
    text = Path('/proc', str(pid), 'stat').read_text()
    return text[text.rfind(')') + 2:].split()[19]


def update_supervisor():
    return dict(pid=os.getpid(), starttime=update_starttime(os.getpid()),
                boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip())


def update_supervisor_alive(value):
    try:
        return (value['boot_id'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip()
                and update_starttime(value['pid']) == value['starttime']
                and Path('/proc', str(value['pid'])).stat().st_uid == 0)
    except (OSError, IndexError): return False


UPDATE_DROPIN = '''# Managed by telemt-web-manager update gate schema 1
[Unit]
Requires=telemt-web-manager-recovery.service
After=telemt-web-manager-recovery.service
[Service]
ExecCondition=!/usr/bin/python3 /opt/telemt-web-manager/lib/safety.py update-service-gate
SendSIGKILL=no
'''
UPDATE_RECOVERY_UNIT = '''# Managed by telemt-web-manager recovery schema 1
[Unit]
Description=Recover interrupted Telemt manager update
Wants=nginx.service
After=local-fs.target nginx.service
Before=telemt.service
[Service]
Type=notify
NotifyAccess=main
RemainAfterExit=yes
ExecStart=/usr/bin/python3 /opt/telemt-web-manager/lib/safety.py update-recover boot
TimeoutStartSec=600
TimeoutStopSec=30
User=root
Group=root
UMask=0077
ProtectSystem=strict
ProtectHome=false
PrivateTmp=true
ReadWritePaths=/var/lib /usr/local/bin /run /root/telemt-backups /etc/systemd/system
[Install]
WantedBy=multi-user.target
'''


def update_gate_contract(layout, allow_absent=False):
    directory = layout.dropin.parent
    if os.path.lexists(directory):
        safe_path(directory)
        require(directory.is_dir() and {p.name for p in directory.iterdir()} <= {layout.dropin.name},
                'foreign Telemt drop-in')
    if os.path.lexists(layout.recovery_unit):
        require(update_read(layout.recovery_unit, 4096, (0o644,)) == UPDATE_RECOVERY_UNIT.encode(),
                'manager recovery unit changed')
    if not os.path.lexists(layout.dropin):
        require(allow_absent, 'manager start gate missing'); return False
    require(update_read(layout.dropin, 4096, (0o644,)) == UPDATE_DROPIN.encode()
            and update_read(layout.recovery_unit, 4096, (0o644,)) == UPDATE_RECOVERY_UNIT.encode(),
            'manager gate/recovery unit changed')
    return True


def update_gate_publish(layout):
    if update_gate_contract(layout, allow_absent=True): return
    # Harmless alone; the drop-in is the final activation point. Never publish
    # a Telemt Requires dependency before its durable target unit exists.
    update_write(layout.recovery_unit, UPDATE_RECOVERY_UNIT.encode(), 0o644)
    safe_path(layout.dropin.parent)
    layout.dropin.parent.mkdir(mode=0o755, exist_ok=True)
    layout.dropin.parent.chmod(0o755)
    update_fsync(layout.dropin.parent.parent)
    update_write(layout.dropin, UPDATE_DROPIN.encode(), 0o644)


def update_permit(layout, journal, receipt):
    require(journal.value['phase'] in ('CANDIDATE_ACTIVATED','CANDIDATE_RUNNING','ROLLING_BACK'))
    update_write_json(layout.permit, dict(schema=1, transaction_id=journal.value['transaction_id'],
        generation_id=receipt['generation_id'], binary_sha256=receipt['binary']['sha256'],
        phase=journal.value['phase'], **update_supervisor()))


def update_clear_permit(layout):
    if os.path.lexists(layout.permit):
        update_read(layout.permit, 4096)  # Refuse a substituted path, even on cleanup.
        layout.permit.unlink(); update_fsync(layout.permit.parent)


def update_service_gate(layout=None):
    """Pure read-only ExecCondition. No lock acquisition or network requests."""
    layout = layout or UpdateLayout()
    require(os.geteuid() == 0)
    update_gate_contract(layout)
    receipt = update_generation(layout)
    require(os.path.lexists(layout.journal), 'managed release journal missing')
    journal = UpdateJournal(layout).read()
    require(journal['phase'] != 'CRITICAL')
    if journal['phase'] in UPDATE_TERMINAL:
        expected = journal['new'] if journal['phase'] == 'COMMITTED' else journal['old']
        require(expected is not None and receipt == expected['receipt'], 'terminal generation differs')
        return
    permit = update_json(update_read(layout.permit, 4096), 4096)
    update_exact(permit, {'schema','transaction_id','generation_id','binary_sha256','phase','pid','starttime','boot_id'})
    expected = journal['new'] if journal['phase'] in ('CANDIDATE_ACTIVATED','CANDIDATE_RUNNING') else journal['old']
    require(journal['phase'] in ('CANDIDATE_ACTIVATED','CANDIDATE_RUNNING','ROLLING_BACK')
            and permit['schema'] == 1 and permit['transaction_id'] == journal['transaction_id']
            and permit['phase'] == journal['phase'] and permit['generation_id'] == receipt['generation_id']
            and permit['binary_sha256'] == receipt['binary']['sha256']
            and expected is not None and receipt == expected['receipt']
            and update_supervisor_alive({k:permit[k] for k in ('pid','starttime','boot_id')}),
            'pending transaction has no valid supervised start permit')


def update_notify_ready():
    destination = os.environ.get('NOTIFY_SOCKET')
    require(destination and destination.startswith(('/', '@')), 'systemd notification socket unavailable')
    if destination.startswith('@'): destination = '\0' + destination[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as channel:
        channel.connect(destination); channel.sendall(b'READY=1')


class UpdateCommandFailed(ValueError):
    def __init__(self, code):
        super().__init__('external command failed'); self.code=code


def update_run(argv, timeout=30, maximum=UPDATE_CHUNK, input_data=None, accepted=(0,)):
    """Bound both streams and kill/reap a live command on failure.

    Candidate descendants additionally belong to the private systemd cgroup;
    isolation always stops that entire group, including a detached child.
    """
    require(type(argv) is list and all(isinstance(x, str) for x in argv))
    process = subprocess.Popen(argv, stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    streams = selectors.DefaultSelector(); output = bytearray(); error = bytearray()
    deadline = time.monotonic() + timeout
    try:
        if input_data is not None:
            require(len(input_data) <= UPDATE_CHUNK)
            process.stdin.write(input_data); process.stdin.close()
        for channel, target in ((process.stdout, output), (process.stderr,error)):
            os.set_blocking(channel.fileno(),False); streams.register(channel,selectors.EVENT_READ,target)
        while streams.get_map():
            require(time.monotonic() < deadline, 'external command deadline')
            for key, _ in streams.select(min(.2, max(0,deadline-time.monotonic()))):
                block = os.read(key.fd,65536)
                if not block: streams.unregister(key.fileobj); key.fileobj.close()
                else:
                    key.data.extend(block)
                    require(len(output)+len(error) <= maximum, 'external command output bound')
        code=process.wait(timeout=max(.01,deadline-time.monotonic()))
        if code not in accepted: raise UpdateCommandFailed(code)
        return bytes(output)
    finally:
        streams.close()
        if process.poll() is None:
            os.killpg(process.pid,signal.SIGKILL); process.wait()
        for channel in (process.stdout, process.stderr):
            if channel and not channel.closed: channel.close()


class UpdateSystemd:
    def __init__(self, layout): self.layout=layout

    def show(self):
        keys = ['ActiveState','SubState','MainPID','InvocationID','NRestarts','ControlGroup',
                'ExecMainStatus','Result','FragmentPath','DropInPaths']
        raw = update_run(['systemctl','show','telemt.service'] + ['-p'+k for k in keys],maximum=65536).decode()
        value = dict(line.split('=',1) for line in raw.splitlines())
        require(set(value) == set(keys))
        return value

    def stop(self, candidate=False):
        # Old shutdown must be graceful. Suppress systemd's default forced kill
        # for this stop job; restore the runtime property afterward. Candidate
        # rollback may use a bounded forced stop after a failed grace period.
        try: update_run(['systemctl','stop','telemt.service'],timeout=190)
        except (ValueError, subprocess.SubprocessError):
            require(candidate, 'old Telemt did not stop gracefully')
            update_run(['systemctl','kill','--kill-whom=all','--signal=SIGKILL','telemt.service'])
        self.quiet()
        if not candidate:
            value=self.show()
            require(value['ExecMainStatus']=='0' and value['Result']=='success',
                    'Telemt graceful shutdown failed')

    def quiet(self):
        value=self.show()
        require(value['ActiveState'] in ('inactive','failed') and value['MainPID']=='0', 'Telemt is not stopped')
        require(not update_run(['ss','-H','-ltnp','sport = :18080']).strip(), 'private listener remains')
        uid=int(fresh_identity(str(self.layout.data))['user'][2])
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit(): continue
            try: status=(entry/'status').read_text()
            except (FileNotFoundError, ProcessLookupError): continue
            match=re.search(r'^Uid:\s+([0-9 \t]+)$',status,re.M)
            require(match is not None and uid not in map(int,match[1].split()), 'Telemt UID writer remains')
        if value['ControlGroup']:
            cgroup=Path('/sys/fs/cgroup') / value['ControlGroup'].lstrip('/')
            require(not cgroup.exists() or not (cgroup/'cgroup.procs').read_text().strip(), 'Telemt cgroup not empty')
        self.firewall(clean=True)

    def firewall(self, clean=False):
        raw=b'\n'.join(update_run(command,maximum=8*UPDATE_CHUNK) for command in
                      (['nft','list','ruleset'],['iptables-save'],['ip6tables-save']))
        if clean: require(not re.search(rb'TELEMT_|telemt_conntrack',raw), 'Telemt firewall shutdown incomplete')
        return raw

    def conntrack(self):
        paths=update_run(['systemd-path','search-binaries-default'],maximum=4096).decode().strip()
        require(paths and all(p.startswith('/') and len(p)<256 for p in paths.split(':')))
        binary=shutil.which('conntrack',path=paths)
        require(binary is not None,'conntrack missing on the default systemd runtime PATH')
        safe_path(Path(binary).resolve(strict=True))
        update_run([binary,'--version'],maximum=4096)
        update_run([binary,'-L'],timeout=10,maximum=8*UPDATE_CHUNK)

    def start(self): update_run(['systemctl','start','telemt.service'],timeout=100)
    def reload(self): update_run(['systemctl','daemon-reload'])
    def ensure_recovery(self): update_run(['systemctl','start','telemt-web-manager-recovery.service'],timeout=600)

    def identity(self, receipt):
        value=self.show()
        require(value['ActiveState']=='active' and value['SubState']=='running'
                and value['MainPID'].isdigit() and int(value['MainPID'])>0
                and re.fullmatch('[0-9a-f]{32}',value['InvocationID']))
        pid=int(value['MainPID']); start=update_starttime(pid)
        require(update_hash(self.layout.binary)==receipt['binary'])
        executable=Path('/proc',str(pid),'exe')
        require(os.readlink(executable)==str(self.layout.binary), 'running executable pathname mismatch')
        # /proc exe is an intentional kernel link, not an archive/filesystem path.
        fd=os.open(executable,os.O_RDONLY)
        try:
            info=os.fstat(fd); digest=hashlib.sha256(); size=0
            require(stat.S_ISREG(info.st_mode) and info.st_size<=128*UPDATE_CHUNK)
            while block:=os.read(fd,UPDATE_CHUNK): size+=len(block); digest.update(block)
            require(dict(sha256=digest.hexdigest(),size=size)==receipt['binary'])
        finally: os.close(fd)
        status=(Path('/proc',str(pid),'status')).read_text()
        account=fresh_identity(str(self.layout.data)); uid=account['user'][2]; gid=account['user'][3]
        for name, number in (('Uid',uid),('Gid',gid)):
            match=re.search(r'^'+name+r':\s+([0-9 \t]+)$',status,re.M)
            require(match and match[1].split()==[number]*4)
        require(re.search(r'^CapEff:\s+0000000000001000$',status,re.M), 'CAP_NET_ADMIN contract differs')
        groups=re.search(r'^Groups:\s*(.*)$',status,re.M)
        require(groups and all(number==gid for number in groups[1].split()), 'unexpected supplementary group')
        listeners=update_run(['ss','-H','-ltnp']).decode().splitlines()
        owned=[line for line in listeners if 'pid='+str(pid)+',' in line]
        require(len(owned)==1 and '127.0.0.1:18080 ' in owned[0], 'PID listener contract differs')
        require(update_starttime(pid)==start and self.show()['MainPID']==str(pid))
        cgroup=Path('/sys/fs/cgroup') / value['ControlGroup'].lstrip('/')
        require(value['ControlGroup'].startswith('/') and cgroup.is_dir())
        events=dict(line.split() for line in (cgroup/'memory.events').read_text().splitlines())
        require(events.get('oom')=='0' and events.get('oom_kill')=='0', 'Telemt memory/OOM event')
        self.conntrack()
        return dict(pid=pid,starttime=start,invocation=value['InvocationID'],restarts=value['NRestarts'])

    def journal(self, invocation):
        raw=update_run(['journalctl','-u','telemt.service','_SYSTEMD_INVOCATION_ID='+invocation,
                        '--no-pager','-o','json'],maximum=16*UPDATE_CHUNK)
        if sys.stdout.isatty() and os.environ.get('TERM','') != 'dumb':
            summary = io.StringIO()
            with redirect_stdout(summary): result = classify_journal(raw.decode())
            if result: print(summary.getvalue(),end='',file=sys.stderr)
        else: result = classify_journal(raw.decode())
        require(result==0, 'fatal current-invocation journal record')

    def path_health(self):
        manager=self.layout.path('/opt/telemt-web-manager/telemt-web-manager.sh')
        safe_path(manager)
        require(update_read(manager,UPDATE_CHUNK,(0o755,)).startswith((b'#!/usr/bin/env bash\n# Telegram Web Proxy Manager.', b'#!/usr/bin/env bash\n# Telemt WEB Manager.')))
        config=read_config(self.layout.config)
        host=domain(config['web']['vhosts'][0]['host'])
        upstream=config['upstreams'][0]
        socks=upstream['address'] if upstream['type']=='socks5' else ''
        with tempfile.TemporaryDirectory(prefix='twm-path-health-') as temporary:
            update_run(['bash','-c','source "$1"; TMP=$2; DOMAIN=$3; SOCKS=$4; path_health',
                        'twm-path-health',str(manager),temporary,host,socks],timeout=120)


def update_pending(layout=None):
    layout=layout or UpdateLayout()
    if any(os.path.lexists(p) for p in (layout.receipt,layout.generation,layout.dropin,layout.recovery_unit)):
        require(os.path.lexists(layout.journal), 'release state has no durable journal; manual recovery required')
    if os.path.lexists(layout.journal):
        require(UpdateJournal(layout).read()['phase'] in UPDATE_TERMINAL,
                'pending/critical update: run a locked manager mutation for recovery')


class UpdateEngine:
    """One generation transaction. All filesystem destinations derive from Layout.

    Filesystem, controller, isolation and HTTP are injectable Python test APIs;
    the installed command always uses fixed production implementations/paths.
    """
    def __init__(self, layout=None, systemd=None, releases=None, isolation=None):
        self.layout=layout or UpdateLayout(); self.systemd=systemd or UpdateSystemd(self.layout)
        self.progress=UpdateProgress()
        account=fresh_identity(str(self.layout.data))
        self.tree=UpdateTree(int(account['user'][2]),int(account['user'][3]))
        self.releases=releases or UpdateReleases(); self.journal=UpdateJournal(self.layout)
        self.isolation=isolation or UpdateIsolation(self.layout,self.tree)

    def ownership(self):
        """Re-prove the fixed managed contract at the internal mutation entry."""
        layout=self.layout
        manifest=update_json(update_read(layout.state/'manifest.json',16384),16384)
        update_exact(manifest,{'schema','domain','public_ip','unit_sha256','nginx_sha256','acme_webroot'})
        require(type(manifest['schema']) is int and manifest['schema']==1)
        host=domain(manifest['domain']); ipv4(manifest['public_ip'])
        for name in ('unit_sha256','nginx_sha256'): update_digest(manifest[name])
        config=read_config(layout.config); runtime_contract(layout.config,str(layout.data))
        require(managed_web_contract(config,str(layout.data))[::2]==(host,manifest['public_ip']))
        current_web_link(layout.state,layout.config)  # Success only; never print the returned secret.
        no_managed_mounts([layout.data,layout.state,layout.config.parent])
        unit=layout.path('/etc/systemd/system/telemt.service')
        manager=layout.path('/opt/telemt-web-manager/telemt-web-manager.sh')
        update_read(manager,UPDATE_CHUNK,(0o755,))
        expected=update_run(['bash','-c','source "$1"; generate_unit','twm-unit-contract',str(manager)],maximum=16384)
        require(update_read(unit,16384,(0o644,))==expected
                and update_hash(unit)['sha256']==manifest['unit_sha256'])
        state=self.systemd.show()
        require(state['FragmentPath']==str(unit))
        present=update_gate_contract(layout,allow_absent=True)
        require(state['DropInPaths']==(str(layout.dropin) if present else ''))
        nginx=layout.path('/etc/nginx')
        require(update_hash(nginx/'conf.d/telemt-web-manager.conf')['sha256']==manifest['nginx_sha256'])
        site_bound_identity(layout.config,str(layout.data),nginx,layout.path(SITE_ROOT))
        with tempfile.TemporaryDirectory(prefix='twm-ownership-') as directory:
            output=Path(directory)/'nginx-plan.json'
            nginx_plan(nginx,host,output,manifest=layout.state/'manifest.json')
            require(update_json(output.read_bytes())['edits']==[], 'managed Nginx integration differs')
        certroot=layout.path('/etc/letsencrypt'); acme=layout.path('/var/lib/telemt-web-manager-acme')
        record=certificate_record_value(host,certroot,acme,nginx)
        require(record['acme_webroot']==manifest['acme_webroot'])
        if os.path.lexists(layout.state/'certificate.json'):
            certificate_record_check(layout.state,host,certroot,acme,nginx)

    def local_receipt(self, allow_legacy=False):
        safe_path(self.layout.state)
        require(self.layout.state.stat().st_uid==0 and stat.S_IMODE(self.layout.state.stat().st_mode)==0o700)
        safe_path(self.layout.binary)
        info=self.layout.binary.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid==info.st_gid==0 and info.st_nlink==1
                and stat.S_IMODE(info.st_mode)==0o755 and not os.listxattr(self.layout.binary), 'unsafe installed binary')
        if os.path.lexists(self.layout.receipt):
            require(os.path.lexists(self.layout.journal), 'release state journal missing')
            require(update_gate_contract(self.layout))
            receipt=update_generation(self.layout)
            require(receipt['architecture']==update_architecture())
            return receipt
        require(allow_legacy, 'missing release receipt; manual review required')
        require(not os.path.lexists(self.layout.generation) and not
                os.path.lexists(self.layout.data/'.telemt-web-manager-generation.json'))
        require(not os.path.lexists(self.layout.dropin.parent) and not os.path.lexists(self.layout.recovery_unit),
                'missing receipt with update gate present; manual recovery required')
        installed_hash=update_hash(self.layout.binary)['sha256']
        require(any(installed_hash==pins[update_architecture()][1]
                    for _, pins in REVIEWED_BASELINES.values()),
                'missing receipt for non-pristine baseline; adoption refused')
        return UpdateReceipt.create(self.layout.binary,uuid.uuid4().hex,uuid.uuid4().hex)

    def immutable(self):
        # No paths from journal JSON are ever passed to filesystem mutations.
        # Complete fresh read constructs the same approved sources each time.
        values={}
        paths={'config':self.layout.config,'unit':self.layout.path('/etc/systemd/system/telemt.service'),
               'manifest':self.layout.state/'manifest.json','web-link':self.layout.state/'web-link.txt',
               'renew-hook':self.layout.path('/etc/letsencrypt/renewal-hooks/deploy/telemt-web-manager')}
        manifest=update_json(update_read(paths['manifest'],16384),16384)
        host=domain(manifest['domain'])
        if (self.layout.state/'certificate.json').exists(): paths['certificate-state']=self.layout.state/'certificate.json'
        nginx=self.layout.path('/etc/nginx')
        paths['nginx-web-vhost']=nginx/'conf.d/telemt-web-manager.conf'
        acme=nginx/'conf.d/telemt-web-manager-acme.conf'
        if os.path.lexists(acme): paths['nginx-acme-vhost']=acme
        parser=Nginx(nginx); streams=exact(parser.read(nginx/'nginx.conf'),'stream')
        require(len(streams)==1)
        if site_vhost_digest(parser.sources[paths['nginx-web-vhost']]):
            values['origin-site'] = site_bound_identity(self.layout.config,str(self.layout.data),nginx,
                                                       self.layout.path(SITE_ROOT))
        # Same exact fragments as reverse planning, without treating unrelated
        # topology/settings as an immutable manager-owned byte contract.
        values.update(nginx_owned_stream(parser,host,streams[0])[0])
        for key,path in paths.items():
            safe_path(path); values[key]=update_hash(path,16*UPDATE_CHUNK)['sha256']
        if update_gate_contract(self.layout,allow_absent=True):
            values['gate']=update_hash(self.layout.dropin)['sha256']
            values['recovery-unit']=update_hash(self.layout.recovery_unit)['sha256']
        return values

    def external_contract(self):
        manifest=update_json(update_read(self.layout.state/'manifest.json',16384),16384)
        host=domain(manifest['domain']); certroot=self.layout.path('/etc/letsencrypt')
        webroot=self.layout.path('/var/lib/telemt-web-manager-acme'); nginx=self.layout.path('/etc/nginx')
        record=certificate_record_value(host,certroot,webroot,nginx)
        require(record['acme_webroot']==manifest['acme_webroot'])
        if os.path.lexists(self.layout.state/'certificate.json'):
            certificate_record_check(self.layout.state,host,certroot,webroot,nginx)
        # Current lineage, hostname and key pairing, never transaction-start PEM bytes.
        fullchain=str(certroot/'live'/host/'fullchain.pem'); key=str(certroot/'live'/host/'privkey.pem')
        require(update_run(['openssl','x509','-in',fullchain,'-noout','-checkhost',host],maximum=16384).strip()==
                ('Hostname '+host+' does match certificate').encode(), 'current certificate hostname mismatch')
        update_run(['openssl','x509','-in',fullchain,'-noout','-checkend','0'],maximum=16384)
        public=update_run(['openssl','x509','-in',fullchain,'-pubkey','-noout'],maximum=16384)
        require(update_run(['openssl','pkey','-pubin','-outform','DER'],input_data=public,maximum=16384)==
                update_run(['openssl','pkey','-in',key,'-pubout','-outform','DER'],maximum=16384),
                'current certificate key mismatch')

    def verify_immutable(self):
        require(self.immutable()==self.journal.value['immutable'], 'immutable deployment bytes changed')
        self.external_contract()

    def budget(self,binary_bytes):
        index=self.tree.budget(self.layout.data,binary_bytes)
        space=os.statvfs(self.layout.backups)
        required=index['logical_bytes']+len(index['entries'])*space.f_frsize+binary_bytes*4+1024*UPDATE_CHUNK
        if Path(self.layout.data).stat().st_dev==self.layout.backups.stat().st_dev:
            required+=(index['logical_bytes']+len(index['entries'])*space.f_frsize)*4+binary_bytes*2
        require(space.f_bavail*space.f_frsize>=required and space.f_favail>=len(index['entries'])+1024,
                'insufficient private rehearsal/evidence filesystem space/inodes')
        return index

    def accept(self, receipt, first=150, second=None):
        # No retries around a failed objective assertion. Readiness alone uses a
        # deadline; all samples after readiness must pass immediately.
        deadline=time.monotonic()+90
        while self.systemd.show()['ActiveState']=='activating' and time.monotonic()<deadline: time.sleep(.2)
        while True:
            state=self.systemd.show()
            require(state['ActiveState'] in ('active','activating') and state['NRestarts']=='0',
                    'candidate failed/restarted before readiness')
            try: identity=self.systemd.identity(receipt); break
            except (ValueError,FileNotFoundError,ProcessLookupError):
                require(time.monotonic()<deadline, 'Telemt identity/listener readiness deadline')
                time.sleep(.2)
        self.systemd.path_health(); self.systemd.journal(identity['invocation'])
        probe=UpdateWEBProbe(read_config(self.layout.config)); probe.run(full=True)
        start=time.monotonic()
        samples=(0,5,15,30,60,90,120,150) if first==150 else tuple(sorted({0,min(5,first),min(15,first),first}))
        self.progress.event(4 if first == 150 else 5, "Candidate stability acceptance" if first == 150 else "Restarted candidate acceptance")
        for sample in samples:
            self.progress.wait(start+sample,start,first)
            require(self.systemd.identity(receipt)==identity, 'Telemt identity/restart changed during acceptance')
            self.systemd.path_health(); self.systemd.journal(identity['invocation'])
            self.verify_immutable()
            self.progress.sample(sample)
        require(time.monotonic()-start>=first)
        probe.run(full=False)
        self.systemd.firewall()
        if second is not None:
            self.journal.intent('STOP_CANDIDATE'); self.systemd.stop(); self.journal.result()
            self.tree.inventory(self.layout.data)  # Stopped writer; validate all persisted DATA objects.
            old_quota=self.layout.trees(self.journal.value['transaction_id'])/'old/state/telemt.limit.json'
            new_quota=self.layout.data/'state/telemt.limit.json'
            old=update_quota_read(old_quota,self.tree.uid) if os.path.lexists(old_quota) else None
            update_quota_preserve(old,new_quota,self.tree.uid)
            self.journal.intent('START_CANDIDATE'); update_permit(self.layout,self.journal,receipt)
            self.systemd.start(); self.journal.result()
            update_permit(self.layout,self.journal,receipt)
            self.accept(receipt,first=second)

    def step(self, intent, operation, phase=None):
        self.journal.intent(intent); operation(); self.journal.result(phase)

    def publish_receipt(self, receipt):
        update_write_json(self.layout.receipt,receipt)
        update_write_json(self.layout.generation,update_generation_value(receipt))
        require(update_generation(self.layout)==receipt)

    def publish_binary(self, source, expected):
        destination=self.layout.binary; safe_path(destination)
        temporary=destination.parent/('.twm-update-'+uuid.uuid4().hex)
        try:
            update_copy_stream(source,temporary,0o755)
            require(update_hash(temporary)==expected)
            os.replace(temporary,destination); update_fsync(destination.parent)
            require(update_hash(destination)==expected)
        finally:
            if temporary.exists(): temporary.unlink(); update_fsync(temporary.parent)

    def rename(self, source, destination):
        require(source.parent.stat().st_dev==destination.parent.stat().st_dev,
                'rollback rename crosses filesystem')
        require(not os.path.lexists(destination))
        safe_path(source.parent); safe_path(destination.parent)
        a=os.open(source.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        b=os.open(destination.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            require(stat.S_ISDIR(os.stat(source.name,dir_fd=a,follow_symlinks=False).st_mode))
            os.rename(source.name,destination.name,src_dir_fd=a,dst_dir_fd=b); os.fsync(a); os.fsync(b)
        finally: os.close(a); os.close(b)

    def snapshot_index(self):
        value=self.journal.value; require(value['snapshot'] is not None)
        raw=update_read(self.layout.backup(value['transaction_id'])/'stopped-data-index.json',64*UPDATE_CHUNK)
        require(hashlib.sha256(raw).hexdigest()==value['snapshot']['sha256'])
        index=UpdateTree.validate(update_json(raw,64*UPDATE_CHUNK))
        require(len(index['entries'])==value['snapshot']['entries']
                and index['logical_bytes']==value['snapshot']['logical_bytes'])
        return index

    def marker(self, root):
        value=update_json(update_read(root/'.telemt-web-manager-generation.json',4096),4096)
        update_exact(value,{'schema','generation_id'})
        require(value['schema']==1 and UPDATE_ID.fullmatch(value['generation_id']))
        return value['generation_id']

    def normalize(self, root):
        # Quiescent private retained evidence must not keep the removed telemt
        # UID alive in account ownership scans. Original UID/mode/mtime remains
        # in the sealed inventory. Never follow a link in failed candidate data.
        no_managed_mounts([root])
        fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        count=0
        def walk(directory,depth=0):
            nonlocal count
            require(depth<=UpdateTree.MAX_DEPTH)
            for name in update_names(directory,UpdateTree.MAX_ENTRIES*2-count):
                count+=1; require(count<=UpdateTree.MAX_ENTRIES*2)
                info=os.stat(name,dir_fd=directory,follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
                    try: walk(child,depth+1)
                    finally: os.close(child)
                os.chown(name,0,0,dir_fd=directory,follow_symlinks=False)
            os.fchown(directory,0,0); os.fsync(directory)
        try: walk(fd)
        finally: os.close(fd)

    def migrate(self, receipt):
        """No binary/DATA rewrite: journal baseline ownership and start gate."""
        self.progress.log('Verifying pristine baseline ownership and publishing recovery controls.', 'Проверяем принадлежность исходной установки и создаём средства безопасного восстановления.')
        self.ownership(); self.systemd.identity(receipt); self.systemd.path_health()
        transaction=self.journal.begin(receipt,receipt_present=False,immutable=self.immutable(),kind='baseline-migration')
        try:
            backup=self.layout.backup(transaction); update_private_directory(self.layout.backups); update_private_directory(backup)
            self.journal.value['new']=dict(receipt=receipt,receipt_present=True); self.journal.publish()
            self.journal.intent('MIGRATE_BASELINE')
            update_write_json(self.layout.data/'.telemt-web-manager-generation.json',
                              dict(schema=1,generation_id=receipt['generation_id']))
            update_write_json(self.layout.receipt,receipt)
            update_write_json(self.layout.generation,update_generation_value(receipt))
            self.journal.result('PREPARED')
            self.step('PUBLISH_GATE',lambda:update_gate_publish(self.layout))
            self.systemd.reload()
            self.progress.log('Starting durable manager recovery barrier.', 'Запускаем защиту запуска и восстановления менеджера.')
            self.systemd.ensure_recovery()
            current=self.immutable()
            require({k:v for k,v in current.items() if k not in ('gate','recovery-unit')}==self.journal.value['immutable'])
            self.step('COMMIT',lambda:require(update_generation(self.layout)==receipt),'COMMITTED')
            return receipt
        except BaseException:
            self.recover(force=True)
            raise


    def update(self):
        self.recover()
        self.ownership()
        old=self.local_receipt(allow_legacy=True)
        self.systemd.identity(old); self.systemd.path_health()
        self.progress.event(1, 'Discovering official stable Telemt release.')
        latest=self.releases.latest(); frozen=self.releases.freeze(latest,update_architecture())
        comparison=version_compare(latest['version'],old['installed_version'])
        self.progress.event(1, 'Verified official stable candidate: '+latest['version']+'; installed: '+old['installed_version'])
        if self.progress.enabled or self.progress.language == 'ru':
            self.progress.log('Updating Telemt '+old['installed_version']+' → '+latest['version'],
                              'Обновление Telemt '+old['installed_version']+' → '+latest['version'])
        require(comparison>=0, 'installed release is newer; automatic downgrade refused')
        if comparison==0:
            require(latest['version']==old['installed_version'], 'non-exact equal version requires manual review')
            if old['origin']=='official-release':
                require(all(old[k]==v for k,v in frozen.items()), 'same-version upstream identity changed')
            else: require(frozen['commit_sha']==old['commit_sha'] and frozen['asset']['sha256']==old['archive_sha256'])
            if not self.layout.receipt.exists(): old=self.migrate(old)
            self.progress.log('already up to date; local receipt and objective health verified',
                              'Уже установлена актуальная версия; запись о релизе и работоспособность проверены.'); return
        if not self.layout.receipt.exists(): old=self.migrate(old)
        previous=self.journal.read() if self.layout.journal.exists() else None
        lkg=previous['transaction_id'] if previous and previous['phase']=='COMMITTED' and previous['snapshot'] else (previous['lkg'] if previous else None)
        immutable=self.immutable()
        enabled=update_run(['systemctl','is-enabled','telemt.service'],accepted=(0,1)).decode().strip()
        require(enabled in ('enabled','disabled'))
        transaction=self.journal.begin(old,lkg=lkg,immutable=immutable,service=enabled+'-active')
        backup=self.layout.backup(transaction)
        update_private_directory(self.layout.backups); update_private_directory(backup)
        update_private_directory(self.layout.stash); update_private_directory(self.layout.trees(transaction))
        try:
            self.releases.recheck(frozen,require_latest=False)
            self.budget(128*UPDATE_CHUNK)
            candidate=self.releases.download(frozen,backup)
            new=UpdateReceipt.create(candidate,transaction,uuid.uuid4().hex,frozen=frozen)
            self.journal.value['new']=dict(receipt=new,receipt_present=True); self.journal.publish()
            root=self.isolation.prepare(backup/'precheck',candidate)
            self.progress.event(2, 'Running isolated candidate compatibility and WEB checks before downtime.')
            self.isolation.run(root,new['installed_version'])
            self.releases.recheck(frozen,require_latest=False); self.verify_immutable()
            self.budget(new['binary']['size'])
            update_copy_stream(self.layout.binary,backup/'old-binary',0o600)
            update_write_json(backup/'old-receipt.json',old)
            require(update_hash(backup/'old-binary')==old['binary'])
            self.journal.value['phase']='PREPARED'; self.journal.publish()
            self.releases.recheck(frozen); self.verify_immutable()
            self.step('STOP_OLD',self.systemd.stop,'OLD_STOPPED')
            self.progress.event(3, 'Old service stopped gracefully; sealing complete DATA.')
            self.budget(new['binary']['size']); self.systemd.quiet()
            index=self.tree.inventory(self.layout.data,durable=True)
            update_write_json(backup/'stopped-data-index.json',index)
            self.journal.value['snapshot']=dict(sha256=update_hash(backup/'stopped-data-index.json',64*UPDATE_CHUNK)['sha256'],
                entries=len(index['entries']),logical_bytes=index['logical_bytes'],generation_id=old['generation_id'])
            self.journal.publish()
            trees=self.layout.trees(transaction)
            self.step('MOVE_OLD_DATA',lambda:self.rename(self.layout.data,trees/'old'),'SNAPSHOT_COMPLETE')
            require(self.tree.inventory(trees/'old')==index)
            root=self.isolation.prepare(backup/'rehearsal',candidate,trees/'old',index)
            self.progress.event(3, 'Rehearsing stopped DATA on the isolated candidate, including restart/readback.')
            self.isolation.run(root,new['installed_version'],rehearsal=True)
            require(self.tree.inventory(trees/'old')==index); self.verify_immutable()
            self.tree.clone(trees/'old',trees/'working',index)
            update_write_json(trees/'working'/'.telemt-web-manager-generation.json',dict(schema=1,generation_id=new['generation_id']))
            self.step('PUBLISH_WORKING_DATA',lambda:self.rename(trees/'working',self.layout.data))
            self.step('REPLACE_BINARY',lambda:self.publish_binary(candidate,new['binary']))
            self.step('REPLACE_RECEIPT',lambda:self.publish_receipt(new),'CANDIDATE_ACTIVATED')
            self.journal.intent('START_CANDIDATE'); update_permit(self.layout,self.journal,new)
            self.systemd.start(); self.journal.result('CANDIDATE_RUNNING'); update_permit(self.layout,self.journal,new)
            self.progress.event(4, 'Candidate activated; beginning objective 150s acceptance and 45s restarted acceptance.')
            self.accept(new,first=150,second=45)
            self.releases.recheck(frozen,require_latest=False); self.verify_immutable()
            require(self.tree.inventory(trees/'old')==index and update_generation(self.layout)==new)
            self.journal.value['phase']='COMMITTING'; self.journal.publish()
            self.step('COMMIT',lambda:require(update_generation(self.layout)==new),'COMMITTED')
            update_clear_permit(self.layout)
            self.finish_committed()
            if self.progress.enabled or self.progress.language == 'ru':
                self.progress.finish('Telemt updated successfully: '+old['installed_version']+' → '+new['installed_version'],
                                     russian='Telemt успешно обновлён: '+old['installed_version']+' → '+new['installed_version'])
            else: print('Updated to '+new['installed_version']+'. TOML and deployment controls preserved byte-for-byte.')
        except BaseException:
            message = ('Update committed; housekeeping requires manual review.' if self.journal.value['phase']=='COMMITTED'
                       else 'Update failed at '+str(self.progress.stage)+'/5; validating rollback.')
            self.progress.finish(message,failed=True,
                russian=('Обновление завершено; очистка сохранённых данных требует ручной проверки.' if self.journal.value['phase']=='COMMITTED'
                         else 'Ошибка обновления на этапе '+str(self.progress.stage)+'/5; проверяем восстановление прежней версии.'))
            if self.journal.value['phase']!='COMMITTED':
                self.journal.value['error']='validation-failed'; self.journal.publish()
                self.recover(force=True)
                raise
            self.journal.value['error']='cleanup-failed'; self.journal.publish()
            self.progress.log('Update committed successfully. Retained generation cleanup requires manual review; new version remains active.',
                              'Обновление завершено. Очистка сохранённого поколения требует ручной проверки; новая версия остаётся активной.', stream=sys.stderr)

    def finish_committed(self):
        value=self.journal.value
        require(value['phase']=='COMMITTED')
        if not value['snapshot'] or value['normalized']: return
        trees=self.layout.trees(value['transaction_id'])
        if value['intent'] is None: self.journal.intent('NORMALIZE_LKG')
        require(value['intent']=='NORMALIZE_LKG')
        index=self.snapshot_index()
        actual=self.tree.inventory(trees/'old')
        expected=json.loads(json.dumps(index))
        for record, saved in zip(actual['entries'],expected['entries']):
            require(record['uid'] in (0,saved['uid']) and record['gid'] in (0,saved['gid']))
            saved.update(uid=record['uid'],gid=record['gid'])
        require(actual==expected, 'retained old generation was changed')
        backup=self.layout.backup(value['transaction_id'])
        require(update_hash(backup/'old-binary')==value['old']['receipt']['binary'])
        # Private experiments are disposable; only the sealed old DATA is LKG.
        for path in (backup/'precheck',backup/'rehearsal',trees/'working'):
            if os.path.lexists(path): self.discard_private(path)
        for root in (trees,backup): self.normalize(root)
        update_write_json(backup/'lkg.json',dict(schema=1,transaction_id=value['transaction_id'],
            old=value['old']['receipt'],snapshot=value['snapshot']))
        if value['lkg']:
            previous=self.layout.backup(value['lkg'])/'lkg.json'
            prior=update_json(update_read(previous))
            update_exact(prior,{'schema','transaction_id','old','snapshot'})
            require(prior['schema']==1 and prior['transaction_id']==value['lkg'])
            UpdateReceipt.validate(prior['old'])
            root=self.layout.trees(value['lkg'])
            retirement=backup/'lkg-retirement.json'
            proof=dict(schema=1,retiring=value['lkg'],superseded_by=value['transaction_id'])
            if not os.path.lexists(retirement):
                old_index_path=self.layout.backup(value['lkg'])/'stopped-data-index.json'
                require(update_hash(old_index_path,64*UPDATE_CHUNK)['sha256']==prior['snapshot']['sha256'])
                old_index=UpdateTree.validate(update_json(update_read(old_index_path,64*UPDATE_CHUNK),64*UPDATE_CHUNK))
                for record in old_index['entries']: record.update(uid=0,gid=0)
                require(self.tree.inventory(root/'old')==old_index and self.marker(root/'old')==prior['old']['generation_id'])
                require(update_hash(self.layout.backup(value['lkg'])/'old-binary')==prior['old']['binary'])
                update_write_json(retirement,proof)
            else: require(update_json(update_read(retirement))==proof)
            if os.path.lexists(root): self.discard_private(root,root_only=True)
            update_write_json(self.layout.backup(value['lkg'])/'lkg-retired.json',
                              dict(schema=1,superseded_by=value['transaction_id']))
        self.journal.value['normalized']=True; self.journal.result('COMMITTED')

    def discard_private(self, path, root_only=False):
        """Bounded anchored unlink; never traverses a candidate-created link."""
        path=Path(path)
        require(path.is_relative_to(self.layout.stash) or path.is_relative_to(self.layout.backups))
        safe_path(path.parent); no_managed_mounts([path]); count=0
        flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
        parent=os.open(path.parent,flags)
        def clear(directory,device,depth):
            nonlocal count
            require(depth<=UpdateTree.MAX_DEPTH)
            for name in update_names(directory,UpdateTree.MAX_ENTRIES*2-count):
                count+=1; require(count<=UpdateTree.MAX_ENTRIES*2)
                info=os.stat(name,dir_fd=directory,follow_symlinks=False)
                require(info.st_dev==device and (not root_only or info.st_uid==info.st_gid==0))
                if stat.S_ISDIR(info.st_mode):
                    child=os.open(name,flags,dir_fd=directory)
                    try: clear(child,device,depth+1)
                    finally: os.close(child)
                    os.rmdir(name,dir_fd=directory)
                else: os.unlink(name,dir_fd=directory)
            os.fsync(directory)
        try:
            fd=os.open(path.name,flags,dir_fd=parent)
            try:
                info=os.fstat(fd); require(not root_only or info.st_uid==info.st_gid==0)
                clear(fd,info.st_dev,0)
            finally: os.close(fd)
            os.rmdir(path.name,dir_fd=parent); os.fsync(parent)
        finally: os.close(parent)

    def known_transition(self, value):
        """A crash may leave a MIX of known old/new controls, never foreign ones."""
        receipts=[item['receipt'] for item in (value['old'],value['new']) if item]
        require(update_hash(self.layout.binary) in [r['binary'] for r in receipts],
                'unknown binary at interrupted transition')
        for path,known in ((self.layout.receipt,receipts),
                           (self.layout.generation,[update_generation_value(r) for r in receipts])):
            require(update_json(update_read(path)) in known, 'unknown control at interrupted transition')
        if os.path.lexists(self.layout.data):
            require(self.marker(self.layout.data) in [r['generation_id'] for r in receipts],
                    'unknown DATA at interrupted transition')

    def recover(self, force=False, boot=False):
        if not self.layout.journal.exists():
            if boot: raise ValueError('boot recovery journal missing')
            self.clean_readonly()
            return
        value=self.journal.read()
        require(value['phase']!='CRITICAL', 'critical update retained for manual recovery')
        if value['phase'] in UPDATE_TERMINAL:
            if value['kind']=='baseline-migration' and value['phase']=='ROLLBACK_COMPLETE':
                self.recover_migration(boot); return
            # Terminal authority is independent of disposable evidence/LKG
            # housekeeping. READY cannot be held hostage by cleanup failure.
            update_service_gate(self.layout)
            if boot: update_notify_ready()
            try:
                self.clean_readonly()
                if value['phase']=='COMMITTED': self.finish_committed()
                else: self.finish_rollback()
                if self.journal.value['error']=='cleanup-failed':
                    self.journal.value['error']=None; self.journal.publish()
            except (ValueError,OSError,subprocess.SubprocessError):
                self.journal.value['error']='cleanup-failed'
                try: self.journal.publish()
                except OSError:
                    if not boot: raise
                self.progress.log('Terminal generation is authoritative; housekeeping remains pending. Next mutation/bootstrap requires cleanup.',
                                  'Рабочее поколение подтверждено, но очистка не завершена. Перед следующим изменением или обновлением менеджера нужна ручная проверка и очистка.', stream=sys.stderr)
                if not boot: raise
            return
        self.clean_readonly()
        if not force and update_supervisor_alive(value['supervisor']):
            # The active lock holder is doing this transaction. systemd recovery
            # is a dependency barrier only; it must not wait on its own parent.
            if boot: update_notify_ready(); return
            raise ValueError('live transaction supervisor holds the manager lock')
        blocked=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGINT,signal.SIGTERM,signal.SIGHUP})
        try:
            old=value['old']['receipt']; transaction=value['transaction_id']
            if value['kind']=='update': self.known_transition(value)
            self.isolation.quiet(self.layout.backup(transaction))
            self.journal.value['phase']='ROLLING_BACK'; self.journal.value['intent']=None
            self.journal.value['supervisor']=update_supervisor(); self.journal.publish()
            if value['kind']=='baseline-migration':
                self.recover_migration(boot); return
            require(value['old']['receipt_present'], 'interrupted fresh install requires manual recovery')
            if not value['snapshot']:
                require(update_generation(self.layout)==old)
            if value['snapshot'] and not value['restored']:
                self.systemd.stop(candidate=True); self.systemd.quiet()
                index=self.snapshot_index(); trees=self.layout.trees(transaction)
                original=trees/'old'
                if original.exists():
                    require(self.marker(original)==old['generation_id'] and self.tree.inventory(original)==index)
                    if self.layout.data.exists():
                        require(value['new'] and self.marker(self.layout.data)==value['new']['receipt']['generation_id'])
                        self.step('RESTORE_DATA',lambda:self.rename(self.layout.data,trees/'failed'))
                    self.step('RESTORE_DATA',lambda:self.rename(original,self.layout.data))
                else:
                    require(self.marker(self.layout.data)==old['generation_id'] and self.tree.inventory(self.layout.data)==index)
                backup=self.layout.backup(transaction)
                require(update_hash(backup/'old-binary')==old['binary'])
                self.step('RESTORE_BINARY',lambda:self.publish_binary(backup/'old-binary',old['binary']))
                self.step('RESTORE_RECEIPT',lambda:self.publish_receipt(old))
                self.journal.value['restored']=True; self.journal.publish()
            else:
                require(update_generation(self.layout)==old)
            self.verify_immutable()
            update_permit(self.layout,self.journal,old)
            if boot: update_notify_ready()
            if self.systemd.show()['ActiveState']!='active': self.step('START_OLD',self.systemd.start)
            self.accept(old,first=15)
            self.journal.value['phase']='ROLLBACK_COMPLETE'; self.journal.value['intent']=None; self.journal.publish()
            self.finish_rollback()
            self.progress.log('Rollback complete: old binary, full DATA, receipt and objective health restored.',
                              'Восстановление завершено: прежний бинарник, все данные (DATA) и запись о релизе восстановлены; работоспособность проверена.')
        except BaseException:
            if self.journal.value['phase']=='ROLLBACK_COMPLETE':
                self.journal.value['error']='cleanup-failed'
                try: self.journal.publish()
                except OSError:
                    if not boot: raise
                self.progress.log('Old generation restored and healthy; retained evidence cleanup requires manual review.',
                                  'Прежнее поколение восстановлено и работает; очистка сохранённых данных требует ручной проверки.', stream=sys.stderr)
                if boot: return
                raise
            try:
                import traceback
                error=sys.exc_info()[1]
                frames=[dict(function=frame.name,line=frame.lineno) for frame in
                        traceback.extract_tb(sys.exc_info()[2]) if Path(frame.filename).name==Path(__file__).name]
                details=dict(schema=1,phase=self.journal.value['phase'],intent=self.journal.value['intent'],
                             error_type=type(error).__name__,code=error.code if isinstance(error,UpdateCommandFailed) else None,
                             locations=frames[-16:])
                status=self.systemd.show()
                details['service']={key:status[key] for key in
                    ('ActiveState','SubState','Result','ExecMainStatus','NRestarts','MainPID')
                    if key in status and isinstance(status[key],str)
                    and re.fullmatch(r'[A-Za-z0-9_-]{1,64}',status[key])}
                backup=self.layout.backup(self.journal.value['transaction_id'])
                update_private_directory(self.layout.backups); update_private_directory(backup)
                update_write_json(backup/'recovery-failure.json',details)
            except (ValueError,OSError): pass
            self.journal.value['phase']='CRITICAL'; self.journal.value['intent']=None
            self.journal.value['error']='recovery-failed'; self.journal.publish()
            update_clear_permit(self.layout)
            try: self.systemd.stop(candidate=True)
            except (ValueError,OSError,subprocess.SubprocessError): pass
            self.progress.log('CRITICAL: start gate closed; backup and journal retained for manual review.',
                              'КРИТИЧЕСКАЯ ОШИБКА: запуск заблокирован. Резервная копия и журнал сохранены; требуется ручное восстановление администратором.', stream=sys.stderr)
            raise
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK,blocked)

    def finish_rollback(self):
        value=self.journal.value
        require(value['phase']=='ROLLBACK_COMPLETE')
        update_clear_permit(self.layout)
        if value['normalized']: return
        backup=self.layout.backup(value['transaction_id']); trees=self.layout.trees(value['transaction_id'])
        for path in (backup/'precheck',backup/'rehearsal',trees/'working'):
            if os.path.lexists(path): self.discard_private(path)
        for root in (trees,backup):
            if os.path.lexists(root): self.normalize(root)
        self.journal.value['normalized']=True; self.journal.publish()

    def clean_readonly(self):
        """Reap proven private Check scratch after a killed shared-lock reader.

        Called only by an exclusive mutation/recovery. Never adopt an unknown
        directory or delete live read-only work. Scratch cannot be a rollback
        source and contains no deployment-state mutation.
        """
        if not os.path.lexists(self.layout.stash): return
        update_private_directory(self.layout.stash)
        paths=[self.layout.stash/name for name in update_names(self.layout.stash,1024)]
        for path in paths:
            if not path.name.startswith('.readonly-'): continue
            require(re.fullmatch(r'\.readonly-[0-9a-f]{32}',path.name))
            update_private_directory(path)
            proof=update_json(update_read(path/'readonly.json',4096),4096)
            update_exact(proof,{'schema','kind','supervisor'})
            require(proof['schema']==1 and proof['kind']=='read-only-compatibility')
            supervisor=proof['supervisor']; update_exact(supervisor,{'pid','starttime','boot_id'})
            require(type(supervisor['pid']) is int and supervisor['pid']>0 and
                isinstance(supervisor['starttime'],str) and re.fullmatch('[0-9]{1,24}',supervisor['starttime']) and
                isinstance(supervisor['boot_id'],str) and re.fullmatch('[0-9a-f-]{36}',supervisor['boot_id']))
            require(not update_supervisor_alive(supervisor), 'live Check scratch requires its shared lock')
            self.isolation.quiesce(path/'root')
            self.discard_private(path)

    def recover_migration(self, boot):
        old=self.journal.value['old']['receipt']
        require(update_hash(self.layout.binary)==old['binary'])
        # Known migration publishes only these new exact control objects; no
        # binary, mutable runtime file, config, certificate or Nginx mutation.
        update_remove_gate(self.layout,allow_partial=True)
        for path in (self.layout.receipt,self.layout.generation,
                     self.layout.data/'.telemt-web-manager-generation.json'):
            if os.path.lexists(path):
                raw=update_json(update_read(path))
                require(raw in (old,update_generation_value(old),dict(schema=1,generation_id=old['generation_id'])))
                path.unlink(); update_fsync(path.parent)
        self.systemd.reload()
        self.verify_immutable()
        if boot: update_notify_ready()
        if self.systemd.show()['ActiveState']!='active': self.systemd.start()
        self.accept(old,first=15)
        self.journal.value['phase']='ROLLBACK_COMPLETE'; self.journal.value['intent']=None; self.journal.publish()
        evidence=self.layout.backup(self.journal.value['transaction_id'])
        update_private_directory(self.layout.backups); update_private_directory(evidence)
        update_write_json(evidence/'migration-result.json',self.journal.value)
        self.layout.journal.unlink(); update_fsync(self.layout.journal.parent)
        self.progress.log('Baseline migration rolled back; prior receipt absence and deployment preserved.',
                          'Перенос состояния отменён с восстановлением: установка сохранена, запись о релизе по-прежнему отсутствует.')


def update_remove_gate(layout,allow_partial=False):
    if not allow_partial: update_gate_contract(layout)
    if layout.dropin.parent.exists():
        safe_path(layout.dropin.parent)
        require({p.name for p in layout.dropin.parent.iterdir()} <= {layout.dropin.name})
    for path,expected in ((layout.dropin,UPDATE_DROPIN),(layout.recovery_unit,UPDATE_RECOVERY_UNIT)):
        if os.path.lexists(path):
            require(update_read(path,4096,(0o644,))==expected.encode())
            path.unlink(); update_fsync(path.parent)
    if layout.dropin.parent.exists():
        layout.dropin.parent.rmdir(); update_fsync(layout.dropin.parent.parent)


def uninstall_update_paths(paths):
    state=Path(paths[4])
    names={'telemt-release.json','telemt-generation.json','update-journal.json'}
    if not any(os.path.lexists(state/name) for name in names): return []
    require(all(os.path.lexists(state/name) for name in names) and state.name=='telemt-web-manager')
    layout=UpdateLayout(state.parents[2])
    require(paths[:5]==[str(layout.binary),str(layout.config.parent),
                       str(layout.path('/etc/systemd/system/telemt.service')),str(layout.data),str(layout.state)]
            and (len(paths)==5 or (len(paths)==6 and paths[5]==str(layout.path(SITE_ROOT)))))
    update_pending(layout); update_gate_contract(layout); update_generation(layout)
    return [str(layout.dropin.parent),str(layout.recovery_unit)]


def update_install_baseline(layout=None):
    layout=layout or UpdateLayout()
    require(os.geteuid()==0 and not os.path.lexists(layout.receipt)
            and not os.path.lexists(layout.generation) and not os.path.lexists(layout.journal))
    receipt=UpdateReceipt.create(layout.binary,uuid.uuid4().hex,uuid.uuid4().hex)
    journal=UpdateJournal(layout)
    journal.begin(receipt,receipt_present=False,kind='baseline-install')
    journal.value['new']=dict(receipt=receipt,receipt_present=True); journal.publish()
    journal.intent('MIGRATE_BASELINE')
    update_write_json(layout.data/'.telemt-web-manager-generation.json',dict(schema=1,generation_id=receipt['generation_id']))
    update_write_json(layout.receipt,receipt); update_write_json(layout.generation,update_generation_value(receipt))
    journal.result('PREPARED')
    journal.intent('PUBLISH_GATE'); update_gate_publish(layout); journal.result()
    require(update_generation(layout)==receipt)
    journal.intent('COMMIT'); journal.result('COMMITTED')


@contextmanager
def update_exclusive_lock(layout, inherit=True):
    lock=layout.path('/run/lock/telemt-web-manager.lock'); safe_path(lock.parent)
    inherited=False
    if inherit:
        try: inherited=os.path.samestat(os.fstat(9),lock.lstat())
        except OSError: pass
    fd=os.dup(9) if inherited else os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
    try:
        info=os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid==0 and info.st_nlink==1
                and stat.S_IMODE(info.st_mode)==0o600 and os.path.samestat(info,lock.lstat()))
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally: os.close(fd)


def update_command(command, args):
    """Internal root-only APIs. Public manager still exposes only its menu/CLI."""
    require(os.geteuid()==0)
    if command=='update-isolated-run':
        require(len(args)==3); update_isolated_run(*args); return
    require(not args or (command=='update-recover' and args==['boot']))
    layout=UpdateLayout()
    if command=='update-service-gate': update_service_gate(layout); return
    if command=='update-pending': update_pending(layout); return
    if command=='update-install-baseline':
        with update_exclusive_lock(layout): update_install_baseline(layout)
        return
    if command=='update-gate-contract': update_gate_contract(layout,allow_absent=True); return
    if command=='update-local-receipt':
        update_pending(layout)
        engine=UpdateEngine(layout); receipt=engine.local_receipt(allow_legacy=True)
        print(receipt['installed_version'])
        if not layout.receipt.exists(): print('Verified pristine baseline; exclusive receipt migration pending.',file=sys.stderr)
        return
    if command=='update-readonly-compatibility':
        update_pending(layout)
        engine=UpdateEngine(layout); receipt=engine.local_receipt(allow_legacy=True)
        original=update_hash(layout.config)
        update_private_directory(layout.stash)
        temporary=layout.stash/('.readonly-'+uuid.uuid4().hex)
        update_private_directory(temporary)
        update_write_json(temporary/'readonly.json',dict(schema=1,kind='read-only-compatibility',supervisor=update_supervisor()))
        try:
            root=engine.isolation.prepare(temporary/'root',layout.binary)
            engine.isolation.run(root,receipt['installed_version'],parse_only=True)
        finally:
            engine.isolation.quiesce(temporary/'root')
            engine.discard_private(temporary)
        require(update_hash(layout.config)==original)
        return
    require(command in ('update-universal','update-recover'))
    if command=='update-recover' and not layout.journal.exists() and not args:
        if not os.path.lexists(layout.stash): return
        update_private_directory(layout.stash)
        entries=[layout.stash/name for name in update_names(layout.stash,1024)]
        if not any(path.name.startswith('.readonly-') for path in entries): return
    def interrupted(signum, frame): raise InterruptedError('updater interrupted')
    old_handlers={sig:signal.signal(sig,interrupted) for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP)}
    try:
        engine=UpdateEngine(layout)
        if command=='update-universal':
            try:
                with update_exclusive_lock(layout): engine.update()
            except BaseException:
                if not engine.progress.failed:
                    engine.progress.finish('Update failed at stage '+str(engine.progress.stage)+'/5; no success reported.',failed=True,
                                           russian=('Ошибка обновления до проверки релиза; успешное завершение не подтверждено.' if engine.progress.stage is None
                                                    else 'Ошибка обновления на этапе '+str(engine.progress.stage)+'/5; успешное завершение не подтверждено.'))
                raise
            finally: engine.progress.end_line()
        else:
            boot=bool(args)
            if boot and layout.journal.exists():
                value=UpdateJournal(layout).read()
                if value['phase'] in UPDATE_TERMINAL and value['intent'] is None and (not value['snapshot'] or value['normalized']):
                    update_generation(layout); update_notify_ready(); return
                if value['phase'] not in UPDATE_TERMINAL and update_supervisor_alive(value['supervisor']):
                    update_notify_ready(); return
            with update_exclusive_lock(layout,inherit=not boot): engine.recover(boot=boot)
    finally:
        for sig, handler in old_handlers.items(): signal.signal(sig,handler)


class UpdateWEBProbe:
    """Trusted protocol code; no candidate Javascript is evaluated."""
    def __init__(self, config, address=('127.0.0.1',18080), checkpoint=None):
        self.config = config; self.host = domain(config['web']['vhosts'][0]['host']); self.address=address
        self.secret = b'\xdd' + bytes.fromhex(config['access']['users']['web-user'])
        self.checkpoint=checkpoint or (lambda name:None)

    @staticmethod
    def frame(kind, payload=b''):
        require(0 <= kind <= 255 and len(payload) <= 65536)
        return bytes((kind,0,0,0))+struct.pack('>I',len(payload))+payload

    @staticmethod
    def frames(raw):
        require(len(raw) <= 256*1024)
        result=[]; offset=0
        while offset<len(raw):
            require(len(result)<32 and offset+8<=len(raw))
            kind=raw[offset]; stream=int.from_bytes(raw[offset+1:offset+4],'big')
            size=int.from_bytes(raw[offset+4:offset+8],'big')
            require(kind in (1,2,3,4,5,6,0x10,0x11,0x1f) and size<=65536 and offset+8+size<=len(raw))
            result.append((kind,stream,raw[offset+8:offset+8+size])); offset+=8+size
        return result

    def request(self, method, path, body=None, headers=None, timeout=5):
        connection=http.client.HTTPConnection(*self.address,timeout=timeout)
        try:
            connection.request(method,path,body,{'Host':self.host,**(headers or {})})
            response=connection.getresponse(); fields={}
            require(len(response.getheaders())<=64)
            for key,value in response.getheaders():
                key=key.lower()
                require(key not in fields and len(value)<=8192, 'ambiguous WEB response headers')
                fields[key]=value
            raw=response.read(256*1024+1); require(len(raw)<=256*1024)
            return response.status,fields,raw
        finally: connection.close()

    def run(self, full=True):
        self.checkpoint('WEB-bootstrap')
        capability=base64.urlsafe_b64encode(hmac.digest(self.secret,
            b'tdesktop-web-proxy-bridge-v1\n'+self.host.encode(),'sha256')).decode().rstrip('=')
        status,_,page=self.request('GET','/?bridge='+capability)
        credentials=re.findall(rb'bootstrap\s*=\s*"([A-Za-z0-9_-]{43})"',page)
        require(status==200 and len(credentials)==1, 'authenticated WEB bridge unavailable')
        credential=credentials[0].decode()
        headers={'Authorization':'Bearer '+credential,'Content-Type':'application/octet-stream',
                 'X-Telemt-Up-Window':'4'}
        hello=self.frame(0x10,b'\x01')
        self.checkpoint('WEB-Hello')
        status,created,welcome=self.request('POST','/api/v1/session',hello,headers)
        require(status==200 and welcome==self.frame(0x11), 'WEB Hello/Welcome contract differs')
        token=created.get('x-session-token','')
        require(re.fullmatch('[A-Za-z0-9_-]{43}',token), 'invalid WEB session response')
        try:
            self.checkpoint('WEB-session-replay')
            status,replay,body=self.request('POST','/api/v1/session',hello,headers)
            require(status==200 and body==welcome and replay.get('x-session-token')==token,
                    'WEB session replay contract differs')
            conveyor=created.get('x-telemt-up-window')
            require(conveyor is None or conveyor=='4', 'WEB conveyor negotiation differs')
            uplink={'Authorization':'Bearer '+token,'Content-Type':'application/octet-stream','X-Up-Seq':'1'}
            if conveyor: uplink['X-Telemt-Up-Confirmed']='0'
            self.checkpoint('WEB-uplink')
            status,ack,_=self.request('POST','/api/v1/up',self.frame(6),uplink)
            require(status==204 and ack.get('x-up-ack')=='1', 'WEB uplink failed')
            status,replay,_=self.request('POST','/api/v1/up',self.frame(6),uplink)
            require(status==204 and replay.get('x-up-ack')=='1', 'WEB uplink replay differs')
            if full:
                self.checkpoint('WEB-downlink')
                down={'Authorization':'Bearer '+token,'X-Down-Cursor':'0'}
                status,fields,body=self.request('POST','/api/v1/down',b'',down,timeout=40)
                frames=self.frames(body)
                require((status==204 and not frames) or (status==200 and len(frames)==1
                        and frames[0][0:2]==(5,0) and len(frames[0][2])<=64), 'WEB bounded downlink failed')
                cursor=fields.get('x-down-cursor','')
                if frames:
                    require(re.fullmatch('[1-9][0-9]{0,19}',cursor), 'invalid WEB downlink cursor')
                    status,replayed,again=self.request('POST','/api/v1/down',b'',down)
                    require(status==200 and again==body and replayed.get('x-down-cursor')==cursor,
                            'WEB downlink replay differs')
                    uplink['X-Up-Seq']='2'
                    if conveyor: uplink['X-Telemt-Up-Confirmed']='1'
                    status,ack,_=self.request('POST','/api/v1/up',self.frame(6,frames[0][2]),uplink)
                    require(status==204 and ack.get('x-up-ack')=='2', 'WEB Pong failed')
                else:
                    require(body==b'' and cursor=='0', 'idle WEB poll is not an authenticated empty response')
        finally:
            if sys.exc_info()[0] is None: self.checkpoint('WEB-close')
            status,_,_=self.request('DELETE','/api/v1/session',None,{'Authorization':'Bearer '+token})
            require(status==204, 'WEB session close failed')


def update_copy_stream(source, target, mode=0o600):
    source=Path(source); target=Path(target)
    safe_path(source); safe_path(target)
    original=update_hash(source)
    src=os.open(source,os.O_RDONLY|os.O_NOFOLLOW); dst=None
    try:
        dst=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
        # Both the public manager and boot recovery use umask 0077. The
        # published executable must still be readable/executable by Telemt.
        os.fchmod(dst,mode)
        while block:=os.read(src,UPDATE_CHUNK):
            view=memoryview(block)
            while view:
                count=os.write(dst,view); require(count>0); view=view[count:]
        os.fsync(dst)
    finally:
        os.close(src)
        if dst is not None: os.close(dst)
    require(update_hash(target)==original==update_hash(source))
    update_fsync(target.parent)


def update_quota(raw):
    value=update_json(raw,16*UPDATE_CHUNK)
    update_exact(value,{'last_reset_epoch_secs','users'})
    require(type(value['last_reset_epoch_secs']) is int and 0<=value['last_reset_epoch_secs']<2**64
            and type(value['users']) is dict and set(value['users']) <= {'web-user'})
    for item in value['users'].values():
        update_exact(item,{'used_bytes','last_reset_epoch_secs'})
        require(all(type(n) is int and 0<=n<2**64 for n in item.values()))
    return value


def update_quota_read(path, uid):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_uid in (0,uid)
                and not before.st_mode&0o022 and not os.listxattr(fd) and before.st_size<=16*UPDATE_CHUNK)
        raw=bytearray()
        while block:=os.read(fd,min(UPDATE_CHUNK,16*UPDATE_CHUNK+1-len(raw))):
            raw.extend(block); require(len(raw)<=16*UPDATE_CHUNK)
        require(UpdateTree.same(before)==UpdateTree.same(os.fstat(fd)))
        return update_quota(bytes(raw))
    finally: os.close(fd)


def update_quota_preserve(old, path, uid):
    """Compare actual persisted user semantics; top-level reset is derived.

    No persisted users means no quota preservation claim. Telemt may create or
    canonicalize its empty quota file; the complete DATA safety checks still run.
    """
    if old is None or not old['users']: return
    new=update_quota_read(path,uid)
    for user,value in old['users'].items():
        require(user in new['users'] and new['users'][user]['used_bytes']>=value['used_bytes']
                and new['users'][user]['last_reset_epoch_secs']==value['last_reset_epoch_secs'],
                'candidate reset or lost persisted quota state')


@contextmanager
def isolated_site_origin(root, settings, identity):
    """Existing Nginx, transiently inside the already private Update namespace.

    Candidate TOML stays byte-identical. Every Nginx write is confined to the
    existing private root; no host Nginx configuration or service is touched.
    """
    if settings['web']['vhosts'][0]['decoy']['mode'] != 'http_upstream':
        yield
        return
    origin_port = decoy_origin_port(settings['web']['vhosts'][0]['decoy'])
    directory = root/str(SITE_ROOT).lstrip('/')
    site_identity(directory)
    executable = root/'usr/sbin/nginx'; safe_path(executable)
    config = root/'run/site-origin.conf'
    runtime = root/'run/site-origin'; runtime.mkdir(mode=0o700)
    uid = 65533 if identity['uid'] == 65534 else 65534
    gid = 65533 if identity['gid'] == 65534 else 65534
    os.chown(runtime,uid,gid)
    temporary = ''.join(f'{kind}_temp_path {kind};\n' for kind in
                        ('client_body','proxy','fastcgi','uwsgi','scgi'))
    source = ('worker_processes 1; pid /run/site-origin/nginx.pid; lock_file /run/site-origin/nginx.lock;\n'
              'error_log /run/site-origin/error.log crit;\nevents { worker_connections 256; }\n'
              'http { access_log off;\n'+temporary+render_site_server(port=origin_port)+'}\n')
    update_write(config,source.encode(),0o644)
    # A distinct numeric UID, no capabilities and the same private chroot keep
    # even a compromised candidate away from the trusted origin and host files.
    command = ['chroot',str(root),'/usr/bin/setpriv','--no-new-privs','--bounding-set=-all',
               '--inh-caps=-all','--ambient-caps=-all','--reuid='+str(uid),'--regid='+str(gid),
               '--clear-groups','/usr/sbin/nginx','-p','/run/site-origin/',
               '-c','/run/site-origin.conf','-e','/run/site-origin/error.log']
    update_run([*command,'-t'],timeout=15,maximum=16384)
    process = subprocess.Popen([*command,'-g','daemon off; master_process off;'],
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic()+10
        while True:
            require(process.poll() is None, 'private site origin exited')
            try:
                with socket.create_connection(('127.0.0.1',origin_port),timeout=.1): break
            except OSError:
                require(time.monotonic()<deadline, 'private site origin readiness failed'); time.sleep(.05)
        yield
    finally:
        if process.poll() is None: process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(); raise ValueError('private site origin shutdown failed') from None
        require(process.returncode == 0, 'private site origin failed')


class UpdateIsolation:
    """Trusted private root + mount/net/PID namespace + resource cgroup."""
    def __init__(self, layout, tree): self.layout=layout; self.tree=tree

    def prepare(self, directory, binary, source=None, index=None):
        root=Path(directory)
        require(not os.path.lexists(root)); root.mkdir(0o700)
        for relative in ('usr','usr/bin','usr/sbin','usr/local','usr/local/bin','etc','etc/telemt',
                         'var','var/lib','proc','tmp','run','dev','lib','lib64'):
            (root/relative).mkdir(mode=0o755)
            (root/relative).chmod(0o755)
        update_copy_stream(binary,root/'usr/local/bin/telemt',0o755)
        update_copy_stream(self.layout.config,root/'etc/telemt/telemt.toml',0o640)
        os.chown(root/'etc/telemt/telemt.toml',0,self.tree.gid)
        http_origin = read_config(self.layout.config)['web']['vhosts'][0]['decoy']['mode'] == 'http_upstream'
        if source: self.tree.clone(source,root/'var/lib/telemt',index)
        else:
            for relative in ('var/lib/telemt','var/lib/telemt/state','var/lib/telemt/public'):
                (root/relative).mkdir(mode=0o750)
                (root/relative).chmod(0o750)
                os.chown(root/relative,self.tree.uid if relative.endswith('/state') else 0,self.tree.gid)
            if not http_origin:
                update_copy_stream(self.layout.data/'public/index.html',root/'var/lib/telemt/public/index.html',0o440)
                os.chown(root/'var/lib/telemt/public/index.html',0,self.tree.gid)
        if http_origin:
            original = self.layout.path(SITE_ROOT); digest = site_identity(original)
            target = root/str(SITE_ROOT).lstrip('/'); target.mkdir(mode=0o755,parents=True)
            for parent in (target,*target.parents):
                if parent == root: break
                parent.chmod(0o755)
            for path in sorted(original.iterdir()): update_copy_stream(path,target/path.name,0o644)
            require(site_identity(target) == digest, 'private site copy differs')
        # Only fixed trusted Ubuntu tooling is inspected with ldd. Never invoke
        # ldd on the candidate (ldd is an executable-code hazard for unknown ELF).
        tools={name:Path(shutil.which(name) or '') for name in
               ('setpriv','conntrack','nft','iptables','ip6tables','iptables-save','ip6tables-save')
               + (('nginx',) if http_origin else ())}
        libraries=set()
        for name,path in tools.items():
            require(path.is_absolute(), 'isolation tooling unavailable')
            real=path.resolve(strict=True); safe_path(real)
            destination=root/('usr/bin/setpriv' if name=='setpriv' else 'usr/sbin/'+name)
            update_copy_stream(real,destination,0o755)
            raw=update_run(['ldd',str(real)],maximum=65536).decode()
            libraries.update(re.findall(r'(/[^\s()]+)',raw))
        arch='x86_64-linux-gnu' if update_architecture()=='x86_64' else 'aarch64-linux-gnu'
        for name in ('libc.so.6','libm.so.6','libgcc_s.so.1','libpthread.so.0','libdl.so.2','librt.so.1'):
            path=Path('/usr/lib',arch,name)
            require(path.exists(), 'GNU isolation library unavailable'); libraries.add(str(path))
        libraries.add('/lib64/ld-linux-x86-64.so.2' if arch.startswith('x86') else '/lib/ld-linux-aarch64.so.1')
        for path in sorted(libraries):
            original=Path(path); real=original.resolve(strict=True); safe_path(real)
            destination=root/str(original).lstrip('/')
            destination.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
            for parent in destination.parents:
                if parent==root: break
                parent.chmod(0o755)
            if not destination.exists(): update_copy_stream(real,destination,0o755)
        extensions=Path('/usr/lib',arch,'xtables')
        require(extensions.is_dir())
        modules=sorted(extensions.glob('*.so'))
        require(0<len(modules)<=256)
        target=root/'usr/lib'/arch/'xtables'; target.mkdir(mode=0o755,parents=True,exist_ok=True)
        for parent in (target,*target.parents):
            if parent==root: break
            parent.chmod(0o755)
        for module in modules: update_copy_stream(module.resolve(strict=True),target/module.name,0o755)
        os.mknod(root/'dev/null',stat.S_IFCHR|0o666,os.makedev(1,3))
        (root/'dev/null').chmod(0o666)
        (root/'tmp').chmod(0o1777)
        update_write_json(root/'isolation-identity.json',dict(schema=1,uid=self.tree.uid,gid=self.tree.gid))
        return root

    @staticmethod
    def unit(root): return 'telemt-manager-isolated-'+hashlib.sha256(str(root).encode()).hexdigest()[:32]

    def quiet(self, backup):
        for name in ('precheck','rehearsal'):
            self.quiesce(Path(backup)/name)

    def quiesce(self,root):
        unit=self.unit(root)+'.service'
        raw=update_run(['systemctl','show',unit,'-pLoadState','-pActiveState','-pControlGroup'],accepted=(0,1)).decode()
        value=dict(line.split('=',1) for line in raw.splitlines())
        require(set(value)=={'LoadState','ActiveState','ControlGroup'})
        if value['LoadState']=='not-found': require(value['ActiveState']=='inactive'); return
        update_run(['systemctl','stop',unit],timeout=20)
        if value['ControlGroup']:
            path=Path('/sys/fs/cgroup')/value['ControlGroup'].lstrip('/')
            require(not path.exists() or not (path/'cgroup.procs').read_text().strip(), 'private candidate cgroup remains')

    def run(self, root, version, rehearsal=False, parse_only=False):
        unit=self.unit(root)
        helper_path=str(Path(__file__).resolve())
        arguments=['systemd-run','--quiet','--wait','--pipe','--collect','--unit='+unit,
            '--property=MemoryMax=1G','--property=TasksMax=4096','--property=RuntimeMaxSec=180',
            '--property=CPUQuota=200%', '--property=IOWriteBandwidthMax='+str(root)+' 4194304',
            '--property=TimeoutStopSec=10','--property=SendSIGKILL=yes',
            '--property=NoNewPrivileges=yes', 'unshare','--mount','--net','--pid','--fork',
            '--kill-child=SIGKILL','--mount-proc','--propagation=private',
            '/usr/bin/python3',helper_path,'update-isolated-run',str(root),version,
            'parseonly' if parse_only else ('rehearsal' if rehearsal else 'precheck')]
        try: update_run(arguments,timeout=190,maximum=1024*1024)
        except BaseException:
            # Stop the entire private cgroup even if the controlling CLI dies.
            try: update_run(['systemctl','stop',unit+'.service'],timeout=15)
            except (ValueError,OSError,subprocess.SubprocessError): pass
            try:
                stage=update_json(update_read(Path(root)/'probe-stage.json',4096),4096)
                update_exact(stage,{'stage'})
                require(stage['stage'] in ('namespace','version','parser','unknown-key','quota-baseline',
                    'readiness','listener','capability','WEB','WEB-bootstrap','WEB-Hello','WEB-session-replay',
                    'WEB-uplink','WEB-downlink','WEB-close','shutdown','firewall','quota-readback','complete'))
                print('Isolated probe failed at trusted stage: '+stage['stage'],file=sys.stderr,flush=True)
            except (ValueError,OSError): pass
            raise


def update_isolated_io_contract(raw):
    # systemd resolves the trusted IOWriteBandwidthMax path to its backing
    # block device, which need not equal the filesystem's st_dev (partitions).
    # This leaf receives exactly one limit; reject missing/extra/malformed rows
    # and verify the effective contract without guessing the device identity.
    rows=raw.splitlines()
    require(len(rows)==1, 'private candidate disk resource limit unavailable')
    fields=rows[0].split()
    require(len(fields)==5 and re.fullmatch(r'[0-9]+:[0-9]+',fields[0]) is not None
            and set(fields[1:])=={'rbps=max','wbps=4194304','riops=max','wiops=max'},
            'private candidate disk resource limit unavailable')


def update_isolated_run(root, expected_version, mode):
    require(os.geteuid()==0 and mode in ('precheck','rehearsal','parseonly'))
    root=Path(root); update_private_directory(root); update_version(expected_version)
    identity=update_json(update_read(root/'isolation-identity.json',4096),4096)
    update_exact(identity,{'schema','uid','gid'})
    require(identity['schema']==1 and all(type(identity[k]) is int and identity[k]>0 for k in ('uid','gid')))
    # The inherited namespace must be genuinely private, not an accidental host
    # fallback. PID 1 here is the trusted namespace supervisor.
    require(os.getpid()==1, 'private PID namespace unavailable')
    cgroup_line=Path('/proc/self/cgroup').read_text().splitlines()
    require(len(cgroup_line)==1 and cgroup_line[0].startswith('0::/'))
    cgroup=Path('/sys/fs/cgroup')/cgroup_line[0][4:]
    require((cgroup/'memory.max').read_text().strip()==str(1024**3)
            and (cgroup/'pids.max').read_text().strip()=='4096')
    cpu=(cgroup/'cpu.max').read_text().split(); require(len(cpu)==2 and cpu[0].isdigit() and int(cpu[0])==2*int(cpu[1]))
    update_isolated_io_contract((cgroup/'io.max').read_text())
    # Never pass the manager's HTTP/proxy/GitHub credentials into a candidate.
    os.environ.clear(); os.environ.update(PATH='/usr/sbin:/usr/bin:/sbin:/bin',LANG='C',HOME='/var/lib/telemt')
    # The outer parent stays private 0700. Inside chroot, the real telemt UID
    # needs to traverse /; making the child root readable does not expose its
    # protected outer parent or any host filesystem.
    root.chmod(0o755)
    def checkpoint(name): update_write_json(root/'probe-stage.json',dict(stage=name))
    checkpoint('namespace')
    update_run(['ip','link','set','lo','up'])
    update_run(['mount','-t','proc','proc',str(root/'proc')])
    config=root/'etc/telemt/telemt.toml'; before=update_hash(config)
    settings=read_config(config); runtime_contract(config,'/var/lib/telemt')
    command=['chroot',str(root),'/usr/bin/setpriv','--no-new-privs','--bounding-set=-all,+net_admin',
        '--inh-caps=+net_admin','--ambient-caps=+net_admin','--reuid='+str(identity['uid']),
        '--regid='+str(identity['gid']),'--clear-groups','/usr/local/bin/telemt']
    checkpoint('version')
    actual=update_run(command+['--version'],timeout=10,maximum=4096).decode().strip()
    require(actual in ('Telemt '+expected_version,'telemt '+expected_version), 'isolated candidate version mismatch')
    print('Isolated official binary version: '+expected_version,flush=True)
    checkpoint('parser')
    update_run(command+['healthcheck','/etc/telemt/telemt.toml'],timeout=60)
    probe=root/'etc/telemt/unknown.toml'
    update_write(probe,b'__telemt_web_manager_unknown_contract = true\n'+update_read(config,UPDATE_CHUNK,(0o640,)),0o640)
    os.chown(probe,0,identity['gid'])
    negative=command+['healthcheck','/etc/telemt/unknown.toml']
    checkpoint('unknown-key')
    rejected=False
    try: update_run(negative,timeout=60)
    except UpdateCommandFailed as error: rejected=error.code==1
    require(rejected and update_hash(config)==before, 'candidate parsing/config preservation failed')
    if mode=='parseonly':
        print('Isolated installed version and strict immutable TOML parser: OK'); return
    checkpoint('quota-baseline')
    quota_path=root/'var/lib/telemt/state/telemt.limit.json'
    old_quota=update_quota_read(quota_path,identity['uid']) if os.path.lexists(quota_path) else None
    with isolated_site_origin(root,settings,identity):
        for cycle in range(2 if mode=='rehearsal' else 1):
            process=subprocess.Popen(command+['/etc/telemt/telemt.toml'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                     start_new_session=True,env=dict(os.environ,PATH='/usr/sbin:/usr/bin:/sbin:/bin'))
            os.set_blocking(process.stdout.fileno(),False); raw=bytearray()
            def drain():
                while True:
                    try: block=os.read(process.stdout.fileno(),65536)
                    except BlockingIOError: break
                    if not block: break
                    raw.extend(block); require(len(raw)<=16*UPDATE_CHUNK, 'private candidate log flood')
            try:
                checkpoint('readiness')
                deadline=time.monotonic()+45
                while time.monotonic()<deadline:
                    drain(); require(process.poll() is None, 'private candidate exited')
                    try:
                        status,_,body=UpdateWEBProbe(settings).request('GET','/')
                        if status==200: break
                    except OSError: pass
                    time.sleep(.1)
                else: raise ValueError('private candidate readiness timeout')
                require(update_hash(root/(str(SITE_ROOT).lstrip('/')+'/index.html' if settings['web']['vhosts'][0]['decoy']['mode']=='http_upstream' else 'var/lib/telemt/public/index.html'),256*1024)==
                        dict(size=len(body),sha256=hashlib.sha256(body).hexdigest()), 'private index response differs')
                checkpoint('listener')
                listeners=update_run(['ss','-H','-ltnp']).decode().splitlines()
                owned=[line for line in listeners if 'pid='+str(process.pid)+',' in line]
                require(len(owned)==1 and '127.0.0.1:18080 ' in owned[0])
                checkpoint('capability')
                require(re.search(r'^CapEff:\s+0000000000001000$',Path('/proc',str(process.pid),'status').read_text(),re.M))
                checkpoint('WEB')
                UpdateWEBProbe(settings,checkpoint=checkpoint).run(full=True); drain()
                start=time.monotonic()
                while time.monotonic()-start<10:
                    drain(); require(process.poll() is None); time.sleep(.2)
            finally:
                if sys.exc_info()[0] is None: checkpoint('shutdown')
                if process.poll() is None: process.send_signal(signal.SIGTERM)
                end=time.monotonic()+40
                while process.poll() is None and time.monotonic()<end: drain(); time.sleep(.1)
                if process.poll() is None: os.killpg(process.pid,signal.SIGKILL); process.wait(); raise ValueError('candidate private shutdown failed')
                drain(); process.stdout.close()
            require(process.returncode==0 and classify_records(raw.decode().splitlines())==0)
            checkpoint('firewall')
            firewall=b'\n'.join(update_run(['chroot',str(root),'/usr/sbin/'+name, *arguments])
                for name,arguments in (('nft',['list','ruleset']),('iptables-save',[]),('ip6tables-save',[])))
            require(not re.search(rb'TELEMT_|telemt_conntrack',firewall), 'private firewall cleanup failed')
            checkpoint('quota-readback')
            update_quota_preserve(old_quota,quota_path,identity['uid'])
    require(update_hash(config)==before)
    checkpoint('complete')
    print('Isolated exact version, strict parser, WEB/replay/bounded poll/Pong/close, quota and shutdown: OK')


def main():
    command, *args = sys.argv[1:]
    if command.startswith('update-'):
        update_command(command,args)
    elif command == 'site-generate':
        print(site_generate(*args))
    elif command == 'site-identity':
        print(site_identity(*args))
    elif command == 'site-bound':
        value=site_bound_identity(*args)
        if value: print(value)
    elif command == 'decoy-mode':
        c=read_config(args[0]); managed_web_contract(c,c['general']['data_path'])
        print(c['web']['vhosts'][0]['decoy']['mode'])
    elif command == 'decoy-port':
        c=read_config(args[0]); managed_web_contract(c,c['general']['data_path'])
        print(decoy_origin_port(c['web']['vhosts'][0]['decoy']))
    elif command == "semver":
        _, pre = semver(args[0])
        require(len(args) == 1 or (args[1] == "stable" and not pre))
    elif command == "version-compare":
        print(version_compare(*args))
    elif command == "nginx-plan":
        nginx_plan(*args[:4], manifest=args[4] if len(args) > 4 else None)
    elif command == 'nginx-site-plan':
        require(len(args) in (5,6,7))
        nginx_plan(*args[:4],site_digest=args[4],
                   site_port=int(args[5]) if len(args)>=6 else 18081,
                   manifest=args[6] if len(args)==7 else None)
    elif command == "nginx-uninstall-plan":
        nginx_plan(*args, uninstall=True)
    elif command == "nginx-keepalive-plan":
        nginx_keepalive_plan(*args)
    elif command == "acme-plan":
        acme_plan(*args)
    elif command == "port80-config":
        port80_config(args[0])
    elif command == "config-info":
        config_info(*args)
    elif command == "web-link-validate":
        current_web_link(*args)
    elif command == "web-link-display":
        display_web_link(*args)
    elif command == "dns":
        dns_check(Path(args[0]).read_text(), Path(args[1]).read_text(), args[2])
    elif command == "domain":
        domain(args[0])
    elif command == "ipv4":
        ipv4(args[0])
    elif command == "safe-path":
        safe_path(args[0])
    elif command == "lock-path":
        lock_path(args[0])
    elif command == "fresh-init":
        fresh_init(*args)
    elif command == "fresh-account-create":
        fresh_account_create(*args)
    elif command == "fresh-mkdir":
        fresh_mkdir(*args)
    elif command == "fresh-verify":
        fresh_verify(*args)
    elif command == "fresh-cleanup-dirs":
        fresh_cleanup_dirs(*args)
    elif command == "fresh-cleanup-account":
        fresh_cleanup_account(*args)
    elif command == "certificate-paths":
        certificate_paths(*args)
    elif command == "socks-address":
        socks_address(args[0])
    elif command == "extract-binary":
        extract_binary(*args)
    elif command == "runtime-contract":
        runtime_contract(*args)
    elif command == "renewal-contract":
        renewal_contract(*args)
    elif command == "renewal-kind":
        renewal_kind(*args)
    elif command == "acme-state":
        acme_state(*args)
    elif command == "certificate-record-check":
        certificate_record_check(*args)
    elif command == "certificate-record-stage":
        certificate_record_stage(*args)
    elif command == "certificate-only-state":
        certificate_only_state(*args)
    elif command == "uninstall-plan":
        uninstall_plan(*args)
    elif command == "uninstall-backup":
        uninstall_backup(*args)
    elif command == "uninstall-refresh":
        uninstall_refresh(*args)
    elif command == "uninstall-quiet":
        uninstall_quiet(*args)
    elif command == "uninstall-remove":
        uninstall_remove(*args)
    elif command == "uninstall-account-remove":
        uninstall_account_remove(*args)
    elif command == "uninstall-restore":
        uninstall_restore(*args)
    elif command == "planned-unlink":
        planned_unlink(*args)
    elif command == "certificate-cleanup-plan":
        certificate_cleanup_plan(*args)
    elif command == "certificate-cleanup-remove":
        certificate_cleanup_remove(*args)
    elif command == "classify":
        require(not args)
        return classify(sys.stdin.read())
    elif command == "classify-journal":
        require(not args)
        return classify_journal(sys.stdin.read())
    else:
        raise ValueError("unknown helper command")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except NginxDomainInUse:
        # Fixed protocol with the shell planner; never transmit exception text.
        sys.exit(20)
    except (ValueError, OSError, KeyError, TypeError, AttributeError, IndexError, tarfile.TarError, subprocess.SubprocessError):
        # Config parse errors may contain credentials. Never echo exception text.
        if len(sys.argv)>1 and sys.argv[1] in ('update-universal','update-recover','web-link-display') and presentation_language() == 'ru':
            print("Проверка безопасности не пройдена. Автоматическое изменение остановлено; требуется ручная проверка. Секреты не показаны.", file=sys.stderr)
        else:
            print("Safety validation failed; manual review required (no credentials displayed).", file=sys.stderr)
        sys.exit(1)
