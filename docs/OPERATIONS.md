# Operations, security and recovery

[Русская главная](../README.md) | [English front page](../README.en.md) | [Upstream audit](UPSTREAM.md)

This document contains the detailed deployment and trust-boundary material.
Start with the README installation commands. Examples use TEST-NET and example.com.

Supported Telemt: **3.5.11**. See [upstream provenance](UPSTREAM.md) and the
[REAL/MOCKED CI coverage inventory](CI-COVERAGE.md).

## Nginx requirements

The manager parses the include tree rather than doing regex substitutions.
Recognized stream example:

```nginx
map $ssl_preread_server_name $sni_name {
    hostnames;
    panel.example.com www;
    reality.example.com xray;
    default xray;
}
upstream xray { server 127.0.0.1:8443; }
upstream www { server 127.0.0.1:7443; }
server {
    proxy_protocol on;
    set_real_ip_from unix:;
    listen 443;
    listen [::]:443;
    proxy_pass $sni_name;
    ssl_preread on;
}
```

`http` must directly include `conf.d/*.conf` through an absolute or relative path.
One stream/map/router, exact SNI names, default route, upstream selector and
loopback frontend are supported. Each named stream upstream must contain one
plain loopback server; extra stream context directives or upstream options are
refused. Existing routes are preserved. Optional
`hostnames;` may occur once before entries, which must still be exact names.
Only the exact optional `set_real_ip_from unix:;` form is accepted; incoming PROXY
protocol on public listeners is refused. Shared HTTP snippets may be included by
several vhosts. Existing HTTP regex, escaping and `${variable}` forms are preserved;
escaped directive/include/listen names and ambiguous syntax are refused.
Re-running does not duplicate mapping/upstream/vhost. New includes or changes
during staging cause refusal.

Regex/wildcard SNI maps, nested dynamic routing, multiple routers, unknown listen
flags/addresses, custom `nginx -c/-p`, occupied private ports and direct HTTPS
without a stream router are not automatically configured. Unknown setups are not
converted into this example. Existing `[::]:443` is preserved; IPv6 Telemt egress
and a new WEB-domain AAAA record are not enabled automatically.

The frontend trusts PROXY only from loopback, sends one canonical X-Forwarded-For
over HTTP/1.1, disables buffering/retries and uses 90-second timeouts. Public HTTP/2
is enabled. Carrier is `https`, so WebSocket Upgrade is not enabled. Access logging
is disabled; the WEB vhost error log goes to `/dev/null` to keep capability URLs
out of logs. This reduces diagnostics while protecting bearer credentials.

## SOCKS5 and Telegram egress

```bash
/opt/telemt-web-manager/telemt-web-manager.sh --install \
  --domain proxy.example.com --public-ip 203.0.113.10 --socks 127.0.0.1:1080
```

The SOCKS handshake and verified HTTPS connection to `api.telegram.org` use SOCKS5h.
This checks Telegram reachability, not egress geography or every DC. Cloudflare
trace is not used. Xray/3x-ui are optional; their database/configuration and
firewall/UFW are untouched. SOCKS authentication and IPv6 upstream need manual review.

## TLS / Certbot

Manager-associated certificates are found in `/etc/letsencrypt/live/DOMAIN/`. Validation covers
hostname, expiry beyond seven days, private key permissions, ownership, safe
Certbot symlinks within archive/DOMAIN and matching public keys. HTTP probes check
TLS trust. For new issuance, explicitly accept ACME terms with `--email` and `--agree-tos`.

Free port 80 uses standalone HTTP-01 without stopping Nginx. If the port belongs
to the same verified Nginx master/workers, webroot supports recognized HTTP
redirect vhosts: `listen 80`, exact `server_name` values and
`return 301 https://$host$request_uri`. Wildcard/regex names, custom HTTP routing,
conflicting domains and unrelated processes cause refusal.
Port-80 runtime/config disagreement also causes refusal, preventing pending
Nginx configuration from invalidating a standalone renewal strategy.

