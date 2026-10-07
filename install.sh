#!/usr/bin/env bash
# Install only the manager program pair from an official published release.
set +x
set -Eeuo pipefail
umask 077
export LC_ALL=C
INSTALL_DIR=/opt/telemt-web-manager
# Legacy paths are compatibility ABI; both public commands execute this pair.
LAUNCHER=/usr/local/bin/telemt-web-manager
CANONICAL_LAUNCHER=''
BOOTSTRAP_LOCK=/run/lock/telemt-web-manager.lock
MANAGER_STATE=/var/lib/telemt-web-manager
MANAGER_SYSTEMD_ROOT=/etc/systemd/system
BOOTSTRAP_TMP='' MANAGER_TAG='' MANAGER_COMMIT='' VERSION='' NO_START=0
readonly PRIMARY_MANAGER_REPO=xPROMSx/telegram-web-proxy-manager
readonly LEGACY_MANAGER_REPO=xPROMSx/telemt-web-manager
MANAGER_REPO=$LEGACY_MANAGER_REPO

bootstrap_die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
bootstrap_download() {
    curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fLsS \
        --connect-timeout 10 --max-time 60 --max-filesize 8388608 --retry 2 "$1" -o "$2" || return 1
    [[ -s $2 ]]
}

# Return the actual HTTP status, not curl's generic failure code. Only a real
# GitHub 404 permits legacy fallback; network/rate-limit/metadata errors refuse.
bootstrap_repository_metadata() {
    curl --proto '=https' --proto-redir '=https' --tlsv1.2 -LsS \
        --connect-timeout 10 --max-time 60 --max-filesize 1048576 \
        -w '%{http_code}' "https://api.github.com/repos/$1" -o "$2"
}

resolve_manager_repository() {
    local requested status
    for requested in "$PRIMARY_MANAGER_REPO" "$LEGACY_MANAGER_REPO"; do
        status=$(bootstrap_repository_metadata "$requested" "$BOOTSTRAP_TMP/repository.json") || bootstrap_die 'Manager repository metadata unavailable'
        if [[ $status == 404 && $requested == "$PRIMARY_MANAGER_REPO" ]]; then continue; fi
        [[ $status == 200 ]] || bootstrap_die 'Manager repository metadata unavailable'
        MANAGER_REPO=$({ bootstrap_version_code; cat <<'PYREPO'
import sys
repo = load_metadata(sys.argv[1])
requested, primary, legacy = sys.argv[2:]
if not isinstance(repo, dict): sys.exit(1)
name = repo.get('full_name')
# The immutable repository/owner IDs survive rename; neither an unrelated repo
# under a trusted name nor an unexpected redirect can become our release source.
if (name not in (primary, legacy) or (requested == primary and name != primary)
        or type(repo.get('id')) is not int or repo['id'] != 1398514078
        or repo.get('name') != name.split('/')[1]
        or repo.get('html_url') != 'https://github.com/' + name
        or not isinstance(repo.get('owner'), dict)
        or repo['owner'].get('login') != 'xPROMSx'
        or type(repo['owner'].get('id')) is not int or repo['owner']['id'] != 102687702
        or any(repo.get(key) is not False for key in ('private','fork','archived','disabled'))):
    sys.exit(1)
print(name)
PYREPO
        } | python3 - "$BOOTSTRAP_TMP/repository.json" "$requested" "$PRIMARY_MANAGER_REPO" "$LEGACY_MANAGER_REPO") || bootstrap_die 'Untrusted or malformed manager repository metadata'
        return
    done
    bootstrap_die 'Manager repository unavailable'
}

# Shared by release selection, downloaded-pair validation and the locked guard.
# This code is part of the installer, never loaded from an installed/downloaded file.
bootstrap_version_code() {
    cat <<'PY'
import json, re
from pathlib import Path

def load_metadata(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Duplicate manager metadata field')
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique)

VERSION_RE = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
                        r'(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?'
                        r'(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?')

def version_key(value):
    if not isinstance(value, str): raise ValueError('Invalid manager SemVer')
    match = VERSION_RE.fullmatch(value)
    if match is None: raise ValueError('Invalid manager SemVer')
    identifiers = match[4].split('.') if match[4] else []
    if any(x.isdigit() and len(x) > 1 and x.startswith('0') for x in identifiers):
        raise ValueError('Invalid numeric prerelease identifier')
    # Length + ASCII digits compares arbitrarily large numbers without overflow
    # or Python's integer-string conversion limit. Build metadata is excluded.
    core = tuple((len(match[i]), match[i]) for i in (1, 2, 3))
    pre = tuple((0, len(x), x) if x.isdigit() else (1, x) for x in identifiers)
    return core, not identifiers, pre

