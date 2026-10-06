"""Render pinned upstream Nginx heredocs with inert example values, never eval.

The installer is not executed. Sources can be read from a local checkout
or fetched from the recorded upstream commit; fixtures contain no live secrets.
"""
import argparse
import hashlib
from pathlib import Path
import re
import urllib.request

REPOSITORY = "xPROMSx/3x-ui-auto-nginx"
COMMIT = "59ff07f3bfeaf4b33bc5d803dfe9a3334ab8c1fd"
BLOB = "c19f7c2116adf41dcc7509fd47ecf2c64f5c1c81"
NEW_COMMIT = "eba91cfe80144f91ce2ce771859ba1787421d0fa"
NEW_BLOB = "c98dcfb9cc8456b8fe72fe34b1238311c59ae1ed"
PROFILES = {"legacy": (COMMIT, BLOB), "webroot": (NEW_COMMIT, NEW_BLOB)}
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


def render(text):
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
                result.append(VALUES[match.group(1) or match.group(2)])
                i += len(match.group())
            else:
                result.append(c)
                i += 1
        else:
            result.append(c)
            i += 1
    return "".join(result)


def build(root, script, source=None, profile="legacy"):
    if script != "x-ui-latest.sh":
        raise ValueError("only the reviewed Fresh Install topology is supported")
    commit, blob = PROFILES[profile]
    if source:
        data = (Path(source) / script).read_bytes()
    else:
        url = f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/{script}"
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
    actual = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    if actual != blob:
        raise ValueError("upstream fixture source differs from reviewed blob")
    print(f"ok - {profile} immutable source: commit {commit}; x-ui-latest.sh blob {actual}")
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
        # Preserve include structure while making all config includes relative
        # to the isolated nginx.conf, never to the CI machine's /etc/nginx.
        path.write_text(render(match.group(2)).replace("/etc/nginx/", ""), encoding="utf-8")
        if target.startswith("sites-available/"):
            # Same active content as the upstream symlinks. No symlink privileges
            # are needed for local Windows unit tests.
            (root / "sites-enabled" / path.name).write_bytes(path.read_bytes())
        count += 1
    if count != 6:
        raise ValueError("unexpected upstream Nginx heredoc layout")
    (root / "nginx.conf").write_text(
        "events { worker_connections 1024; }\n"
        "http {\n    include conf.d/*.conf;\n    include sites-enabled/*;\n}\n"
        "stream { include stream-enabled/*.conf; }\n", encoding="utf-8")
    return root


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    parser.add_argument("--script", choices=("x-ui-latest.sh",), required=True)
    parser.add_argument("--source")
    parser.add_argument("--profile", choices=tuple(PROFILES), default="legacy")
    options = parser.parse_args()
    build(options.root, options.script, options.source, options.profile)
