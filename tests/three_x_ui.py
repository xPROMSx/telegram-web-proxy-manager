"""Render pinned upstream Nginx heredocs with inert example values, never eval.

The installer is not executed. Sources can be read from a local checkout
or fetched from the recorded upstream commit; fixtures contain no live secrets.
"""
import argparse
import ast
import hashlib
from pathlib import Path
import re
import urllib.request

REPOSITORY = "xPROMSx/3x-ui-auto-nginx"
COMMIT = "59ff07f3bfeaf4b33bc5d803dfe9a3334ab8c1fd"
BLOB = "c19f7c2116adf41dcc7509fd47ecf2c64f5c1c81"
NEW_COMMIT = "eba91cfe80144f91ce2ce771859ba1787421d0fa"
NEW_BLOB = "c98dcfb9cc8456b8fe72fe34b1238311c59ae1ed"
V162_COMMIT = "0a3f79ff99d3c544aef1683b1c6eacbd7c605d40"
V162_BLOB = "07400c3cae40fee713df5bc21eb8c7dde674d4fc"
V217_COMMIT = "2ae180bb36efdc1af36912fd96c673e9e7d9055a"
V217_BLOB = "f93b6c0178e125294ff514adca15c6d00bc591cf"
VISION_BLOB = "e5c41a3c3f0c65990a53627399eb0b6db68cf9d5"
# Independent (IPv6 listeners, Vision) flags; all four use the same source pin.
V217_OPTIONS = {'v2.1.7': (True, True), 'v2.1.7-ipv4': (False, True),
                'v2.1.7-no-vision': (True, False), 'v2.1.7-ipv4-no-vision': (False, False)}
PROFILES = {"legacy": (COMMIT, BLOB), "webroot": (NEW_COMMIT, NEW_BLOB),
            "v1.6.2": (V162_COMMIT, V162_BLOB),
            **{name: (V217_COMMIT, V217_BLOB) for name in V217_OPTIONS}}
VALUES = {
    "domain": "panel.example.com", "reality_domain": "reality.example.com",
    "sub_path": "subscription", "json_path": "json", "xhttp_path": "xhttp",
    "panel_path": "panel", "diag_path": "/diagnostics/",
    "diag_token": "fixture-placeholder-not-a-credential",
    "ws_port": "2097", "ws_path": "websocket",
    "trojan_port": "2098", "trojan_path": "grpc",
    "panel_port": "2053", "sub_port": "2096", "mtr_backend_port": "9080",
    "http2_listen": " http2", "http2_on": "",
}


def render(text, values=VALUES):
    result = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text) and text[i + 1] in "$`\\\n":
            if text[i + 1] != "\n":
                result.append(text[i + 1])
            i += 2
        elif c == "`" or text.startswith("$(", i):
            raise ValueError("command substitution is never allowed in fixtures")
        elif c == "$":
            match = re.match(r"\$\{([a-zA-Z_][a-zA-Z_0-9]*)\}|\$([a-zA-Z_][a-zA-Z_0-9]*)", text[i:])
            if match:
                result.append(values[match.group(1) or match.group(2)])
                i += len(match.group())
            else:
                result.append(c)
                i += 1
        else:
            result.append(c)
            i += 1
    return "".join(result)


def source_bytes(path, commit, blob, source):
    if source:
        data = (Path(source) / path).read_bytes()
    else:
        url = f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/{path}"
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
    actual = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    if actual != blob:
        raise ValueError("upstream fixture source differs from reviewed blob")
    print(f"ok - immutable source: commit {commit}; {path} blob {actual}")
    return data