def manager_version(path):
    content = Path(path).read_bytes().decode('utf-8')
    # The fixed prologue puts the declaration outside shell strings/heredocs.
    # Only the exact generated syntax is supported, without shell interpretation.
    source_lines = content.split('\n')
    if (source_lines[2:6] != ['set +x', 'set -Eeuo pipefail', 'umask 077', 'export LC_ALL=C']
            or len(source_lines) < 7 or not source_lines[6].startswith('readonly SCRIPT_VERSION=')):
        raise ValueError('Unrecognized manager version prologue')
    # Reject other bare references too (nested/quoted/conditional assignments).
    lines = [line for line in source_lines if not line.lstrip().startswith('#')
             and re.search(r'(?<![\w${])SCRIPT_VERSION\b', line)]
    if len(lines) != 1 or not lines[0].startswith('readonly SCRIPT_VERSION='):
        raise ValueError('Missing or ambiguous installed SCRIPT_VERSION')
    value = lines[0][len('readonly SCRIPT_VERSION='):]
    version_key(value)
    return value
PY
}

resolve_manager_release() {
    local page count sha kind depth
    local -a metadata=()
    if [[ -n $VERSION ]]; then
        # Keep the public explicit-tag surface: one prerelease OR build suffix.
        [[ $VERSION =~ ^v[0-9]+\.[0-9]+\.[0-9]+([+-][0-9A-Za-z.-]+)?$ ]] || bootstrap_die 'Expected a published version tag, e.g. v0.1.0'
        { bootstrap_version_code; cat <<'PYCODE'
import sys
if not sys.argv[1].startswith('v'): sys.exit(1)
version_key(sys.argv[1][1:])
PYCODE
        } | python3 - "$VERSION" || bootstrap_die 'Expected a published SemVer tag, e.g. v0.1.0'
        bootstrap_download "https://api.github.com/repos/$MANAGER_REPO/releases/tags/$VERSION" "$BOOTSTRAP_TMP/releases.json" || bootstrap_die 'Manager release metadata unavailable'
        metadata+=("$BOOTSTRAP_TMP/releases.json")
    else
        for ((page=1; page<=20; page++)); do
            bootstrap_download "https://api.github.com/repos/$MANAGER_REPO/releases?per_page=100&page=$page" "$BOOTSTRAP_TMP/releases-$page.json" || bootstrap_die 'Manager release metadata unavailable'
            metadata+=("$BOOTSTRAP_TMP/releases-$page.json")
            count=$({ bootstrap_version_code; cat <<'PY'
import sys
value = load_metadata(sys.argv[1])
if not isinstance(value, list) or len(value) > 100: sys.exit(1)
print(len(value))
PY
            } | python3 - "${metadata[-1]}"
            ) || bootstrap_die 'Invalid manager release list'
            (( count == 100 )) || break
        done
        (( count < 100 )) || bootstrap_die 'Release history too large; select --version explicitly'
    fi
    MANAGER_TAG=$({ bootstrap_version_code; cat <<'PY'
import datetime, sys
releases = []
repository = sys.argv[2]
for filename in sys.argv[3:]:
    value = load_metadata(filename)
    if sys.argv[1]:
        if not isinstance(value, dict): sys.exit(1)
        releases.append(value)
    else:
        if not isinstance(value, list): sys.exit(1)
        releases.extend(value)
valid, seen = [], set()
for release in releases:
    if not isinstance(release, dict): sys.exit(1)
    if release.get('draft') is True: continue
    if release.get('draft') is not False or not isinstance(release.get('prerelease'), bool): sys.exit(1)
    tag = release.get('tag_name')
    if not isinstance(tag, str) or not tag.startswith('v'): sys.exit(1)
    key = version_key(tag[1:])
    if tag in seen: sys.exit(1)
    seen.add(tag)
    if release.get('html_url') != 'https://github.com/' + repository + '/releases/tag/' + tag: sys.exit(1)
    published = release.get('published_at')
    if not isinstance(published, str): sys.exit(1)
    if datetime.datetime.fromisoformat(published.replace('Z', '+00:00')).tzinfo is None: sys.exit(1)
    # A GitHub prerelease flag on a plain core version remains supported (v0.1.0
    # is published that way). A SemVer prerelease cannot be treated as stable.
    valid.append((key, tag, release['prerelease'] or not key[1]))
if sys.argv[1]:
    valid = [r for r in valid if r[1] == sys.argv[1]]
else:
    stable = [r for r in valid if not r[2]]
    if stable: valid = stable
if not valid: sys.exit(1)
latest = max(r[0] for r in valid)
selected = [r for r in valid if r[0] == latest]
# Distinct tags at equal highest precedence require administrator selection.
if len(selected) != 1: sys.exit(1)
print(selected[0][1])
PY
    } | python3 - "$VERSION" "$MANAGER_REPO" "${metadata[@]}"
    ) || bootstrap_die 'Ambiguous or invalid published manager release; select --version explicitly after review'
    bootstrap_download "https://api.github.com/repos/$MANAGER_REPO/git/ref/tags/$MANAGER_TAG" "$BOOTSTRAP_TMP/ref.json" || bootstrap_die 'Published manager tag unavailable'
    for ((depth=0; depth<5; depth++)); do
        local object
        object=$({ bootstrap_version_code; cat <<'PY'
import sys
value = load_metadata(sys.argv[1])
obj = value.get('object', {})
if sys.argv[3] == '0':
    if value.get('ref') != 'refs/tags/' + sys.argv[2]: sys.exit(1)
elif value.get('sha') != sys.argv[4]: sys.exit(1)
sha, kind = obj.get('sha', ''), obj.get('type', '')
if not re.fullmatch('[0-9a-f]{40}', sha) or kind not in ('commit', 'tag'): sys.exit(1)
print(sha, kind)
PY
        } | python3 - "$BOOTSTRAP_TMP/ref.json" "$MANAGER_TAG" "$depth" "${sha:-}"
        ) || bootstrap_die 'Invalid manager tag object'
        read -r sha kind <<<"$object"
        if [[ $kind == commit ]]; then MANAGER_COMMIT=$sha; return; fi
        bootstrap_download "https://api.github.com/repos/$MANAGER_REPO/git/tags/$sha" "$BOOTSTRAP_TMP/ref.json" || bootstrap_die 'Annotated manager tag unavailable'
    done
    bootstrap_die 'Manager tag does not resolve to one commit'
}

