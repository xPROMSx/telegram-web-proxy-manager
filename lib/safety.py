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
from contextlib import contextmanager
import stat
import tarfile
import re
import sys
import tomllib
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
        require(Path(root).is_absolute() and not os.path.lexists(root))
    safe_path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(dict(schema=1, roots=list(roots), directories=[], account=None,
                       pending_account=False, user_removed=False), output)


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
        require(all(not os.path.lexists(root) for root in roots))
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
        source = path.read_bytes().decode("utf-8")
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


def nginx_plan(root, host, output, acme_root="/var/lib/telemt-web-manager-acme"):
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
    snapshot = {str(p): hashlib.sha256(s.encode()).hexdigest() for p, s in parser.sources.items()}
    plan = {"snapshot": snapshot, "edits": [{"path": str(p), "content": s,
            "old": base64.b64encode(p.read_bytes()).decode() if p.exists() else None}
            for p, s in edits.items()]}
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
    raw = Path(path).read_bytes()
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


def classify(version, os_version, backend, text, records=None):
    # Old configs may emit ANSI SGR; new configs disable colors explicitly.
    # Strip only color sequences, not arbitrary control/error text.
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    if records is None:
        records = []
        for line in text.splitlines():
            if re.match(r"^(?:\d{4}-\d\d-\d\dT\S+\s+)?(?:TRACE|DEBUG|INFO|WARN|ERROR|FATAL|panic)\b", line, re.I):
                records.append(line)
            elif records:
                records[-1] += "\n" + line
            elif line.strip():
                records.append(line)
    require(all(isinstance(record, str) for record in records), "binary journal message requires review")
    helper_version = r"1\.8\.(?:10|11)"
    backend_ok = re.fullmatch(rf"iptables v{helper_version} \(nf_tables\)", backend) is not None
    diagnostic = (
        rf"(?P<tool>ip6?tables) v{helper_version} \(nf_tables\): "
        r"Chain 'TELEMT_NOTRACK' does not exist\.?"
        r"(?:\nTry \x60(?P=tool) -h' or '(?P=tool) --help' for more information\.)?"
    )
    warning = re.compile(
        r"^(?:\d{4}-\d\d-\d\dT[0-9:.]+(?:Z|[+-]\d\d:\d\d)\s+)?"
        r"WARN\s+(?:[A-Za-z_][A-Za-z_0-9]*(?:::[A-Za-z_][A-Za-z_0-9]*)*:\s+)?"
        r"Failed to reconcile conntrack firewall policy"
        r"(?:\s+generation=[0-9]+)?\s+error=startup recovery failed: (?P<payload>.+)$",
        re.S,
    )
    known = failures = warnings = 0
    for record in records:
        record = re.sub(r"\x1b\[[0-9;]*m", "", record)
        # Severity wins even if the record also contains the known warning.
        if re.search(r"\b(ERROR|FATAL|panic)\b(?![=])", record, re.I):
            failures += 1
            continue
        if not re.search(r"\bWARN\b", record, re.I):
            if re.search(r"Operation not permitted|Permission denied", record, re.I):
                failures += 1
            continue
        match = warning.fullmatch(record)
        diagnostics = match["payload"].split("; ") if match else []
        expected = (version == "3.5.9" and os_version in ("ubuntu:24.04", "ubuntu:26.04")
                    and backend_ok and diagnostics
                    and all(re.fullmatch(diagnostic, part) for part in diagnostics))
        if expected:
            known += 1
        elif re.search(r"conntrack|Operation not permitted|Permission denied", record, re.I):
            failures += 1
        else:
            warnings += 1
    print(f"logs: failures={failures}, warnings={warnings}, known_nonfatal={known}")
    return 1 if failures else 0


def classify_journal(version, os_version, backend, text):
    # Journald JSON preserves MESSAGE boundaries, including embedded newlines.
    # A continuation that looks like INFO must not hide extra stderr.
    records = [json.loads(line)["MESSAGE"] for line in text.splitlines() if line.strip()]
    return classify(version, os_version, backend, "", records)


def main():
    command, *args = sys.argv[1:]
    if command == "semver":
        _, pre = semver(args[0])
        require(len(args) == 1 or (args[1] == "stable" and not pre))
    elif command == "version-compare":
        print(version_compare(*args))
    elif command == "nginx-plan":
        nginx_plan(*args)
    elif command == "acme-plan":
        acme_plan(*args)
    elif command == "port80-config":
        port80_config(args[0])
    elif command == "config-info":
        config_info(*args)
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
    elif command == "classify":
        return classify(*args[:3], sys.stdin.read())
    elif command == "classify-journal":
        return classify_journal(*args[:3], sys.stdin.read())
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
