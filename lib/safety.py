#!/usr/bin/env python3
"""Strict, read-only parsers and staged Nginx plans. Python 3.11+ stdlib only."""
import base64
import glob
import hashlib
import ipaddress
import json
import os
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
    c = tomllib.loads(Path(path).read_text())
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
        require(p.is_absolute() and p.is_relative_to(state) and ".." not in p.parts,
                "active state path escapes systemd sandbox; manual review required")


def renewal_contract(root, host, webroot):
    path = Path(root) / "renewal" / f"{domain(host)}.conf"
    safe_path(path)
    text = path.read_text()
    require(re.search(r"(?m)^authenticator\s*=\s*webroot\s*$", text))
    pattern = re.escape(str(webroot))
    require(re.search(rf"(?m)^webroot_path\s*=\s*{pattern},?\s*$", text))
    maps = re.findall(rf"(?m)^{re.escape(host)}\s*=\s*(.+)$", text)
    require(not maps or maps == [str(webroot)])


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

        def parse(nested=False, map_values=False):
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
                if not map_values:
                    require(re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]*", args[0]),
                            "escaped or unknown Nginx directive name")
                terminator, close = tokens[position]
                position += 1
                require(terminator != "}")
                children = None
                if terminator == "{":
                    children, close = parse(True, args[0] == "map")
                node = Node(args, children, path, start, close)
                nodes.append(node)
                if args[0] == "include":
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
        if node.args[0] == "include":
            yield from expand(node.children)
        else:
            yield node


def walk(nodes):
    for node in nodes:
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


def config_info(path):
    raw = Path(path).read_bytes()
    require(not re.search(rb"(?m)^\s*include\s*=", raw), "config includes need manual review")
    c = tomllib.loads(raw.decode())
    require(not any(k in c for k in ("include", "includes")), "config includes need manual review")
    server = c.get("server", {})
    listeners = server.get("listeners", [])
    require(len(listeners) == 1 and listeners[0].get("ip") == "127.0.0.1"
            and listeners[0].get("port") == 18080 and listeners[0].get("transport") == "web"
            and listeners[0].get("proxy_protocol", False) is False
            and listeners[0].get("web_client_ip_source") == "x_forwarded_for"
            and listeners[0].get("web_trusted_proxy_cidrs") == ["127.0.0.1/32"],
            "unsupported listener; manual review required")
    web = c.get("web", {})
    require(web.get("enabled") is True and web.get("carrier") == "https"
            and not web.get("carriers"), "unsupported WEB carrier")
    vhosts = web.get("vhosts", [])
    require(len(vhosts) == 1 and not vhosts[0].get("base_path"), "unsupported WEB scope")
    require(server.get("api", {}).get("enabled") is False, "enabled API needs manual review")
    host = domain(vhosts[0]["host"])
    upstreams = c.get("upstreams", [])
    require(len(upstreams) == 1, "ambiguous upstream configuration")
    upstream = upstreams[0]
    kind = upstream.get("type")
    require(kind in ("direct", "socks5"), "unsupported upstream")
    address = upstream.get("address", "")
    if kind == "socks5":
        socks_address(address)
        require(not upstream.get("username") and not upstream.get("password"), "SOCKS auth needs manual review")
    print(host)
    print(address if kind == "socks5" else "direct")


def classify(version, os_version, backend, text):
    # Only a whole known upstream warning with no extra error is downgraded.
    known = 0
    failures = 0
    warnings = 0
    for line in text.splitlines():
        if not re.search(r"\b(WARN|ERROR|FATAL|panic)\b", line, re.I):
            continue
        exact_error = "Chain 'TELEMT_NOTRACK' does not exist"
        expected = (version == "3.5.9" and os_version == "ubuntu:26.04"
                    and "nf_tables" in backend and "WARN" in line
                    and "Failed to reconcile conntrack firewall policy" in line
                    and "startup recovery failed:" in line and exact_error in line)
        # Permit repeated identical iptables messages, but no permission/other failures.
        remainder = line.split("startup recovery failed:", 1)[-1]
        remainder = remainder.replace("Failed to reconcile conntrack firewall policy", "")
        remainder = remainder.replace(exact_error, "")
        remainder = re.sub(r"ip6?tables v[0-9.]+ \(nf_tables\):", "", remainder)
        remainder = re.sub(r'''[\s;:."']''', "", remainder)
        if expected and not remainder:
            known += 1
        elif re.search(r"ERROR|FATAL|panic|conntrack|Operation not permitted|Permission denied", line, re.I):
            failures += 1
        else:
            warnings += 1
    print(f"logs: failures={failures}, warnings={warnings}, known_nonfatal={known}")
    return 1 if failures else 0


def main():
    command, *args = sys.argv[1:]
    if command == "nginx-plan":
        nginx_plan(*args)
    elif command == "acme-plan":
        acme_plan(*args)
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
    elif command == "classify":
        return classify(*args[:3], sys.stdin.read())
    else:
        raise ValueError("unknown helper command")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, TypeError, IndexError, tarfile.TarError):
        # Config parse errors may contain credentials. Never echo exception text.
        print("Safety validation failed; manual review required (no credentials displayed).", file=sys.stderr)
        sys.exit(1)