def vision_configs(data, stream, ipv6):
    """Read two literal f-strings and verify the exact stream insertion; no eval/import."""
    tree = ast.parse(data)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    marker = ast.literal_eval(next(node.value for node in tree.body if isinstance(node, ast.Assign)
                                  and any(isinstance(t, ast.Name) and t.id == 'MARKER' for t in node.targets)))
    def assignment(name, key):
        return next(node for node in functions[name].body if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == key for t in node.targets))

    anchor = ast.literal_eval(assignment('stream_config', 'anchor').value)
    expected = "text.replace(anchor, anchor + f'    {domain} vision;\\n') + f'\\nupstream vision {{ server 127.0.0.1:{port}; }}\\n'"
    if (anchor != 'map $ssl_preread_server_name $sni_name {\n    hostnames;\n'
            or stream.count(anchor) != 1
            or ast.dump(functions['stream_config'].body[-1].value) != ast.dump(ast.parse(expected, mode='eval').body)):
        raise ValueError('unrecognized Vision stream template')
    listener = assignment('acme_config', 'listener')
    if ast.dump(listener) != ast.dump(ast.parse("listener = '    listen [::]:80;\\n' if ipv6 else ''").body[0]):
        raise ValueError('unrecognized Vision IPv6 template')

    def template(name, values):
        expression = functions[name].body[-1].value
        if not (isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.Add)
                and isinstance(expression.left, ast.Name) and expression.left.id == 'MARKER'
                and isinstance(expression.right, ast.JoinedStr)):
            raise ValueError('unrecognized Vision literal template')
        parts = [marker]
        for part in expression.right.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                parts.append(part.value)
            elif (isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name)
                  and part.value.id in values and part.conversion == -1 and part.format_spec is None):
                parts.append(str(values[part.value.id]))
            else:
                raise ValueError('nonliteral Vision template substitution')
        return ''.join(parts)

    fallback = template('fallback_config', dict(domain='vision.example.com', port=10444,
                        root=ast.literal_eval(functions['fallback_config'].args.defaults[0])))
    acme = template('acme_config', dict(domain='vision.example.com',
                    listener=ast.literal_eval(listener.value.body if ipv6 else listener.value.orelse)))
    stream = stream.replace(anchor, anchor + '    vision.example.com vision;\n') + '\nupstream vision { server 127.0.0.1:10443; }\n'
    return stream, fallback, acme


def build(root, script, source=None, profile="legacy"):
    if script != "x-ui-latest.sh":
        raise ValueError("only the reviewed Fresh Install topology is supported")
    commit, blob = PROFILES[profile]
    ipv6, vision = V217_OPTIONS.get(profile, (True, False))
    data = source_bytes(script, commit, blob, source)
    vision_data = source_bytes('assets/vision/managed.py', commit, VISION_BLOB, source) if vision else None
    text = data.decode("utf-8").replace("\r\n", "\n")
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "conf.d").mkdir(exist_ok=True)
    (root / "sites-enabled").mkdir(exist_ok=True)
    count = 0
    for match in re.finditer(r"(?m)^[ \t]*cat > ([^\n]+) <<EOF\n(.*?)^EOF[ \t]*$", text, re.S):
        target = match.group(1).strip('"')
        if not target.startswith("/etc/nginx/"):
            continue
        target = render(target).removeprefix("/etc/nginx/")
        path = root / target
        path.parent.mkdir(parents=True, exist_ok=True)
        values = dict(VALUES)
        values['ipv6_listen'] = ('' if not ipv6 else
                                'listen [::]:443;' if target == 'stream-enabled/stream.conf' else
                                'listen [::]:80;')
        # Preserve include structure while making all config includes relative
        # to the isolated nginx.conf, never to the CI machine's /etc/nginx.
        path.write_text(render(match.group(2), values).replace("/etc/nginx/", ""), encoding="utf-8")
        if target.startswith("sites-available/"):
            # Same active content as the upstream symlinks. No symlink privileges
            # are needed for local Windows unit tests.
            (root / "sites-enabled" / path.name).write_bytes(path.read_bytes())
        count += 1
    if count != 6:
        raise ValueError("unexpected upstream Nginx heredoc layout")
    if vision:
        stream = root / 'stream-enabled/stream.conf'
        patched, fallback, acme = vision_configs(vision_data, stream.read_text(), ipv6)
        stream.write_text(patched)
        (root / 'sites-enabled/vision.conf').write_text(fallback)
        (root / 'sites-enabled/vision-acme.conf').write_text(acme)
    (root / "nginx.conf").write_text(
        "events { worker_connections 1024; }\n"
        "http {\n    include conf.d/*.conf;\n    include sites-enabled/*;\n}\n"
        "stream { include stream-enabled/*.conf; }\n", encoding="utf-8")
    if profile in V217_OPTIONS:
        content = '\n'.join(p.read_text() for p in root.rglob('*') if p.is_file())
        assert bool(re.search(r'listen\s+\[', content)) == ipv6
        assert ('vision.example.com' in content) == vision
        assert ('upstream vision {' in content) == vision
        assert (root / 'sites-enabled/vision.conf').exists() == vision
        assert (root / 'sites-enabled/vision-acme.conf').exists() == vision
        print(f'ok - {profile}: IPv6={ipv6}, Vision={vision}; fixture listeners/routes verified')
    return root


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    parser.add_argument("--script", choices=("x-ui-latest.sh",), required=True)
    parser.add_argument("--source")
    parser.add_argument("--profile", choices=tuple(PROFILES), default="legacy")
    options = parser.parse_args()
    build(options.root, options.script, options.source, options.profile)
