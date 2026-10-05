#!/usr/bin/env python3
"""Strict, read-only parsers and staged Nginx plans. Python 3.11+ stdlib only."""
# This canonical header is also the install.sh downloaded-pair identity marker.
import base64
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
    require(value['schema'] == 1 and len(value['roots']) == 3)
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
    require(len(roots) == 3 and len(set(roots)) == 3)
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
        config, data, state = map(Path, value['roots'])
        allowed = {config, data, data / 'public', data / 'state', state}
        directory = Path(directory)
        require(directory in allowed and directory.is_absolute() and mode in ('0750', '0700'))
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
    addresses = [x.strip() for x in a_text.splitlines() if x.strip()]
    # dig +short may include CNAMEs. Aliases and multiple addresses need review.
    require(addresses == [expected], "DNS A missing, ambiguous or mismatching")
    for item in aaaa_text.splitlines():
        if item.strip():
            address = ipaddress.ip_address(item.strip())
            require(address.version == 6 and address.ipv4_mapped is None,
                    "DNS AAAA is not a real IPv6 address")
            raise ValueError("real DNS AAAA exists; IPv6 ingress needs manual review")


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

    def read(self, path):
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
                        node.children.extend(self.read(item))
            require(not nested)
            return nodes, len(source)

        nodes, _ = parse()
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


def nginx_plan(root, host, output, acme_root="/var/lib/telemt-web-manager-acme", uninstall=False):
    domain(host)
    parser = Nginx(root)
    nodes = parser.read(Path(root) / "nginx.conf")
    streams, https = exact(nodes, "stream"), exact(nodes, "http")
    require(len(streams) == len(https) == 1)
    stream, http = streams[0], https[0]
    require(all(n.args[0] in ("map", "upstream", "server") for n in expand(stream.children)),
            "unknown stream context directive")
    maps = exact(stream.children, "map")
    routers = exact(stream.children, "server")
    require(len(maps) == len(routers) == 1)
    mapping, router = maps[0], routers[0]
    require(len(mapping.args) == 3 and mapping.args[1] == "$ssl_preread_server_name"
            and re.fullmatch(r"\$[a-zA-Z_][a-zA-Z_0-9]*", mapping.args[2]))
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
            require(host not in n.args[1:])
        if n.args[0] == "listen" and n not in exact(router.children, "listen"):
            require(len(n.args) >= 2)
            address = n.args[1]
            require(re.fullmatch(r"[0-9]+|[0-9.]+:[0-9]+|\[[0-9a-fA-F:]+\]:[0-9]+|unix:/[^\s\\$]+", address),
                    "ambiguous Nginx listen address")
            if not address.startswith("unix:"):
                require(int(address.rsplit(":", 1)[-1]) not in (443, 7444, 18080))
    edits = {}
    if existing or owned or vhost.exists():
        require(len(existing) == len(owned) == 1 and vhost.exists())
        require(existing[0].args == [host, "twm_frontend"])
        require([n.args for n in expand(owned[0].children)] == [["server", "127.0.0.1:7444"]])
        require(vhost.read_text() == render_vhost(host), "managed Nginx vhost differs; manual review required")
    else:
        source = parser.sources[mapping.path]
        require(mapping.path == stream.path or mapping.path.is_relative_to(parser.root))
        edits[mapping.path] = source[:mapping.close] + f"    {host} twm_frontend; # telemt-web-manager\n" + source[mapping.close:]
        # Append upstream in the same physical file directly after the map block.
        shifted = mapping.close + len(f"    {host} twm_frontend; # telemt-web-manager\n") + 1
        content = edits[mapping.path]
        edits[mapping.path] = content[:shifted] + "\n# telemt-web-manager\nupstream twm_frontend { server 127.0.0.1:7444; }\n" + content[shifted:]
        edits[vhost] = render_vhost(host)
    if uninstall:
        require(len(existing) == len(owned) == 1 and vhost.exists())
        require([n for n in entries if n.args[1] == "twm_frontend"] == existing,
                "managed upstream shared by another route")
        require(sum("twm_frontend" in n.args for n in walk(nodes)) == 2)
        managed,ranges = nginx_owned_stream(parser,host,stream)
        for path, spans in ranges.items():
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
        directives = list(expand(server.children))
        names = exact(server.children, "server_name")
        require(len(names) == 1)
        for name in names[0].args[1:]:
            if name != "_":
                domain(name) # No wildcard/regex/escaped/dynamic name precedence.
            require(name != host or server.path.name == "telemt-web-manager.conf")
        listens = exact(server.children, "listen")
        if not any(n.args[1] in ("80", "0.0.0.0:80", "[::]:80") for n in listens):
            continue
        require(all(n.children is None for n in directives))
        require(len(directives) == len(listens) + 2)
        require(len(listens) in (1, 2)
                and sum(n.args in (["listen", "80"], ["listen", "0.0.0.0:80"]) for n in listens) == 1)
        require(len({tuple(n.args) for n in listens}) == len(listens)
                and all(n.args in (["listen", "80"], ["listen", "0.0.0.0:80"],
                                   ["listen", "[::]:80"]) for n in listens))
        require([n.args for n in directives if n.args[0] == "return"]
                == [["return", "301", "https://$host$request_uri"]])
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


