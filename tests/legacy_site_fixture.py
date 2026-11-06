"""Historical static_directory test data; never installed as manager code."""
import json
import os
from pathlib import Path
import shutil
import sys
import tomllib

ROOT=Path(__file__).resolve().parents[1]


def legacy_config(raw):
    if isinstance(raw,bytes): raw=raw.decode()
    data=tomllib.loads(raw)['general']['data_path']
    old='mode = "http_upstream"\nupstream = "http://127.0.0.1:18081"'
    assert raw.count(old)==1
    return raw.replace(old,f'mode = "static_directory"\ndirectory = "{data}/public"\nindex = "index.html"').encode()


def write_legacy_public(data,gid=None):
    public=Path(data)/'public'; public.mkdir(mode=0o750,parents=True,exist_ok=True)
    gid=public.stat().st_gid if gid is None else gid
    os.chown(public,0,gid); public.chmod(0o750)
    for source,name in (('site-02.html','index.html'),('cover.css','cover.css')):
        path=public/name; path.write_bytes((ROOT/'assets/fake-sites'/source).read_bytes())
        os.chown(path,0,gid); path.chmod(0o440)


def convert(config,data,nginx,state,site,form='direct'):
    """Construct known old fixture bytes after a current fake Fresh install."""
    sys.path.insert(0,str(ROOT/'lib'))
    import safety as s
    config=Path(config); data=Path(data); nginx=Path(nginx); state=Path(state); site=Path(site)
    current = s.site_bound_identity(config,str(data),nginx,site)
    if current:
        config.write_bytes(legacy_config(config.read_bytes()))
        write_legacy_public(data)
    manifest=json.loads((state/'manifest.json').read_text())
    vhost=nginx/'conf.d/telemt-web-manager.conf'
    vhost.write_text(s.render_vhost(manifest['domain'],keepalive=form!='direct'))
    manifest['nginx_sha256']=s.update_hash(vhost)['sha256']
    s.update_write_json(state/'manifest.json',manifest)
    if current: shutil.rmtree(site)  # Only this just-verified private fixture tree.


if __name__=='__main__': convert(*sys.argv[1:])
