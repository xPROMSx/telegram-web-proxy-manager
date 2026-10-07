"""Offline Markdown link targets/anchors; external URLs are syntax-checked."""
from pathlib import Path
import re
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]


def anchors(path):
    result = set(); occurrences = {}
    for title in re.findall(r'^#{1,6}\s+(.+?)\s*#*$', path.read_text(), re.M):
        title = re.sub(r'\[([^]]+)\]\([^)]*\)', r'\1', title)
        slug = re.sub(r'[^\w\- ]', '', title.lower()).replace(' ', '-')
        count = occurrences.get(slug, 0); occurrences[slug] = count + 1
        result.add(slug + (f'-{count}' if count else ''))
    return result


def check(root=ROOT):
    root = Path(root); count = 0
    for path in [*root.glob('README*.md'), *root.glob('docs/**/*.md')]:
        for target in re.findall(r'!?\[[^\n]*?\]\(([^\s)]+)\)', path.read_text()):
            parsed = urllib.parse.urlsplit(target)
            if parsed.scheme:
                assert parsed.scheme == 'https' and parsed.netloc and not parsed.username, target
            else:
                dest = (path.parent / urllib.parse.unquote(parsed.path)).resolve() if parsed.path else path
                assert dest.is_relative_to(root.resolve()) and dest.is_file(), f'{path.name}: {target}'
                if parsed.fragment:
                    assert urllib.parse.unquote(parsed.fragment) in anchors(dest), f'{path.name}: {target}'
            count += 1
    return count


if __name__ == '__main__':
    print(f'Documentation link targets/anchors and URL syntax: {check()} PASS (offline)')