def render_vhost(host):
    return f'''# Managed by telemt-web-manager v1. Manual changes require review.
server {{
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
        proxy_pass http://127.0.0.1:18080;
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
'''


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
    require(decoy.get("mode") == "static_directory"
            and decoy.get("directory") == str(Path(data) / "public")
            and decoy.get("index", "index.html") == "index.html", "decoy contract changed")
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
    anchors = uninstall_objects([str(data), str(data / 'public'), str(data / 'public/index.html')],
                                account, recursive=False)
    for record, directory, mode in zip(anchors, (True, True, False), (0o750, 0o750, 0o440)):
        require(record['directory'] == directory and record['uid'] in (0, os.geteuid())
                and record['gid'] == int(account['user'][3]) and record['mode'] == mode,
                'managed DATA anchor changed')
    marker=data/'.telemt-web-manager-generation.json'
    if marker.exists(): anchors += uninstall_objects([str(marker)],account,recursive=False)
    return records + anchors


def uninstall_plan(output, binary, config, unit, data, state, nginx_root, cert_root, webroot):
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
    data, state = map(Path, value['roots'][3:])
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
    binary, config, unit, data, state = value['roots']
    # After quiescence every object must still match the authoritative backup.
    extra=uninstall_update_paths(value['roots'])
    require(uninstall_objects(value['roots'] + extra, value['account']) == value['objects'])
    remove = {r['path']: r for r in value['objects'] if r['path'] == binary or r['path'] == unit
              or Path(r['path']).is_relative_to(config) or Path(r['path']).is_relative_to(data)
              or r['path'] in (str(Path(state,'manifest.json')),str(Path(state,'web-link.txt')),
                              str(Path(state,'telemt-release.json')),str(Path(state,'telemt-generation.json')),
                              str(Path(state,'update-journal.json')))
              or any(Path(r['path']).is_relative_to(p) for p in extra)}
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
    binary, config, unit, data, state = value['roots']
    require(all(not os.path.lexists(p) for p in (binary,config,unit,data,Path(state,'manifest.json'),Path(state,'web-link.txt'))))
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
    require(len(plan['edits']) == 2)  # Core WEB integration has already gone.
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


def display_web_link(state, config):
    # Keep validation-only CLI silent; only this explicit terminal path prints.
    require(sys.stdin.isatty() and sys.stdout.isatty())
    link = current_web_link(state, config)
    color = os.environ.get('TERM', '') != 'dumb' and not os.environ.get('NO_COLOR')
    header, cyan, warning, reset = ('\033[1;32m', '\033[96m', '\033[33m', '\033[0m') if color else ('',) * 4
    rule = '=' * 40
    print(f'{header}{rule}\n        TELEGRAM WEB PROXY\n{rule}{reset}\n')
    print('CURRENT CONNECTION LINK:\n')
    print(f'{cyan}{link}{reset}\n')
    print(f'{warning}WARNING: This link contains a bearer secret.\nStore it securely and do not share it.{reset}\n')
    print(f'Saved locally:\n  {Path(state) / "web-link.txt"}\n\n{rule}')


