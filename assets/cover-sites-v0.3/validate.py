#!/usr/bin/env python3
"""Offline static-site quality checks. Uses Python stdlib only.

This validates published files and editorial variants, not anti-probing efficacy,
Nginx integration, or Telegram/Telemt transport.
"""
import hashlib
import html
from html.parser import HTMLParser
from pathlib import Path
import re
import tempfile
from xml.etree import ElementTree

from generate import ARTICLE, ARTICLE_ALTERNATES, DATA, HOME_EDITORIAL, generate, make_article, make_home

ROOT = Path(__file__).resolve().parent
ASSET_NAMES = {'index.html', '404.html', 'site.css', 'illustration.svg',
               'favicon.ico', 'favicon.svg', 'robots.txt'}


class Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.resources = []
        self.ids = []
        self.tags = []
        self.titles = 0
        self.h1 = 0
        self.current = 0
        self.external = []
        self.meta = []
        self.stack = []

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        self.tags.append(tag)
        if tag in ('a', 'link'):
            self.links.append(attrs.get('href', ''))
        if tag in ('img', 'script', 'iframe', 'source'):
            self.resources.append(attrs.get('src', ''))
        for attr in ('srcset', 'action', 'formaction'):
            if attr in attrs:
                self.external.append(attrs[attr])
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if attrs.get('aria-current') == 'page':
            self.current += 1
        if tag == 'h1':
            self.h1 += 1
        if tag == 'title':
            self.titles += 1
        if tag == 'meta':
            self.meta.append(attrs)


def check_site(path, theme=None):
    path = Path(path)
    theme = theme or path.name
    names = {p.name for p in path.iterdir()}
    assert names == ASSET_NAMES | {p for p, _ in DATA[theme]['pages'] if p != 'index.html'}, (path, names)
    assert len(names) == 11
    all_titles = []
    for file in path.iterdir():
        assert file.is_file() and not file.is_symlink(), file
        assert 0 < file.stat().st_size <= 180_000, file
        if file.suffix == '.html':
            source = file.read_text('utf-8')
            parsed = Document()
            parsed.feed(source)
            parsed.close()
            assert source.lower().startswith('<!doctype html>'), file
            assert '<html lang="en">' in source and parsed.titles == parsed.h1 == 1, file
            assert parsed.tags.count('main') == 1 and len(parsed.ids) == len(set(parsed.ids)), file
            assert parsed.current == (0 if file.name == '404.html' else 1), file
            assert not {'script', 'iframe', 'form', 'object', 'embed', 'video', 'audio'}.intersection(parsed.tags), file
            assert not parsed.external, (file, parsed.external)
            assert '<title>' in source and '</title>' in source, file
            assert '<meta name="viewport"' in source, file
            assert '<meta name="description"' in source or file.name == '404.html', file
            title = html.unescape(re.search(r'<title>(.*?)</title>', source).group(1))
            assert len(title) > 10 and title not in all_titles, file
            all_titles.append(title)
            assert 'href="#main"' in source and 'id="main"' in source or file.name == '404.html', file
            for target in parsed.links + parsed.resources:
                if target.startswith('#'):
                    assert target[1:] in parsed.ids, (file, target)
                    continue
                assert target and not target.startswith(('http:', 'https:', '//', 'data:', 'javascript:')),(file,target)
                assert not re.search(r'\\|(?:^|/)\.\.?/', target), (file, target)
                bare = target.partition('#')[0].partition('?')[0]
                if bare in ('', '/'):
                    continue
                child = path / bare.lstrip('/')
                assert child.is_file() and child.parent == path, (file, target)
            if file.name == '404.html':
                assert '<meta name="robots" content="noindex">' in source, file
        elif file.suffix == '.css':
            css = file.read_text('utf-8')
            assert not re.search(r'\{\{[A-Z_]+\}\}', css), file
            assert '@import' not in css and not re.search(r'url\s*\(', css, re.I), file
            assert re.search(r'@media\s*\(', css), file
        elif file.suffix == '.svg':
            root = ElementTree.fromstring(file.read_bytes())
            assert root.tag.endswith('svg'), file
            assert not root.findall('.//{http://www.w3.org/2000/svg}script'), file
        elif file.suffix == '.ico':
            raw = file.read_bytes()
            assert len(raw) > 1000 and raw[:6] == bytes([0,0,1,0,1,0]), file
        elif file.suffix == '.txt':
            robots = file.read_text('utf-8')
            assert robots.count('User-agent: *') == 1 and 'Disallow:' in robots, file
    return hashlib.sha256(b''.join(file.read_bytes() for file in sorted(path.iterdir()))).hexdigest()



def contrast(first, second):
    def light(hexvalue):
        rgb = [int(hexvalue[i:i+2], 16) / 255.0 for i in (1, 3, 5)]
        values = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in rgb]
        return sum(a*b for a,b in zip(values, (0.2126, 0.7152, 0.0722)))
    high, low = sorted((light(first), light(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)

def check_variants():
    for theme in DATA:
        colors = DATA[theme]['colors']
        for ink, bg, soft, accent in colors:
            assert contrast(ink, bg) >= 4.5, (theme, ink, bg)
            assert contrast(accent, bg) >= 4.5 and contrast(accent, soft) >= 4.5, (theme, accent)
        # Five illustrations differ in actual SVG content, not only the file name.
        from generate import svg_art
        assert len({svg_art(theme, i, *colors[0]) for i in range(5)}) == 5
        pages = [p for p, _ in DATA[theme]['pages'] if p != 'index.html']
        assert len(pages) == 4 and len(ARTICLE[theme]) == len(ARTICLE_ALTERNATES[theme]) == 4
        assert len(HOME_EDITORIAL[theme]) == 4
        for page in pages:
            options = [ARTICLE[theme][page], *ARTICLE_ALTERNATES[theme][page]]
            assert len(options) == 3
            titles = [item[0] for item in options]
            assert len(set(titles)) == 3, (theme, page, titles)
            for index in range(3):
                text = make_article(theme, DATA[theme]['brands'][0], page, colors[0], 0, index)
                assert titles[index] in html.unescape(text) and len(text) > 1600
        h = [make_home(theme, DATA[theme]['brands'][0], DATA[theme]['copy'][0], colors[0], i)
             for i in range(4)]
        assert len(set(h)) == 4, theme


def main():
    check_variants()
    for theme in DATA:
        print(theme, 'example', check_site(ROOT / 'examples' / theme)[:12])
    seen = set()
    with tempfile.TemporaryDirectory() as temporary:
        for i in range(300):
            path = Path(temporary) / list(DATA)[i % len(DATA)]
            path = path / str(i)
            path.parent.mkdir(exist_ok=True)
            generate(path, theme=list(DATA)[i % len(DATA)])
            # check_site expects the theme name for its page inventory.
            digest = check_site(path, list(DATA)[i % len(DATA)])
            assert digest not in seen, f'duplicate published site in sample #{i}'
            seen.add(digest)
        # Reject overwrite, including existing directory even if empty.
        sample = Path(temporary) / 'existing'
        sample.mkdir()
        try:
            generate(sample)
        except FileExistsError:
            pass
        else:
            raise AssertionError('generation overwrote an existing directory')
    print('PASS: 3 examples, all article/home editions, 300 random builds, static structure, links and uniqueness')



if __name__ == '__main__':
    main()