After backup, a separate managed vhost serves `/.well-known/acme-challenge/`
from a root-owned webroot; other requests get 404. `nginx -t` and reload precede
a local challenge-file probe. Certbot runs `certonly --webroot --webroot-path`,
records renewal settings, then certificate and renewal contracts are checked.
Failure/signals restore ACME changes and reload valid previous configuration;
existing vhosts are untouched. Only issuance followed by successful certificate and renewal validation commits
the persistent vhost/webroot for renewal, even if later Telemt installation fails.
Empty webroot directories may remain after failure; inspect backup/marker before retrying.

Check external reachability of 80/443 yourself; firewall rules remain unchanged.
No new cron/timer is created. Installation and `--check` report enabled
`certbot.timer` or `snap.certbot.renew.timer`. If neither is enabled, a WARNING
asks you to verify cron/custom scheduling; this alone does not fail the check.

Every managed installation load (`--check`, `--update`, `--repair`, install rerun)
validates certificate paths, key/hostname/expiry, renewal settings and the
manager deploy hook. Standalone requires actual TCP port 80 to remain free:
`ss -H -ltn 'sport = :80'` includes IPv4/IPv6, wildcard and loopback listeners.
Any listener or socket-inspection failure causes refusal. This is deliberately
conservative: [Certbot standalone](https://eff-certbot.readthedocs.io/en/stable/using.html#standalone)
tries IPv6 and IPv4 and can continue if only one bind succeeds, which does not
prove the challenge reaches that socket. Webroot instead requires its verified
Nginx port-80 owner and persistent managed state; it does not require free port 80.

The canonical `/etc/letsencrypt/renewal-hooks/deploy/telemt-web-manager` hook runs
`/usr/sbin/nginx -t`, then `/usr/bin/systemctl reload nginx`. Validation never
executes it: safe ancestors, regular non-symlink file, root ownership, owner execute
permission, no group/other writes or special mode bits, and byte-exact canonical
content are required. Fresh installation creates it transactionally with mode
0750. Missing, changed or unsafe hooks require manual review; check/update/repair
never recreate them. Existing schema-1 manifests remain compatible without new
fields or automatic migration.

For a port conflict, review renewal strategy manually without stopping an
unrelated service automatically. No authenticator, renewal file, hook, Nginx
configuration or firewall is repaired by health checking. After either flow run
`certbot renew --dry-run` on a test VPS.
CI does not perform real ACME issuance.

## Certificate recovery

### Recovering partial Certbot success

If Certbot issued a certificate but post-validation failed, the certificate,
account and renewal file remain. ACME Nginx edits and the ownership marker may
have rolled back. A second install must not report success with broken renewal.
It refuses incomplete state and never deletes/reissues the surviving lineage.

Recovery is deliberately a root administrator decision:

1. Save private backups of the relevant Certbot lineage/renewal file and Nginx
   configuration. Never paste keys or account data into an issue.
2. Inspect the exact authenticator, webroot_path and per-domain map in
   `/etc/letsencrypt/renewal/DOMAIN.conf`. Verify domain, certificate/key, validity
   and the original manager backup/ACME plan. Do not alter an unrelated lineage.
3. If the original manager contract is proven, restore its exact ACME vhost from
   the reviewed plan, its root-owned webroot/challenge directories and domain
   marker. The rendered vhost must equal `render_acme(DOMAIN, ACME_ROOT)`, with
   exactly one HTTP include. A backup snapshot taken before creation might not
   contain the new file; the ACME plan records its desired content.
4. Run `nginx -t`, reload and verify local and external HTTP-01 challenge serving.
   Run `certbot renew --dry-run` on the disposable test VPS before retrying install.
5. If ownership/topology cannot be proven, review and repair the renewal strategy
   manually with Certbot. The manager does not automatically adopt a foreign
   certificate or rewrite its renewal parameters.

Do not create a marker merely to bypass refusal. It asserts an independently
reviewed Nginx/webroot contract. Restoring only the PEM files is insufficient.
Existing standalone certificates without a manager manifest are also refused;
this includes a certificate left by a failed standalone first installation.
The manager does not infer ownership from the hostname alone.

## Updates and rollback

```bash
/opt/telemt-web-manager/telemt-web-manager.sh --update
```

Only recognized manager-owned installations are updated. Other existing Telemt
installations require unit/config/topology review, even with the same service
name. Managed TOML edits must retain the supported WEB/runtime contract;
unknown includes/schemas are refused.

Matching versions report `already up to date`, then check health. Otherwise the
verified candidate runs `healthcheck` on the **current config** before backup,
atomic binary replacement and restart. TOML stays byte-for-byte unchanged; binary
updates do not modify Nginx, cert or unit. There are no automatic TOML migrations.
Validation failure stops the update. The only download target is the reviewed
3.5.11 pin, with embedded official asset hashes. Older compatible managed installs
can upgrade to it; newer installs refuse before download and require manual review
or a newer reviewed manager. Equal SemVer precedence with a different exact version
(such as an unreviewed build suffix) also refuses. Future releases require an explicit
manager change.
Candidates must pass managed WEB/write-path validation and strict-parser probes;
systemd enforces the writable boundary, and runtime failures trigger rollback. Older manager configs with quota outside
`state` require manual review; updates do not add strict mode or rewrite paths.
TOML hashes are checked before/after candidate healthcheck and before activation.

After restart, readiness polls systemd and the real listener for up to 90 seconds.
Checks cover listener PID ownership, UID/capabilities, decoy, full local TLS,
public HTTPS, SOCKS and recent logs. Failure restores/restarts the old binary.
Failed rollback emits CRITICAL and the backup path. TCP sessions are not restored.

Backups: `/root/telemt-backups/TIMESTAMP.RANDOM/`, 0700. `files.tsv` maps indexes
to destinations; `nginx-plan.json` records changed originals and include hashes;
`nginx-snapshot/` holds the complete read config tree. Backups may contain private
TOML and are never automatically deleted. SIGINT/TERM/HUP and ordinary failures
trigger rollback. SIGKILL, power loss and disk failure require manual recovery.

Fresh-install rollback records successful account creation (exact passwd/group
records, UID/GID and home/shell) and created directory device/inode identities in
`fresh-ownership.json` inside the private backup. Critical creation/recording windows
block catchable signals. Existing paths/accounts are never adopted. An unsuccessful
partial useradd is not ownership proof and requires manual recovery.

A failed fresh activation first stops/disables Telemt, verifies that no process has
the recorded UID, validates account/directory identities and refuses mount points
(including same-device bind mounts). It removes/restores tracked files, reloads
systemd and restores Nginx before recursively removing only recorded fresh roots.
Cleanup uses directory file descriptors and O_NOFOLLOW; runtime symlinks are unlinked,
never traversed. Account deletion uses neither force nor recursive-home options;
private-group removal handles userdel already having removed it. Stop, identity,
mount or cleanup failures emit CRITICAL and retain the backup evidence for manual
recovery. Successfully issued certificates and committed manager ACME webroot,
marker and renewal vhost remain outside this cleanup. A clean retry reuses valid
manager-owned webroot certificate state without unnecessary issuance.

## Check and repair

`--check` leaves managed configuration/services unchanged. It reports versions,
systemd state, SubState/NRestarts, identity/capabilities, listener, Nginx/HTTP/TLS,
expiry, SOCKS and classifications from the last five minutes of logs. Raw journal
lines are not printed. Root is required; private temporary diagnostics are deleted.
Version reporting is local: manager, installed Telemt and supported Telemt 3.5.11.
A mismatch reports unsupported status and returns nonzero; no latest-release query
is made. WARN records only contribute a diagnostic count. ERROR/FATAL and genuine
Rust panic records fail; malformed journal transport or unsafe controls fail closed.
Payload words such as `error=`, `conntrack` or `Permission denied` cannot promote
a WARN. Every line of multiline records is checked for structured fatal prefixes.
The unlevelled upstream `MAESTRO: ` banner is diagnostic and never printed.

Check safely creates/opens the common lock and takes shared flock, including the
first invocation after reboot. Several checks may coexist; mutations take exclusive
flock. Conflicts fail immediately. Symlink/FIFO/hardlink locks and unsafe permissions
are refused. Lock/temp files are operational writes of read-only diagnostics.
Managed webroot installs also verify persistent ACME vhost, marker and renewal settings.

`--repair` checks manifest ownership, unit/vhost hashes, topology and config
healthcheck; backs up; restarts Telemt and reloads valid Nginx. It does not guess
how to reconstruct changed/damaged files. Cert renewal problems, inactive Nginx
and foreign units/drop-ins need manual review.

## Systemd and security

`User=telemt`, `Group=telemt`, only `CAP_NET_ADMIN`; `NoNewPrivileges`,
`ProtectSystem=strict`, `ProtectHome`, private tmp/devices, kernel/control-group
protections, restricted address families/realtime/SUID/namespaces, W^X and personality.
Limits: 65536 descriptors, 4096 tasks, MemoryMax=1G. Review VPS capacity/workload;
external unit edits require review. CAP_NET_ADMIN remains for upstream conntrack
cleanup even in tracked mode. Telemt 3.5.11 requires `conntrack` on its PATH;
Ubuntu provides it in the `conntrack` package. Preflight checks it and the account
creation/deletion tools (`getent`, `useradd`, `userdel`, `groupdel`) before temporary
transaction setup, downloads or ACME. `systemd-path search-binaries-default`
verifies runtime discovery without changing the generated service PATH. Generated
conntrack policy remains inline enabled and tracked. All WARNs are diagnostic;
actual ERROR/FATAL/panic records and objective health failures still fail.
Evidence is in upstream notes.

Fresh TOML sets `general.config_strict = true`, `disable_colors = true`, and
`data_path = /var/lib/telemt`. Colors are disabled for deterministic systemd logs;
existing TOML is never rewritten to add the flag.
Active beobachten and quota state explicitly use `/var/lib/telemt/state`.
Unknown-DC log (disabled), public-IP cache (unused by the reviewed probe),
middle-proxy secret/config caches (middle proxy disabled) and TLS-front cache
(emulation disabled) also point inside `state`. No file logging: stderr goes to
journald. ReadWritePaths remains only `/var/lib/telemt/state`; decoy and remaining
DATA are root-owned. Upstream notes contain the audit table; this is source review,
not a VPS runtime persistence test.

Positional-config ExecStart remains: upstream default Run is already foreground,
without daemonization/PID file. systemd Type=simple controls the process directly;
SIGTERM triggers graceful cleanup/quota save. TimeoutStopSec is 180s because
individual firewall commands can wait 30s. Exceeding the deadline may still kill
the process before persistence completes.

## Tests

```bash
for file in install.sh telemt-web-manager.sh tests/*.sh; do bash -n "$file"; done
shellcheck -x install.sh telemt-web-manager.sh tests/*.sh
bash tests/run.sh
bash tests/fresh.sh
bash tests/fresh-rollback.sh # late journal failure, ACME preservation/retry, partial failures
sudo bash tests/fresh-account.sh # disposable runner only: real account/runtime cleanup
bash tests/preflight.sh # Missing conntrack/account tools before transaction dispatch
bash tests/download.sh   # Real pinned download; mocked bad-digest/URL/version negatives
bash tests/contracts.sh  # Strict config, writable paths, unit
bash tests/locks.sh      # Shared/exclusive races, unsafe lock paths
bash tests/acme.sh       # Certbot mocks, refusal, rollback, renewal/idempotence
sudo bash tests/renewal.sh # Root-owned hook, standalone sockets, scheduler visibility
bash tests/pinned.sh     # Official pin metadata, both asset digests, docs agreement
bash tests/upstream.sh   # Real pinned binary config healthcheck; no process startup
bash tests/staging.sh    # Real config healthcheck; lifecycle/path/journal transport mocked
sudo bash tests/runtime.sh # Disposable runner: actual Telemt, isolated net namespace
bash tests/pinned.sh --versions # With TELEMT_TEST_EVIDENCE_DIR from all three layers
bash tests/bootstrap_versions.sh # SemVer, installed parser and paginated release fixtures
sudo bash tests/bootstrap.sh # Root-owned isolated bootstrap atomicity/release/TTY fixtures
bash tests/conntrack.sh  # CI: sudo + isolated namespace, actual Noble nf_tables
bash tests/nginx.sh      # nginx + libnginx-mod-stream; private ports
bash tests/three-x-ui.sh  # Internet + Nginx: both full upstream configurations
```

Fixtures use TEST-NET/example.com, no production credentials. Secrets are generated
only in temporary environments and never printed. Ubuntu 24.04 CI uses real Nginx
stream/PROXY/TLS and canonical X-Forwarded-For. Fixtures do not replace live acceptance
on Ubuntu 26.04, arm64 and Telegram clients.

Both 3x-ui-pro scripts are downloaded at the pinned commit, Git blob hashes checked,
and Nginx heredocs rendered with inert values. Installer/patcher are never executed.
Tests cover mocked full install, idempotence, byte-for-byte rollback and real
Nginx/TLS/PROXY/XFF over IPv4/IPv6. Minimal fixtures cover unsafe variants/include
cycles. Real Nginx checks ACME challenges/404 and preserved HTTP redirects. Python
checks traversal/hardlink/symlink/duplicate archives and unsafe ancestors.
Downloads/members are limited to 128 MiB; extraction timeout is 60s.

Parsing/snapshot checks cannot exclude an external root editor: do not edit configs
during installation. Symlink/write-permission checks protect against unprivileged
substitution; the root administrator remains the trust boundary.

## Manual recovery and removal

Save a private backup and inspect `files.tsv`. Stop Telemt; restore a root-owned
executable binary. Restore TOML deliberately from the matching backup (root:telemt,
0640). After unit restoration run `systemctl daemon-reload`. Always run `nginx -t`
before reload.

There is no automatic `--uninstall`. Run `systemctl disable --now telemt.service`,
then manually remove only manager files, its exact SNI entry and `twm_frontend`.
Validate/reload Nginx. Preserve unrelated routes, certs, x-ui DB, firewall and backups.
Remove the `telemt` account only after confirming nothing else uses it.
If the certificate is still needed, retain persistent ACME vhost/webroot/hook or
first move renewal to another strategy. Removing them can break renewal;
certificates are not automatically deleted.

Failed fresh installs remove only transaction-owned Telemt directories/accounts
after service, identity and mount checks. Committed certificates and ACME renewal
state remain. Unsafe or incomplete rollback emits CRITICAL and retains the private
ownership journal/backups; inspect them before manual recovery or retry.

## Live acceptance fixes: MIME data and release compatibility

A normal Ubuntu nginx.conf includes mime.types. Earlier real-Nginx tests used a
synthetic main config without this include: upstream heredocs were covered but
package-owned configuration was omitted. CI now copies the installed package's
actual mime.types bytes into each isolated trusted Nginx tree, parses both plans,
asserts its snapshot hash, then runs real Nginx with it, including both pinned
3x-ui-pro topologies. No production config or include trust expansion is needed.

The parser marks flat types{} entries as data records. Generic directive traversal
and include expansion cannot see them as listen/server_name/include/etc. Ordinary
directive-name restrictions and map{} grammar are retained. Nested MIME blocks
are refused. Every included source still participates in integrity snapshots.

Fresh install verifies the pinned official asset, embedded digest, archive and exact
binary version before constructing a private, usable compatibility filesystem under
`$TMP/compat-data`: `state`, `public` and the same immutable `public/index.html`
used in production. One parameterized TOML generator and one decoy writer create
both stages. Only the data-root prefix changes; secret, hostname, listener,
upstream and every other setting stay identical.

The pre-certificate candidate contract takes its expected data root explicitly.
Semantic WEB/write-path checks, positive healthcheck and unknown-key rejection
run on private copies, with hash checks rejecting mutation. Production paths,
accounts, unit, manifest and permanent WEB integration are not created at this
stage. Only a compatible staged candidate can reach Certbot. After certificate
issuance and transaction setup, real managed directories/index and final TOML
are created. The same candidate validates the exact final config on private
copies before binary activation, followed by readiness, path and journal checks.
Temporary data is removed by normal cleanup. Post-issuance certificate retention
and rollback policy is unchanged.

The v0.1.0 coverage gap was the combination of a real binary and fresh ordering:
`upstream.sh` pre-created DATA/public/index.html, while `fresh.sh` mocked healthcheck.
`staging.sh` now verifies the official pinned 3.5.11 digest and runs the actual
binary through fresh orchestration in direct and SOCKS modes. It proves the old
absent-directory state and a missing index fail, usable staging succeeds, strict
unknown keys fail, final paths never contain staging, config semantics match,
and incompatible/missing-decoy candidates never reach even the mocked Certbot
boundary. OS/account/systemd/ACME actions remain fixtures; this is not live issuance.

Updates validate the installed runtime/configuration and compare it with the fixed
3.5.11 target. Equal versions keep the health checks; older compatible managed
installs upgrade, while newer ones refuse without downloading or modifying files.
Failures restore the old binary; config, unit, certificate and Nginx are not migrated.
No compatibility promise is made for future releases. The real runtime smoke
starts the exact pin with real Linux helpers and CAP_NET_ADMIN in a separate
network namespace. It first proves owned chains absent, verifies process-owned
listener/HTTP index again after a measured >=10-second dwell, and refuses pinned
conntrack reconciliation/retry/shutdown failure fragments in actual captured logs.
Production WARN classification stays generic; the seven 3.5.10 WARN records remain
historical regression input. Fatal classifier negatives, clean shutdown and
firewall state checks remain. It does not start
systemd or perform ACME issuance. See the coverage inventory for every CI step.

## Manager bootstrap

`install.sh` installs only the manager program pair and a fixed-path launcher.
It resolves releases from `xPROMSx/telemt-web-manager`, ignores drafts, prefers
the highest published stable SemVer, and uses the highest prerelease only while
no stable exists. SemVer prerelease tags are never classified as stable even if
GitHub's prerelease flag is false; a plain core tag flagged prerelease is supported.
Duplicate JSON fields fail closed. Release pages are enumerated with 100 entries
per page until a short page, up to 20 pages. A full twentieth page, failed page, malformed metadata or duplicate tag
causes refusal rather than selection from an incomplete/ambiguous history.
Publication timestamps validate published status but never decide precedence.
Core and numeric prerelease identifiers compare by digit length then ASCII digits,
without bounded integer conversion. Build metadata is accepted but ignored for
precedence; distinct highest tags of equal precedence require explicit `--version`.
The existing explicit-tag surface accepts a prerelease or a build suffix, not
both together. Default discovery retains its existing support for both suffixes;
ambiguities outside the explicit surface require manual review.
`--version v0.1.0` selects an explicit published tag, including prereleases.
The tag is resolved through official Git objects to a commit SHA; annotated tag
objects must identify the exact requested object SHA;
both files are fetched over HTTPS from that same immutable commit. Metadata
cannot supply an arbitrary download URL or repository. Release ambiguity, unsafe
ref syntax, failed/empty downloads, Bash/Python syntax errors all cause refusal.

The bootstrap script itself is fetched from main in the quick command; review it
or download it before execution if desired. The program pair is never installed
from mutable main. To test an unpublished PR/commit, use the advanced/manual
installation workflow with its reviewed immutable checkout.
The manager's release channel is independent from the fixed Telemt 3.5.11 pin.

Root and Python 3.11+ are required. No packages, firewall, Telemt configuration,
Nginx, Certbot, Xray or release/tag are changed. Validate both files first, then
take the same exclusive lock used by the manager. Root-owned safe ancestors,
non-symlink regular files, a recognized two-file existing installation, no extra
files, and an absent or exact canonical launcher are required. An unrelated
`/opt/telemt-web-manager` or `/usr/local/bin/telemt-web-manager` causes refusal.
Manual two-file installations from previous manager versions can be updated;
modified layouts require manual review. Under the exclusive lock, the canonical
installed manager is read as UTF-8 text; only one exact unquoted
`readonly SCRIPT_VERSION=MAJOR.MINOR.PATCH...` declaration immediately after the
fixed generated prologue is accepted. Missing,
malformed, duplicate or ambiguous declarations fail closed, including for explicit
updates. No installed shell content is sourced, evaluated or executed.
Downloaded file identity and declared version must also match the published tag.
For automatic selection, a candidate below the installed SemVer is refused before
any installation stage, directory replacement or launcher mutation. The error
shows both versions. Equal versions can safely reinstall; newer versions update.
An explicit valid published `--version` permits an intentional downgrade while
retaining every validation, path, lock and rollback safeguard.

The validated pair is staged beside `/opt/telemt-web-manager`. Linux `renameat2`
exchanges whole directories atomically for updates; a fresh directory is renamed
atomically. Launcher commit failure restores the old complete pair (or removes
the new pair on a fresh install). If the reverse exchange itself fails, retain
the previous pair's staging directory and report its path for manual recovery;
never delete the sole recoverable previous pair. Catchable signals are blocked
across this short commit window; cleanup deletes only disposable transaction stages.
Interrupted metadata/download operations also clean their private temporary files. Unsupported exchange,
unsafe lock, active manager or write failure causes refusal. Power loss/SIGKILL
and concurrent root edits remain manual recovery boundaries. Both installed
files and directories are root:root, script/launcher 0755 and helper 0644.
The launcher executes the fixed manager path and forwards arguments.

Rerun the quick command to update manager files without changing the managed
Telemt deployment. `--update` inside the manager instead updates Telemt. Close existing idle menus before updating; the lock excludes manager actions,
not an idle menu that has already loaded older shell functions. On a TTY
bootstrap launches the menu after releasing its lock; noninteractive use or
`--no-start` only installs the program files. CI uses root-owned temporary paths,
release/download fixtures and a fake menu, including a failure injected after
directory exchange; no production paths or release operations are tested.

## Advanced / manual installation

Review a trusted checkout (use the reviewed PR commit for an unpublished PR) and install both
files. This path does not install the convenient launcher:

```bash
git clone https://github.com/xPROMSx/telemt-web-manager.git
cd telemt-web-manager
bash -n telemt-web-manager.sh
shellcheck telemt-web-manager.sh
install -d -m 0755 /opt/telemt-web-manager/lib
install -m 0755 telemt-web-manager.sh /opt/telemt-web-manager/
install -m 0644 lib/safety.py /opt/telemt-web-manager/lib/
/opt/telemt-web-manager/telemt-web-manager.sh
```

Keep the installation root-owned and unwritable by others. Install missing
manager dependencies deliberately, without replacing the working Nginx stack:

```bash
apt-get update
apt-get install git shellcheck bash python3 curl ca-certificates tar openssl jq \
  dnsutils util-linux iproute2 coreutils passwd certbot iptables nftables conntrack
```

On a clean package Nginx, stream usually needs `libnginx-mod-stream`; match modules
to the installed Nginx and verify `nginx -t`. The manager checks dependencies.
Bootstrap options: `--version v0.1.1` selects a published release; `--no-start`
suppresses the menu. See [manager bootstrap](#manager-bootstrap).