COVER_BUNDLE = {
    "schema": 1,
    "sites": [
        {
            "id": 'site-02',
            "size": 2454,
            "sha256": 'cbc8bf570ee6cecf5ad2089b87d31ee5502f4b19abe65de8af6767cccf0f67eb',
            "html": """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BuildRight Co. — Under Construction</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #f4f5f7;
    font-family: Georgia, 'Times New Roman', serif;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 2rem;
  }
  .card {
    background: #ffffff;
    border-radius: 4px;
    box-shadow: 0 2px 24px rgba(0,0,0,0.08);
    padding: 3.5rem 3rem;
    max-width: 540px;
    width: 100%;
    text-align: center;
    border-top: 5px solid #f4a100;
  }
  .icon {
    font-size: 4rem;
    margin-bottom: 1.5rem;
    line-height: 1;
  }
  h1 {
    font-size: 2rem;
    color: #1a1a2e;
    font-weight: 700;
    margin-bottom: 0.75rem;
    letter-spacing: -0.5px;
  }
  .subtitle {
    font-size: 1rem;
    color: #555;
    line-height: 1.7;
    margin-bottom: 2rem;
  }
  .tape {
    background: #f4a100;
    color: #1a1a2e;
    font-family: 'Courier New', monospace;
    font-weight: 700;
    font-size: 0.75rem;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    padding: 0.5rem 1.5rem;
    display: inline-block;
    transform: rotate(-1deg);
    margin-bottom: 2rem;
  }
  .progress-bar {
    background: #e9ecef;
    border-radius: 999px;
    height: 8px;
    overflow: hidden;
    margin-bottom: 0.5rem;
  }
  .progress-fill {
    background: linear-gradient(90deg, #f4a100, #ffca28);
    height: 100%;
    width: 68%;
    border-radius: 999px;
  }
  .progress-label {
    font-family: 'Courier New', monospace;
    font-size: 0.75rem;
    color: #999;
    text-align: right;
  }
  .brand {
    margin-top: 2rem;
    font-size: 0.8rem;
    color: #aaa;
    letter-spacing: 0.1em;
    font-family: Arial, sans-serif;
  }
</style>
</head>
<body>
  <div class="card">
    <div class="icon">&#128679;</div>
    <h1>Under Construction</h1>
    <p class="subtitle">
      We're working hard to build something great for you.
      Our team is putting the finishing touches on our new website.
    </p>
    <div class="tape">Work in progress</div>
    <div class="progress-bar"><div class="progress-fill"></div></div>
    <p class="progress-label">68% complete</p>
    <p class="brand">BuildRight Co. &mdash; Building Better Together</p>
  </div>
</body>
</html>
""",
        },
        {
            "id": 'site-03',
            "size": 2287,
            "sha256": '86e41f5b9be51dde377fc38efcf9268293d867f9cc5043831391fbcb9d074d41',
            "html": """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GreenLeaf Tech — Launching Soon</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: linear-gradient(135deg, #0f3d1e 0%, #1a5c2a 40%, #0d4d1f 100%);
    color: #d4edda;
    font-family: 'Trebuchet MS', Arial, sans-serif;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 2rem;
    text-align: center;
  }
  .leaf {
    font-size: 3rem;
    margin-bottom: 1rem;
    filter: drop-shadow(0 0 12px rgba(72,199,100,0.5));
  }
  .brand {
    font-size: 0.85rem;
    letter-spacing: 0.3em;
    text-transform: uppercase;
    color: #6fcf7c;
    margin-bottom: 3rem;
  }
  h1 {
    font-size: clamp(2.2rem, 7vw, 5rem);
    font-weight: 700;
    color: #ffffff;
    line-height: 1.1;
    margin-bottom: 1.5rem;
    text-shadow: 0 2px 20px rgba(0,0,0,0.4);
  }
  h1 span { color: #48c764; }
  .body-text {
    font-size: 1.1rem;
    color: #a8d5b0;
    max-width: 480px;
    line-height: 1.8;
    margin-bottom: 3rem;
  }
  .badge-row {
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
    justify-content: center;
    margin-bottom: 3rem;
  }
  .badge {
    background: rgba(72, 199, 100, 0.15);
    border: 1px solid rgba(72, 199, 100, 0.4);
    color: #6fcf7c;
    padding: 0.4rem 1.1rem;
    border-radius: 999px;
    font-size: 0.8rem;
    letter-spacing: 0.05em;
  }
  .footer-line {
    font-size: 0.75rem;
    color: #5a8c65;
    letter-spacing: 0.15em;
    text-transform: uppercase;
  }
</style>
</head>
<body>
  <div class="leaf">&#127807;</div>
  <p class="brand">GreenLeaf Tech</p>
  <h1>We're Launching<br><span>Soon</span></h1>
  <p class="body-text">
    We're building a greener future through sustainable technology.
    Our platform is almost ready — join us as we grow something remarkable.
  </p>
  <div class="badge-row">
    <span class="badge">Sustainable Cloud</span>
    <span class="badge">Carbon Neutral</span>
    <span class="badge">Open Source</span>
  </div>
  <p class="footer-line">GreenLeaf Tech &copy; 2025 &mdash; Growing Tomorrow, Today</p>
</body>
</html>
""",
        },
        {
            "id": 'site-04',
            "size": 3285,
            "sha256": '9ea160b849f434efb815b238d776d4f0fcdea821540d779d6b0c522971aa81bd',
            "html": """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Alex Chen — Portfolio Coming Soon</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: linear-gradient(160deg, #1a0533 0%, #2d1055 50%, #1e0840 100%);
    font-family: 'Palatino Linotype', Palatino, Georgia, serif;
    min-height: 100vh;
    display: grid;
    grid-template-columns: 1fr 1fr;
    align-items: center;
  }
  @media (max-width: 700px) {
    body { grid-template-columns: 1fr; padding: 3rem 2rem; }
    .right { display: none; }
  }
  .left {
    padding: 4rem;
    display: flex;
    flex-direction: column;
    justify-content: center;
  }
  .eyebrow {
    font-size: 0.75rem;
    letter-spacing: 0.3em;
    text-transform: uppercase;
    color: #b07eff;
    margin-bottom: 1.5rem;
  }
  h1 {
    font-size: clamp(2rem, 4vw, 3.5rem);
    color: #ffffff;
    line-height: 1.15;
    font-weight: 400;
    margin-bottom: 0.5rem;
  }
  h1 em {
    font-style: italic;
    color: #c89fff;
  }
  .role {
    font-size: 0.9rem;
    color: #9b6fcc;
    letter-spacing: 0.1em;
    margin-bottom: 2rem;
  }
  p {
    font-size: 1rem;
    color: #c4a8e8;
    line-height: 1.9;
    max-width: 380px;
    margin-bottom: 2.5rem;
  }
  .divider {
    width: 40px;
    height: 1px;
    background: #7c3aed;
    margin-bottom: 2.5rem;
  }
  .status {
    display: inline-flex;
    align-items: center;
    gap: 0.6rem;
    background: rgba(124, 58, 237, 0.2);
    border: 1px solid rgba(124, 58, 237, 0.5);
    padding: 0.5rem 1.2rem;
    border-radius: 4px;
    font-size: 0.8rem;
    color: #b07eff;
    letter-spacing: 0.08em;
  }
  .dot {
    width: 7px; height: 7px;
    background: #7c3aed;
    border-radius: 50%;
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }
  .right {
    padding: 4rem;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .art {
    width: 260px; height: 320px;
    border: 1px solid rgba(124,58,237,0.4);
    border-radius: 8px;
    background: rgba(124,58,237,0.08);
    position: relative;
    overflow: hidden;
  }
  .art::before {
    content: '';
    position: absolute;
    top: -40%; left: -40%;
    width: 180%; height: 180%;
    background: radial-gradient(circle, rgba(124,58,237,0.3) 0%, transparent 65%);
  }
  .art-label {
    position: absolute;
    bottom: 1.2rem; left: 1.2rem;
    font-size: 0.7rem;
    color: rgba(176,126,255,0.5);
    letter-spacing: 0.15em;
    text-transform: uppercase;
  }
</style>
</head>
<body>
  <div class="left">
    <p class="eyebrow">Portfolio</p>
    <h1>Alex Chen &mdash;<br><em>Designer</em></h1>
    <p class="role">UI / UX &nbsp;&bull;&nbsp; Brand Identity &nbsp;&bull;&nbsp; Motion</p>
    <div class="divider"></div>
    <p>
      Something carefully crafted is on the way. A new portfolio showcasing
      the intersection of form, function, and feeling. Coming soon.
    </p>
    <span class="status"><span class="dot"></span>Currently in development</span>
  </div>
  <div class="right">
    <div class="art">
      <div class="art-label">Work preview</div>
    </div>
  </div>
</body>
</html>
""",
        },
    ],
}