validate_manager_pair() {
    [[ -s $BOOTSTRAP_TMP/telemt-web-manager.sh && -s $BOOTSTRAP_TMP/safety.py ]] || bootstrap_die 'Empty manager download'
    bash -n "$BOOTSTRAP_TMP/telemt-web-manager.sh" || bootstrap_die 'Invalid manager Bash syntax'
    { bootstrap_version_code; cat <<'PY'
import sys
script, helper, tag = sys.argv[1:]
if not Path(script).read_bytes().startswith((b'#!/usr/bin/env bash\n# Telegram Web Proxy Manager.', b'#!/usr/bin/env bash\n# Telemt WEB Manager.')):
    raise ValueError('Downloaded program is not recognized as this manager')
if not Path(helper).read_bytes().startswith(b'#!/usr/bin/env python3\n"""Strict, read-only parsers and staged Nginx plans.'):
    raise ValueError('Downloaded helper is not recognized')
if manager_version(script) != tag[1:]:
    raise ValueError('Downloaded SCRIPT_VERSION does not match published tag')
compile(Path(helper).read_bytes(), 'safety.py', 'exec')
PY
    } | python3 - "$BOOTSTRAP_TMP/telemt-web-manager.sh" "$BOOTSTRAP_TMP/safety.py" "$MANAGER_TAG"
}

