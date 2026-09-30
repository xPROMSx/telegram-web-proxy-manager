"""Render pinned upstream Nginx heredocs with inert example values, never eval.

The installer/patcher is not executed. Sources can be read from a local checkout
or fetched from the recorded upstream commit; fixtures contain no live secrets.
"""
import argparse
import hashlib
from pathlib import Path
import re
import urllib.request

COMMIT = "a2c430cd6dec7c86d873dcda3544a61e7ac41144"
VALUES = {
    "domain": "panel.example.com", "reality_domain": "reality.example.com",
    "sub_path": "subscription", "json_path": "json", "xhttp_path": "xhttp",
    "panel_path": "panel", "diag_path": "/diagnostics/",
    "diag_token": "fixture-placeholder-not-a-credential",
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


def build(root, script, source=None):
    if source:
        text = (Path(source) / script).read_text(encoding="utf-8")
    else:
        url = f"https://raw.githubusercontent.com/mozaroc/3x-ui-pro/{COMMIT}/{script}"
        with urllib.request.urlopen(url, timeout=30) as response:
            text = response.read().decode("utf-8")
    # Git blob hashes record the exact sources investigated, independent of CRLF
    # conversion in local Windows checkouts.
    text = text.replace("\r\n", "\n")
    expected = {"x-ui-latest.sh": "671ca1e17b0162493b05cf3086968d1b43b5547f",
                "x-ui-patch.sh": "dc506e80e371c7768177881fd0b3b7676c55bf3f"}
    data = text.encode()
    actual = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    if actual != expected[script]:
        raise ValueError("upstream fixture source differs from reviewed blob")
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
    parser.add_argument("--script", choices=("x-ui-latest.sh", "x-ui-patch.sh"), required=True)
    parser.add_argument("--source")
    options = parser.parse_args()
    build(options.root, options.script, options.source)