from html.parser import HTMLParser
import secrets

COVER_LIMIT = 32768
SERVICE_STATUS = b'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Service Status</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#101827;color:#e8eef7;font:16px system-ui,sans-serif}main{padding:3rem;border:1px solid #29364b;border-radius:20px;background:#172235;text-align:center}i{display:inline-block;width:12px;height:12px;border-radius:50%;background:#50d890;margin-right:10px}h1{font-size:1.5rem}p{color:#b4c2d6}</style></head><body><main><h1>Service Status</h1><p><i></i>All systems operational</p></main></body></html>\n'''


class CoverHTML(HTMLParser):
    """Small local HTML/CSS only; no executable or externally loaded content."""
    def handle_starttag(self, tag, attrs):
        require(tag in {'html','head','meta','title','style','body','main','div','span','p',
                        'h1','h2','h3','br','i','em','strong','section','footer'}, 'unsafe cover HTML')
        allowed = {'lang','charset','name','content','class','id'}
        require(all(key in allowed and value is not None for key,value in attrs), 'unsafe cover attribute')
        if tag == 'meta':
            require(all(key in {'charset','name','content'} for key,_ in attrs))
            require(not any(key == 'name' and value != 'viewport' for key,value in attrs))


def cover_assets(bundle=None):
    bundle = COVER_BUNDLE if bundle is None else bundle
    require(type(bundle) is dict and set(bundle) == {'schema','sites'} and type(bundle['schema']) is int
            and bundle['schema'] == 1 and type(bundle['sites']) is list and 1 <= len(bundle['sites']) <= 8,
            'invalid cover manifest')
    result = {}
    for item in bundle['sites']:
        require(type(item) is dict and set(item) == {'id','size','sha256','html'})
        require(type(item['id']) is str and re.fullmatch(r'site-[0-9]{2}', item['id'])
                and item['id'] not in result)
        require(type(item['size']) is int and 0 < item['size'] <= COVER_LIMIT
                and type(item['html']) is str and len(item['html']) <= COVER_LIMIT and type(item['sha256']) is str
                and re.fullmatch(r'[0-9a-f]{64}', item['sha256']))
        raw = item['html'].encode('utf-8')
        require(len(raw) == item['size'] and hashlib.sha256(raw).hexdigest() == item['sha256'],
                'cover integrity check failed')
        require(not re.search(r'url\s*\(|@import|expression\s*\(|\\|https?\s*:',item['html'],re.I),
                'external or active cover content')
        parser = CoverHTML(convert_charrefs=True); parser.feed(item['html']); parser.close()
        result[item['id']] = raw
    return result