commit_manager_pair() {
    # Linux renameat2 exchanges complete directories atomically. Never copy into
    # the live pair. The common manager lock excludes active manager operations.
    { bootstrap_version_code; cat <<'PY'
import ast, ctypes, datetime, fcntl, hashlib, json, os, re, shutil, signal, stat, sys, tempfile
from pathlib import Path
source, dest, launcher, lock = map(Path, sys.argv[1:5])
tag, explicit, state_path, systemd_path, canonical_path = sys.argv[5:]
canonical = Path(canonical_path)
launchers = (launcher, canonical)
if launcher == canonical: raise ValueError('Launcher paths must be distinct')
state = Path(state_path)
systemd_root = Path(systemd_path)

def safe(path, regular=False):
    for item in (path, *path.parents):
        try: info = item.lstat()
        except FileNotFoundError: continue
        sticky = stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
        if info.st_uid != 0 or stat.S_ISLNK(info.st_mode) or (info.st_mode & 0o022 and not sticky):
            raise ValueError('Unsafe bootstrap path; manual review required')
        if item == path and regular:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('Expected a regular manager file')
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError('Expected a manager directory')

def existing_pair():
    safe(dest)
    if not dest.exists(): return False
    if {p.name for p in dest.iterdir()} != {'telemt-web-manager.sh', 'lib'}:
        raise ValueError('Unrelated installation directory; manual review required')
    safe(dest / 'lib')
    if {p.name for p in (dest / 'lib').iterdir()} != {'safety.py'}:
        raise ValueError('Unrelated manager helper directory; manual review required')
    for p in (dest / 'telemt-web-manager.sh', dest / 'lib/safety.py'): safe(p, regular=True)
    if not (dest / 'telemt-web-manager.sh').read_bytes().startswith((b'#!/usr/bin/env bash\n# Telegram Web Proxy Manager.', b'#!/usr/bin/env bash\n# Telemt WEB Manager.')):
        raise ValueError('Existing program is not recognized as this manager')
    if not (dest / 'lib/safety.py').read_bytes().startswith(b'#!/usr/bin/env python3\n\"\"\"Strict, read-only parsers and staged Nginx plans.'):
        raise ValueError('Existing helper requires manual review')
    return True

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('Duplicate recovery metadata key')
        result[key] = value
    return result

def recovery_record(path):
    safe(path, regular=True)
    info = path.stat()
    if info.st_gid != 0 or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 1048576:
        raise ValueError('Unsafe recovery metadata; keep the installed manager')
    with path.open('rb') as stream:
        value = json.loads(stream.read(1048577), object_pairs_hook=unique_object,
                           parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite recovery metadata')))
    if type(value) is not dict or type(value.get('schema')) is not int:
        raise ValueError('Unknown recovery metadata; keep the installed manager')
    return value

def static_schemas(path, kind):
    # No source/eval/import/exec of the downloaded candidate. Exactly one
    # literal capability declaration is recognized in the canonical shell.
    lines = path.read_text().splitlines()
    found = [re.fullmatch(r'readonly UPDATE_' + kind + r'_SCHEMAS=([1-9][0-9]*(?:,[1-9][0-9]*)*)', line)
             for line in lines if line.startswith('readonly UPDATE_' + kind + '_SCHEMAS=')]
    if not found: return set()  # Published legacy versions remain usable without new state.
    if len(found) != 1 or found[0] is None: raise ValueError('Invalid recovery capability declaration')
    values = found[0][1].split(',')
    if len(values) > 16 or len(set(values)) != len(values): raise ValueError('Ambiguous recovery capabilities')
    return {int(v) for v in values}

def recovery_valid(ok):
    if not ok: raise ValueError('Malformed recovery metadata; retain the installed manager')

def recovery_exact(value, keys):
    recovery_valid(type(value) is dict and set(value)==set(keys))

def recovery_hex(value, length):
    recovery_valid(isinstance(value,str) and re.fullmatch('[0-9a-f]{'+str(length)+'}',value))

def recovery_date(value, optional=False):
    if value is None and optional: return
    recovery_valid(isinstance(value,str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',value))
    datetime.datetime.strptime(value,'%Y-%m-%dT%H:%M:%SZ')

def recovery_version(value):
    recovery_valid(isinstance(value,str) and len(value)<=128 and
                   re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',value))

def recovery_receipt(value):
    recovery_exact(value, {'schema','origin','repository','architecture','installed_version','tag','tag_object_sha',
        'commit_sha','tag_verification','release','asset','checksum_asset','archive_sha256','binary','installed_at',
        'manager_version','transaction_id','generation_id','trust_policy'})
    recovery_valid(type(value['schema']) is int and value['schema']==1 and
        value['repository']=={'id':1125007401,'full_name':'telemt/telemt'} and
        value['architecture'] in ('x86_64','aarch64'))
    recovery_version(value['installed_version']); recovery_version(value['manager_version'])
    recovery_valid(value['tag'] in (value['installed_version'],'v'+value['installed_version']))
    for key in ('transaction_id','generation_id'): recovery_hex(value[key],32)
    recovery_hex(value['commit_sha'],40); recovery_hex(value['archive_sha256'],64)
    recovery_date(value['installed_at']); recovery_exact(value['binary'],{'sha256','size'})
    recovery_hex(value['binary']['sha256'],64)
    recovery_valid(type(value['binary']['size']) is int and 0<value['binary']['size']<=128*1024*1024)
    if value['origin']=='reviewed-baseline':
        pins={'x86_64':('92bfaa6177d87790bae79caea08d8ddddd0ca3ebc95545c1d62374897592c6c3',
                        '53da315a9f61975913235f72c4adb413313089b966ffcca700653b4663d3d964'),
              'aarch64':('16bfd0e78b746171b0434c935ca953358c88b43cfb0091d7b74cb982424202a3',
                        '308271c73ece5d748aeab21680c10c2bea153ba29c83135b1b84aa79a394173c')}
        archive,binary=pins[value['architecture']]
        recovery_valid(value['installed_version']=='3.5.12' and
            value['commit_sha']=='c4555e25f39dd5be200ccf6353f7d82bfcf89131' and
            value['archive_sha256']==archive and value['binary']['sha256']==binary and
            value['trust_policy']=='embedded-reviewed-baseline-v1' and
            all(value[key] is None for key in ('tag_object_sha','tag_verification','release','asset','checksum_asset')))
        return
    recovery_valid(value['origin']=='official-release' and
        value['trust_policy']=='github-verified-tag-and-official-asset-sha256-v1')
    recovery_hex(value['tag_object_sha'],40)
    verification=value['tag_verification']; recovery_exact(verification,{'verified','reason','verified_at'})
    recovery_valid(verification['verified'] is True and verification['reason']=='valid')
    recovery_date(verification['verified_at'],optional=True)
    release=value['release']; recovery_exact(release,{'id','tag','published_at','draft','prerelease','target_commitish','url','html_url'})
    recovery_valid(type(release['id']) is int and 0<release['id']<2**63 and release['tag']==value['tag'] and
        release['draft'] is False and release['prerelease'] is False and
        release['url']==f'https://api.github.com/repos/telemt/telemt/releases/{release["id"]}' and
        release['html_url']=='https://github.com/telemt/telemt/releases/tag/'+value['tag'] and
        isinstance(release['target_commitish'],str) and 0<len(release['target_commitish'])<=256)
    recovery_date(release['published_at'])
    if re.fullmatch('[0-9a-f]{40}',release['target_commitish']):
        recovery_valid(release['target_commitish']==value['commit_sha'])
    for key,suffix in (('asset',''),('checksum_asset','.sha256')):
        asset=value[key]; recovery_exact(asset,{'id','name','size','url','api_url','sha256'})
        name='telemt-'+value['architecture']+'-linux-gnu.tar.gz'+suffix
        recovery_valid(type(asset['id']) is int and asset['id']>0 and type(asset['size']) is int and
            0<asset['size']<=(512 if suffix else 128*1024*1024) and asset['name']==name and
            asset['url']=='https://github.com/telemt/telemt/releases/download/'+value['tag']+'/'+name and
            asset['api_url']==f'https://api.github.com/repos/telemt/telemt/releases/assets/{asset["id"]}')
        recovery_hex(asset['sha256'],64)
    recovery_valid(value['asset']['id']!=value['checksum_asset']['id'] and
                   value['archive_sha256']==value['asset']['sha256'])

def recovery_journal(value):
    recovery_valid(type(value['sequence']) is int and 0<=value['sequence']<=10000 and
        type(value['restored']) is bool and type(value['normalized']) is bool and
        value['kind'] in ('update','baseline-migration','baseline-install') and
        value['error'] in (None,'interrupted','validation-failed','recovery-failed','cleanup-failed') and
        value['service'] in (None,'enabled-active','disabled-active'))
    recovery_hex(value['transaction_id'],32); recovery_date(value['created_at'])
    if value['lkg'] is not None: recovery_hex(value['lkg'],32)
    supervisor=value['supervisor']; recovery_exact(supervisor,{'pid','starttime','boot_id'})
    recovery_valid(type(supervisor['pid']) is int and supervisor['pid']>0 and
        isinstance(supervisor['starttime'],str) and re.fullmatch('[0-9]{1,24}',supervisor['starttime']) and
        isinstance(supervisor['boot_id'],str) and re.fullmatch('[0-9a-f-]{36}',supervisor['boot_id']))
    recovery_valid(type(value['immutable']) is dict and len(value['immutable'])<=256)
    for key,digest in value['immutable'].items():
        recovery_valid(isinstance(key,str) and 0<len(key)<=512 and all(32<=ord(c)<127 for c in key)); recovery_hex(digest,64)
    for key in ('old','new'):
        if value[key] is None:
            recovery_valid(key=='new' and value['phase']=='ROLLBACK_COMPLETE'); continue
        recovery_exact(value[key],{'receipt','receipt_present'})
        recovery_valid(type(value[key]['receipt_present']) is bool); recovery_receipt(value[key]['receipt'])
    if value['snapshot'] is not None:
        snapshot=value['snapshot']; recovery_exact(snapshot,{'sha256','entries','logical_bytes','generation_id'})
        recovery_hex(snapshot['sha256'],64); recovery_hex(snapshot['generation_id'],32)
        recovery_valid(value['kind']=='update' and type(snapshot['entries']) is int and 0<snapshot['entries']<=100000 and
            type(snapshot['logical_bytes']) is int and 0<=snapshot['logical_bytes']<=8*1024**3 and
            snapshot['generation_id']==value['old']['receipt']['generation_id'])

def bootstrap_recovery_barrier():
    gate=systemd_root/'telemt.service.d/50-telemt-web-manager-update.conf'
    recovery=systemd_root/'telemt-web-manager-recovery.service'
    deployed_gate=any(os.path.lexists(p) for p in (gate,recovery))
    if not state.exists():
        if deployed_gate: raise ValueError('Recovery gate without state; retain installed manager for manual recovery')
        return
    safe(state)
    if stat.S_IMODE(state.stat().st_mode) != 0o700: raise ValueError('Unsafe manager state')
    candidate = source / 'telemt-web-manager.sh'
    required = []; records={}
    for filename, kind in (('telemt-release.json', 'RECEIPT'), ('update-journal.json', 'JOURNAL'),
                           ('telemt-generation.json', 'GATE')):
        path = state / filename
        if os.path.lexists(path):
            value = recovery_record(path)
            records[kind]=value
            if kind == 'JOURNAL':
                if value.get('phase') not in ('COMMITTED','ROLLBACK_COMPLETE') or value.get('intent') is not None:
                    raise ValueError('Pending/critical Telemt update: recover with the installed manager before replacing it')
            required.append((kind, value['schema']))
    if required or deployed_gate:
        if set(records)!={'RECEIPT','JOURNAL','GATE'} or not deployed_gate:
            raise ValueError('Incomplete deployed recovery contract; retain installed manager')
        expected={'RECEIPT':{'schema','origin','repository','architecture','installed_version','tag','tag_object_sha',
            'commit_sha','tag_verification','release','asset','checksum_asset','archive_sha256','binary','installed_at',
            'manager_version','transaction_id','generation_id','trust_policy'},
            'JOURNAL':{'schema','transaction_id','phase','intent','sequence','old','new','snapshot','immutable','service',
                       'supervisor','created_at','error','lkg','restored','kind','normalized'},
            'GATE':{'schema','generation_id','binary','receipt_sha256'}}
        if any(set(value)!=expected[kind] or value['schema']!=1 for kind,value in records.items()):
            raise ValueError('Unsupported/malformed deployed recovery state')
        receipt, journal, generation = (records[k] for k in ('RECEIPT','JOURNAL','GATE'))
        recovery_receipt(receipt); recovery_journal(journal)
        recovery_hex(generation['generation_id'],32); recovery_hex(generation['receipt_sha256'],64)
        authoritative=journal['new'] if journal['phase']=='COMMITTED' else journal['old']
        if (type(authoritative) is not dict or set(authoritative)!={'receipt','receipt_present'}
            or authoritative['receipt']!=receipt or authoritative['receipt_present'] is not True
            or generation['generation_id']!=receipt['generation_id'] or generation['binary']!=receipt['binary']
            or generation['receipt_sha256']!=hashlib.sha256(json.dumps(receipt,sort_keys=True,separators=(',',':')).encode()+b'\n').hexdigest()
            or type(journal['normalized']) is not bool or journal['error']=='cleanup-failed'
            or (journal['snapshot'] and not journal['normalized'])):
            raise ValueError('Deployed generation or retention is incomplete; recover before manager replacement')
        prefix=state.parents[2]
        binary=prefix/'usr/local/bin/telemt'; safe(binary,regular=True)
        info=binary.stat()
        recovery_valid(info.st_gid==0 and stat.S_IMODE(info.st_mode)==0o755 and info.st_size==receipt['binary']['size'])
        fd=os.open(binary,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as stream:
            digest=hashlib.sha256(); count=0
            while block:=stream.read(1048576):
                count+=len(block); recovery_valid(count<=receipt['binary']['size']); digest.update(block)
        recovery_valid(digest.hexdigest()==receipt['binary']['sha256'] and
                       (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)==
                       (binary.stat().st_dev,binary.stat().st_ino,binary.stat().st_size,binary.stat().st_mtime_ns))
        marker=recovery_record(prefix/'var/lib/telemt/.telemt-web-manager-generation.json')
        recovery_exact(marker,{'schema','generation_id'})
        recovery_valid(marker['schema']==1 and marker['generation_id']==receipt['generation_id'])
        safe(gate.parent)
        recovery_valid({p.name for p in gate.parent.iterdir()}=={gate.name})
        # Parse helper source as data too: advertised shell schema and Python
        # schema literal must agree. compile() elsewhere checks syntax only.
        module = ast.parse((source / 'safety.py').read_bytes())
        definitions={node.targets[0].id:node.value.value for node in module.body
            if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name)
            and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str)}
        for path,name in ((gate,'UPDATE_DROPIN'),(recovery,'UPDATE_RECOVERY_UNIT')):
            safe(path,regular=True)
            if stat.S_IMODE(path.stat().st_mode)!=0o644 or path.stat().st_size>4096 or definitions.get(name)!=path.read_text():
                raise ValueError('Candidate does not preserve the deployed exact gate/recovery contract')
        schemas = [node.value.value for node in module.body if isinstance(node, ast.Assign)
                   and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                   and node.targets[0].id == 'UPDATE_SCHEMA' and isinstance(node.value, ast.Constant)
                   and type(node.value.value) is int]
        if len(schemas) != 1: raise ValueError('Candidate does not understand installed recovery state')
        for kind, schema in required:
            if schema not in static_schemas(candidate, kind) or schemas[0] != schema:
                raise ValueError('Candidate cannot interpret deployed recovery schema; explicit downgrade also refused')

wrapper = ('#!/bin/sh\nexec ' + str(dest / 'telemt-web-manager.sh') + ' "$@"\n').encode()
stage = None
staged_launchers = {}
created_launchers = []
swapped = created = committed = False
libc = ctypes.CDLL(None, use_errno=True)
exchange = getattr(libc, 'renameat2', None)
if exchange is None: raise SystemExit('ERROR: Atomic directory exchange unavailable')
exchange.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
exchange.restype = ctypes.c_int

def swap(a, b):
    if exchange(-100, os.fsencode(a), -100, os.fsencode(b), 2):
        raise OSError(ctypes.get_errno(), 'Atomic manager directory exchange failed')

def interrupted(signum, frame):
    if not committed: raise InterruptedError('Bootstrap interrupted')
for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP): signal.signal(sig, interrupted)
try:
    safe(dest.parent); safe(lock.parent)
    for target in launchers: safe(target.parent)
    with os.fdopen(os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600), 'r+') as held:
        info = os.fstat(held.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('Unsafe manager lock')
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        had_pair = existing_pair()
        bootstrap_recovery_barrier()
        missing_launchers = []
        for target in launchers:
            safe(target, regular=True)
            if target.exists():
                if target.read_bytes() != wrapper:
                    raise ValueError('Unrelated launcher; manual review required')
                if stat.S_IMODE(target.stat().st_mode) != 0o755 or target.stat().st_gid != 0:
                    raise ValueError('Existing launcher mode requires manual review')
            else: missing_launchers.append(target)
        if had_pair:
            installed = manager_version(dest / 'telemt-web-manager.sh')
            if not explicit and version_key(tag[1:]) < version_key(installed):
                raise ValueError(f'Installed manager {installed}; automatically selected {tag}; '
                                 'automatic downgrade refused. Use --version for an intentional published version.')
        # All validation and downgrade checks precede installation staging/commit files.
        stage = Path(tempfile.mkdtemp(prefix='.telemt-web-manager.', dir=dest.parent))
        (stage / 'lib').mkdir(0o755)
        for src, relative, mode in ((source / 'telemt-web-manager.sh', 'telemt-web-manager.sh', 0o755), (source / 'safety.py', 'lib/safety.py', 0o644)):
            target = stage / relative
            shutil.copyfile(src, target)
            os.chown(target, 0, 0); target.chmod(mode)
        os.chown(stage, 0, 0); os.chown(stage / 'lib', 0, 0)
        stage.chmod(0o755); (stage / 'lib').chmod(0o755)
        for target in missing_launchers:
            fd, filename = tempfile.mkstemp(prefix='.telemt-web-manager.', dir=target.parent)
            staged = Path(filename)
            staged_launchers[target] = staged
            with os.fdopen(fd, 'wb') as output:
                output.write(wrapper)
                output.flush(); os.fsync(output.fileno())
            os.chown(staged, 0, 0); staged.chmod(0o755)
        # Block catchable signals only across the tiny commit/rollback window.
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})
        try:
            if had_pair: swap(stage, dest); swapped = True
            else: os.rename(stage, dest); created = True
            for target, staged in staged_launchers.items():
                os.replace(staged, target); created_launchers.append(target)
            committed = True
        except BaseException:
            if swapped: swap(stage, dest); swapped = False
            elif created: os.rename(dest, stage); created = False
            for target in reversed(created_launchers): target.unlink()
            created_launchers.clear()
            raise
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
except (OSError, ValueError) as error:
    print('ERROR: ' + str(error), file=sys.stderr); sys.exit(1)
finally:
    if stage is not None and stage.exists():
        if swapped and not committed:
            print(f'ERROR: Rollback exchange failed; previous manager pair retained at {stage}; manual recovery required', file=sys.stderr)
        else: shutil.rmtree(stage)
    for staged in staged_launchers.values():
        if staged.exists(): staged.unlink()
PY
    } | python3 - "$BOOTSTRAP_TMP" "$INSTALL_DIR" "$LAUNCHER" "$BOOTSTRAP_LOCK" "$MANAGER_TAG" "$VERSION" "$MANAGER_STATE" "$MANAGER_SYSTEMD_ROOT" "${CANONICAL_LAUNCHER:-${LAUNCHER%/*}/telegram-web-proxy-manager}"
}

