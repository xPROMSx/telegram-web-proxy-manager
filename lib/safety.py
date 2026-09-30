#!/usr/bin/env python3
"""Strict, read-only parsers and staged Nginx plans. Python 3.11+ stdlib only."""
import base64
import glob
import hashlib
import ipaddress
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


def require(ok, message="automatic nginx integration not possible"):
    if not ok:
        raise ValueError(message)


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
        self.root = Path(root).resolve()
        self.sources = {}
        self.stack = []

    def read(self, path):
        path = Path(path).resolve()
        require(path.is_relative_to(self.root), "Nginx include escapes config directory")
        require(path not in self.stack and path not in self.sources,
                "repeated or cyclic Nginx include")
        self.stack.append(path)
        source = path.read_bytes().decode("utf-8")
        require("\\" not in source, "escaped Nginx syntax needs manual review")
        self.sources[path] = source
        pattern = r'''\s+|\#[^\n]*|"[^"\n]*"|'[^'\n]*'|[{};]|[^\s{};"'\#]+'''
        tokens = []
        end = 0
        for match in re.finditer(pattern, source):
            require(match.start() == end)
            end = match.end()
            token = match.group()
            if not token.isspace() and not token.startswith("#"):
                tokens.append((token, match.start()))
        require(end == len(source))
        position = 0

        def parse(nested=False):
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
                terminator, close = tokens[position]
                position += 1
                require(terminator != "}")
                children = None
                if terminator == "{":
                    children, close = parse(True)
                node = Node(args, children, path, start, close)
                nodes.append(node)
                if args[0] == "include":
                    require(children is None and len(args) == 2 and "$" not in args[1])
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


def nginx_plan(root, host, output):
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
               "proxy_connect_timeout", "access_log", "error_log", "tcp_nodelay"}
    require(all(d[0] in allowed for d in directives))
    for required in (["ssl_preread", "on"], ["proxy_protocol", "on"],
                     ["proxy_pass", mapping.args[2]]):
        require(directives.count(required) == 1)
    listens = [d[1:] for d in directives if d[0] == "listen"]
    require(listens == [["443"]] or listens == [["0.0.0.0:443"]])
    entries = list(expand(mapping.children))
    require(sum(n.args[0] == "default" for n in entries) == 1)
    require(len({n.args[0] for n in entries}) == len(entries))
    for n in entries:
        require(n.children is None and len(n.args) == 2)
        require(n.args[0] == "default" or re.fullmatch(r"[a-z0-9.-]+", n.args[0]))
        require(re.fullmatch(r"[A-Za-z0-9_.:-]+", n.args[1]))
    upstreams = exact(stream.children, "upstream")
    owned = [n for n in upstreams if n.args == ["upstream", "twm_frontend"]]
    existing = [n for n in entries if n.args[0] == host]
    vhost = parser.root / "conf.d" / "telemt-web-manager.conf"
    # Only an actual top-level http include proves where the new vhost is loaded.
    includes = [n for n in http.children if n.args[0] == "include"]
    require(any(str((parser.root / n.args[1]).resolve()) ==
                str(parser.root / "conf.d" / "*.conf") for n in includes))
    # No competing HTTPS socket, domain, managed symbol or internal port anywhere.
    for n in walk(nodes):
        if n.path == vhost:
            continue
        if n.args[0] == "server_name":
            require(host not in n.args[1:])
        if n.args[0] == "listen" and n not in exact(router.children, "listen"):
            require(not any(re.search(r"(?:^|:)(443|7444|18080)$", a) for a in n.args[1:]))
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
    with open(path, "rb") as source:
        c = tomllib.load(source)
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
        require(re.fullmatch(r"[a-zA-Z0-9.-]+:[0-9]{1,5}", address)
                and 0 < int(address.rsplit(":", 1)[1]) < 65536, "invalid SOCKS address")
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
    elif command == "config-info":
        config_info(*args)
    elif command == "dns":
        dns_check(Path(args[0]).read_text(), Path(args[1]).read_text(), args[2])
    elif command == "domain":
        domain(args[0])
    elif command == "ipv4":
        ipv4(args[0])
    elif command == "classify":
        return classify(*args[:3], sys.stdin.read())
    else:
        raise ValueError("unknown helper command")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, TypeError, IndexError):
        # Config parse errors may contain credentials. Never echo exception text.
        print("Safety validation failed; manual review required (no credentials displayed).", file=sys.stderr)
        sys.exit(1)