def cover_choose(current=None):
    choices = [raw for raw in cover_assets().values() if raw != current]
    require(bool(choices), 'no different cover available')
    return secrets.choice(choices)


def cover_atomic(directory, raw, initial=False):
    """Anchored, bounded single-file publication with verified rollback bytes."""
    directory = Path(directory); path = directory/'index.html'; safe_path(path)
    require(0 < len(raw) <= COVER_LIMIT and not os.path.ismount(directory))
    parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = '.twm-cover-' + uuid.uuid4().hex
    old = None; published = False
    try:
        before = os.fstat(parent)
        require(before.st_uid == os.geteuid() and not before.st_mode & 0o022)
        if initial:
            require(not os.path.lexists(path), 'cover already exists')
        else:
            old = web_link_read(path, {0o440}, COVER_LIMIT)
            original = path.lstat()
            require(original.st_gid == before.st_gid)
        def publish(content):
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            with os.fdopen(fd,'wb') as output:
                os.fchown(output.fileno(), os.geteuid(), before.st_gid)
                os.fchmod(output.fileno(),0o440)
                output.write(content); output.flush(); os.fsync(output.fileno())
            require(os.fstat(parent).st_ino == directory.lstat().st_ino
                    and os.fstat(parent).st_dev == directory.lstat().st_dev)
            os.replace(temporary,'index.html',src_dir_fd=parent,dst_dir_fd=parent)
            os.fsync(parent)
        try:
            if old is not None: require(path.lstat() == original, 'cover changed concurrently')
            # Signals cannot interrupt publication/verification between durable bytes.
            with fresh_signal_window():
                published = True
                publish(raw)
                fd = os.open('index.html',os.O_RDONLY | os.O_NOFOLLOW,dir_fd=parent)
                try:
                    info = os.fstat(fd)
                    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.geteuid()
                            and info.st_gid == before.st_gid and stat.S_IMODE(info.st_mode) == 0o440)
                    require(os.read(fd,COVER_LIMIT+1) == raw, 'cover publication verification failed')
                finally: os.close(fd)
        except BaseException:
            try: os.unlink(temporary,dir_fd=parent)
            except FileNotFoundError: pass
            if published:
                if old is not None: publish(old)
                else:
                    try: os.unlink('index.html',dir_fd=parent); os.fsync(parent)
                    except FileNotFoundError: pass
            raise
    finally:
        try: os.unlink(temporary,dir_fd=parent)
        except FileNotFoundError: pass
        os.close(parent)