launch_manager_menu() {
    if (( ! NO_START )) && [[ -t 0 && -t 1 ]]; then "${CANONICAL_LAUNCHER:-${LAUNCHER%/*}/telegram-web-proxy-manager}"; fi
}

bootstrap_main() {
    (( EUID == 0 )) || bootstrap_die 'Run the manager installer as root'
    while (( $# )); do
        case $1 in
            --version)
                [[ -z $VERSION ]] || bootstrap_die 'Duplicate --version'
                (( $# >= 2 )) || bootstrap_die 'Missing --version tag'
                VERSION=$2
                [[ -n $VERSION ]] || bootstrap_die 'Missing --version tag'
                shift 2;;
            --no-start) NO_START=1; shift;;
            *) bootstrap_die 'Usage: install.sh [--version vX.Y.Z] [--no-start]';;
        esac
    done
    local tool
    for tool in bash curl python3 mktemp rm; do command -v "$tool" >/dev/null || bootstrap_die "Missing dependency: $tool"; done
    python3 -c 'import sys; sys.exit(sys.version_info < (3,11))' || bootstrap_die 'Python 3.11+ required'
    BOOTSTRAP_TMP=$(mktemp -d)
    trap 'rm -rf -- "$BOOTSTRAP_TMP"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM HUP
    resolve_manager_repository
    resolve_manager_release
    local base="https://raw.githubusercontent.com/$MANAGER_REPO/$MANAGER_COMMIT"
    bootstrap_download "$base/telemt-web-manager.sh" "$BOOTSTRAP_TMP/telemt-web-manager.sh" || bootstrap_die 'Manager shell download failed/empty'
    bootstrap_download "$base/lib/safety.py" "$BOOTSTRAP_TMP/safety.py" || bootstrap_die 'Manager helper download failed/empty'
    validate_manager_pair || bootstrap_die 'Invalid manager Python/Bash syntax'
    commit_manager_pair || bootstrap_die 'Manager installation transaction failed; review the error above'
    printf 'Installed manager %s (%s). Run: telegram-web-proxy-manager\n' "$MANAGER_TAG" "$MANAGER_COMMIT"
    rm -rf -- "$BOOTSTRAP_TMP"; BOOTSTRAP_TMP=''
    launch_manager_menu
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then bootstrap_main "$@"; fi