def cover_initial(directory, source=None):
    try:
        if source:
            raw = web_link_read(source,{0o440},COVER_LIMIT,owner=os.geteuid())
            require(raw in [SERVICE_STATUS,*cover_assets().values()], 'unknown staged cover')
        else: raw = cover_choose()
    except (ValueError,UnicodeError):
        print('Cover assets unavailable; using Service Status.',file=sys.stderr)
        raw = SERVICE_STATUS
    cover_atomic(directory,raw,initial=True)


def cover_change(state, config, data, mode, previous):
    current_web_link(state,config)  # Silent manager ownership/domain/secret proof.
    runtime_contract(config,data)
    account = fresh_identity(data)
    directory = Path(data)/'public'
    safe_path(directory)
    require(directory.lstat().st_uid == 0 and directory.lstat().st_gid == int(account['group'][2])
            and stat.S_IMODE(directory.lstat().st_mode) == 0o750)
    current = web_link_read(directory/'index.html',{0o440},COVER_LIMIT)
    known = [SERVICE_STATUS,*cover_assets().values()]
    require(current in known, 'Unknown current cover; manual review required')
    if mode == 'restore':
        raw = web_link_read(previous,{0o600},COVER_LIMIT)
        require(raw in known)
    else:
        require(mode in ('random','default'))
        raw = cover_choose(current) if mode == 'random' else SERVICE_STATUS
        require(not os.path.lexists(previous)); update_write(previous,current)
    cover_atomic(directory,raw)


class UpdateProgress:
    """Presentation only. Deadlines, samples and transaction authority stay in Engine."""
    def __init__(self, stream=None):
        self.stream = stream or sys.stdout
        self.enabled = self.stream.isatty() and os.environ.get('TERM','') != 'dumb'
        self.color = self.enabled and not os.environ.get('NO_COLOR')
        self.stage = None; self.line = False; self.failed = False

    def end_line(self):
        if self.line: print(file=self.stream,flush=True); self.line = False

    def event(self, stage, legacy):
        if not self.enabled: print(legacy,file=self.stream,flush=True); return
        if self.stage == stage: return
        self.end_line(); self.stage = stage
        labels = {1:'Verifying release',2:'Compatibility check',3:'Preparing safe update',
                  4:'Stability check',5:'Restart verification'}
        print(f'[{stage}/5] {labels[stage]}…',file=self.stream,flush=True)

    def wait(self, deadline, start, total):
        if not self.enabled:
            remaining = deadline-time.monotonic()
            if remaining > 0: time.sleep(remaining)
            return
        while True:
            now = time.monotonic(); elapsed = min(total,max(0,int(now-start)))
            filled = min(10,int(elapsed*10/max(1,total))); bar = '█'*filled+'░'*(10-filled)
            green,reset = ('\033[32m','\033[0m') if self.color else ('','')
            print(f'\r[{self.stage}/5] {green}[{bar}]{reset} {elapsed:3d} / {total} s — Please wait…',
                  end='',file=self.stream,flush=True); self.line = True
            if now >= deadline: break
            time.sleep(min(1,deadline-now))

    def sample(self, sample):
        if not self.enabled:
            print(f'Acceptance sample {sample}s: process, cgroup, path and current journal OK',file=self.stream,flush=True)

    def finish(self, message, failed=False):
        self.end_line()
        self.failed = self.failed or failed
        if self.enabled: print(('✗ ' if failed else '✓ ')+message,file=self.stream,flush=True)

    def log(self, message):
        self.end_line()
        print(message,file=self.stream,flush=True)



# Universal updater. These components share the canonical, atomically installed
# helper with the older parser APIs; bootstrap continues to install one pair.
UPDATE_SCHEMA = 1
UPSTREAM_REPOSITORY = dict(id=1125007401, full_name='telemt/telemt')
UPDATE_MANAGER_VERSION = '1.0.0'
BASELINE_VERSION = '3.5.12'
BASELINE_COMMIT = 'c4555e25f39dd5be200ccf6353f7d82bfcf89131'
BASELINE_HASHES = {
    'x86_64': ('92bfaa6177d87790bae79caea08d8ddddd0ca3ebc95545c1d62374897592c6c3',
               '53da315a9f61975913235f72c4adb413313089b966ffcca700653b4663d3d964'),
    'aarch64': ('16bfd0e78b746171b0434c935ca953358c88b43cfb0091d7b74cb982424202a3',
                '308271c73ece5d748aeab21680c10c2bea153ba29c83135b1b84aa79a394173c')}
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
            'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'telemt-web-manager/1.0.0'})
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
        request = urllib.request.Request(url, headers={'User-Agent': 'telemt-web-manager/1.0.0'})
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
            archive, binary = BASELINE_HASHES[value['architecture']]
            require(value['installed_version'] == BASELINE_VERSION and value['commit_sha'] == BASELINE_COMMIT
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
        value = dict(schema=UPDATE_SCHEMA, origin='official-release' if frozen else 'reviewed-baseline',
            repository=UPSTREAM_REPOSITORY, architecture=architecture, installed_version=BASELINE_VERSION,
            tag=BASELINE_VERSION, tag_object_sha=None, commit_sha=BASELINE_COMMIT, tag_verification=None,
            release=None, asset=None, checksum_asset=None, archive_sha256=BASELINE_HASHES[architecture][0],
            binary=update_hash(binary), installed_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
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
        require(update_read(manager,UPDATE_CHUNK,(0o755,)).startswith(b'#!/usr/bin/env bash\n# Telemt WEB Manager.'))
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
        with tempfile.TemporaryDirectory(prefix='twm-ownership-') as directory:
            output=Path(directory)/'nginx-plan.json'
            nginx_plan(nginx,host,output)
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
        require(update_hash(self.layout.binary)['sha256']==BASELINE_HASHES[update_architecture()][1],
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
        print('Verifying pristine baseline ownership and publishing recovery controls.',flush=True)
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
            print('Starting durable manager recovery barrier.',flush=True)
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
        if self.progress.enabled: print('Updating Telemt '+old['installed_version']+' → '+latest['version'],flush=True)
        require(comparison>=0, 'installed release is newer; automatic downgrade refused')
        if comparison==0:
            require(latest['version']==old['installed_version'], 'non-exact equal version requires manual review')
            if old['origin']=='official-release':
                require(all(old[k]==v for k,v in frozen.items()), 'same-version upstream identity changed')
            else: require(frozen['commit_sha']==BASELINE_COMMIT and frozen['asset']['sha256']==old['archive_sha256'])
            if not self.layout.receipt.exists(): old=self.migrate(old)
            print('already up to date; local receipt and objective health verified'); return
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
            if self.progress.enabled:
                self.progress.finish('Telemt updated successfully: '+old['installed_version']+' → '+new['installed_version'])
            else: print('Updated to '+new['installed_version']+'. TOML and deployment controls preserved byte-for-byte.')
        except BaseException:
            message = ('Update committed; housekeeping requires manual review.' if self.journal.value['phase']=='COMMITTED'
                       else 'Update failed at '+str(self.progress.stage)+'/5; validating rollback.')
            self.progress.finish(message,failed=True)
            if self.journal.value['phase']!='COMMITTED':
                self.journal.value['error']='validation-failed'; self.journal.publish()
                self.recover(force=True)
                raise
            self.journal.value['error']='cleanup-failed'; self.journal.publish()
            print('Update committed successfully. Retained generation cleanup requires manual review; new version remains active.',file=sys.stderr)

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
                print('Terminal generation is authoritative; housekeeping remains pending. Next mutation/bootstrap requires cleanup.',file=sys.stderr)
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
            self.progress.log('Rollback complete: old binary, full DATA, receipt and objective health restored.')
        except BaseException:
            if self.journal.value['phase']=='ROLLBACK_COMPLETE':
                self.journal.value['error']='cleanup-failed'
                try: self.journal.publish()
                except OSError:
                    if not boot: raise
                print('Old generation restored and healthy; retained evidence cleanup requires manual review.',file=sys.stderr)
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
            print('CRITICAL: start gate closed; backup and journal retained for manual review.',file=sys.stderr)
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
        print('Baseline migration rolled back; prior receipt absence and deployment preserved.')


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
    require(paths==[str(layout.binary),str(layout.config.parent),
                   str(layout.path('/etc/systemd/system/telemt.service')),str(layout.data),str(layout.state)])
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
                    engine.progress.finish('Update failed at stage '+str(engine.progress.stage)+'/5; no success reported.',failed=True)
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
        if source: self.tree.clone(source,root/'var/lib/telemt',index)
        else:
            for relative in ('var/lib/telemt','var/lib/telemt/state','var/lib/telemt/public'):
                (root/relative).mkdir(mode=0o750)
                (root/relative).chmod(0o750)
                os.chown(root/relative,self.tree.uid if relative.endswith('/state') else 0,self.tree.gid)
            update_copy_stream(self.layout.data/'public/index.html',root/'var/lib/telemt/public/index.html',0o440)
            os.chown(root/'var/lib/telemt/public/index.html',0,self.tree.gid)
        # Only fixed trusted Ubuntu tooling is inspected with ldd. Never invoke
        # ldd on the candidate (ldd is an executable-code hazard for unknown ELF).
        tools={name:Path(shutil.which(name) or '') for name in
               ('setpriv','conntrack','nft','iptables','ip6tables','iptables-save','ip6tables-save')}
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
            require(update_hash(root/'var/lib/telemt/public/index.html',256*1024)==
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
    elif command == "cover-initial":
        cover_initial(*args)
    elif command == "cover-change":
        cover_change(*args)
    elif command == "semver":
        _, pre = semver(args[0])
        require(len(args) == 1 or (args[1] == "stable" and not pre))
    elif command == "version-compare":
        print(version_compare(*args))
    elif command == "nginx-plan":
        nginx_plan(*args)
    elif command == "nginx-uninstall-plan":
        nginx_plan(*args, uninstall=True)
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
    except (ValueError, OSError, KeyError, TypeError, AttributeError, IndexError, tarfile.TarError, subprocess.SubprocessError):
        # Config parse errors may contain credentials. Never echo exception text.
        print("Safety validation failed; manual review required (no credentials displayed).", file=sys.stderr)
        sys.exit(1)
