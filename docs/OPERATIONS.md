# Operations, security and recovery

[Русская главная](../README.md) | [English front page](../README.en.md) | [Upstream audit](UPSTREAM.md)

This document contains the detailed deployment and trust-boundary material.
Start with the README installation commands. Examples use TEST-NET and example.com.

Supported Telemt: **3.5.12** (fresh Install baseline). Universal Update (introduced in 0.2.0) is
compatibility-driven across all stable SemVer series. See [upstream provenance](UPSTREAM.md) and the
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

Universal Update verifies the newest official stable candidate against the exact
current managed TOML and state, with no major/minor gate. Matching exact versions
still verify provenance and objective health; newer installed versions refuse
downgrade. Custom/non-exact equal-precedence builds refuse. No automatic TOML
migration, Nginx/certificate modification, unmanaged adoption or Reinstall occurs.
See the complete [0.2.0 transaction and recovery contract](#universal-update-020).

Historical manager 0.1.3 acceptance upgraded 3.5.11 to the reviewed 3.5.12 pin.
Generated TOML/unit remain unchanged in 0.2.0: explicit inline control `true`,
tracked mode, default POST carrier and AF_NETLINK are retained. The additional
exact manager-owned systemd drop-in and root recovery unit implement the start gate.

Fresh Install and Uninstall backups remain under
`/root/telemt-backups/TIMESTAMP.RANDOM/`, 0700. `files.tsv`, `nginx-plan.json` and
`nginx-snapshot/` record prior files and Nginx bytes. They may contain secrets.
Fresh Install/Uninstall power loss, SIGKILL, disk failure and unrelated external
changes retain their manual-recovery boundaries; the durable automatic boot
recovery below applies specifically to Universal Update.

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

## Universal Update (0.2.0)

`--update` still means an existing healthy manager-owned deployment. It does not
implement Reinstall, adoption, automatic configuration migration or a general
rollback UI. The manager takes the same exclusive lock and recovers a pending
transaction before any further mutation. Check and Show use shared locks, remain
offline/read-only and refuse pending/CRITICAL state.

Discovery is fixed to official repository ID `1125007401`, name `telemt/telemt`.
Two complete release enumerations use 100-item pages through a short/empty final
page (at most 100 pages, 180 seconds per enumeration). Inventory drift, duplicate
IDs/tags/JSON keys, malformed new stable versions and equal-precedence ambiguity
refuse. Drafts and prereleases, including SemVer prereleases mislabeled stable,
are excluded. All major/minor series participate; the seven exact historical
malformed records below are the only quarantine:

| Release ID | Tag | Published UTC |
| --- | --- | --- |
| 286377748 | 2.0.0.1 | 2026-02-14T13:29:46Z |
| 285764063 | 1.2.0.2 | 2026-02-12T16:30:28Z |
| 278074445 | 1.1.1.0 | 2026-01-19T23:20:01Z |
| 275857798 | 1.0.3.0 | 2026-01-11T22:02:40Z |
| 274860393 | 1.0.2.0 | 2026-01-07T15:21:06Z |
| 273844763 | 1.0.1.0 | 2026-01-02T16:40:50Z |
| 273320189 | 1.0.0.0 | 2025-12-30T02:32:21Z |

The chosen release is frozen with signed annotated tag/object/commit, GitHub
verification, release identity and both GNU archive/checksum asset identities.
Metadata, API digests, exact single checksum filename/digest, archive hash and
safe one-file extraction must agree before execution. Official HTTPS redirects
are validated before following. Rechecks occur before download, after precheck,
just before stopping the old service, and before commit. A newer stable before
stop aborts; after stop the frozen transaction completes or rolls back.

The root-only schema-1 receipt is
`/var/lib/telemt-web-manager/telemt-release.json`: installed version, repository,
architecture, provenance identities/digests, binary hash/size, manager version,
transaction/generation IDs and timestamps. Generation metadata also binds the
receipt hash and root-owned DATA marker. All controls are regular non-symlink,
single-link root:root 0600 files below root-only 0700 state. A pristine v0.1.4
3.5.12 deployment may migrate under the exclusive lock after embedded binary
hash, running image and managed health are proven. Its reviewed-baseline receipt
honestly leaves unavailable release/tag verification fields null. A non-baseline
missing receipt, partial state or custom binary is never adopted.

Private candidate execution, including version/healthcheck, uses a root-controlled
chroot, mount/network/PID namespaces, real Telemt UID/private group, only
CAP_NET_ADMIN and cleared environment. Trusted Ubuntu helpers/libraries are copied;
`ldd` never examines a candidate. Live DATA, certificates, host root/backups and
systemd sockets are inaccessible. A transient cgroup limits memory to 1 GiB,
tasks to 4096, CPU to two cores and lifetime to 180 seconds; disk writes are
limited to 4 MiB/s on the backing device and the actual cgroup limits are checked.
Output and command deadlines are bounded.
Read-only compatibility checks use separately marked private scratch. Normal
completion reaps it; an exclusive recovery cleans only schema-validated scratch
whose supervisor is dead, after stopping its derived private cgroup. Live or
unmarked/unknown scratch refuses automatic cleanup and needs manual review.
Missing isolation tooling refuses. Precheck uses synthetic DATA and exact TOML,
including an unknown-key negative. Stopped-state rehearsal uses a separate clone,
two runtime/shutdown/restart cycles and semantic readback of actual stopped DATA.
Production never seeds synthetic quota: missing/empty old users impose no quota
preservation claim. An existing web-user must retain its reset timestamp and
nondecreasing used_bytes; top-level reset time is derived and may be canonicalized. Only a pristine third clone can become the live candidate generation.

The old service must stop gracefully, with no remaining UID process/cgroup/private
listener or Telemt-owned firewall state. The authoritative complete DATA inventory
is then sealed. Fd/O_NOFOLLOW streaming copies use 1 MiB buffers and preserve bytes,
UID/GID, modes and nanosecond mtime. Bounds are 8 GiB logical data, 100,000 entries,
depth 32 and 16 MiB total path strings. Symlinks/hardlinks, mounts/bind mounts,
special files, setid/sticky/writeable metadata, unexpected owners, xattrs/ACLs/
capabilities and source races refuse. Logical block/inode budgets and a 512 MiB
reserve are checked before downtime and authoritatively after stop; an existing
LKG is never deleted to make space. Private probe/evidence storage additionally
reserves 1 GiB for bounded candidate writes; demands are combined on a shared filesystem.

Fixed private storage is `/var/lib/.telemt-web-manager-update/TRANSACTION/` on the
same DATA filesystem and `/root/telemt-backups/update-TRANSACTION/` for evidence,
both root-only. The old complete DATA is renamed into protected storage; binary,
receipt and sealed inventory are retained. File and parent-directory fsync precede
success markers. A partial clone/index is never an activation rollback point.

Schema-1 `STATE/update-journal.json` durably records intent before mutation and
verified result afterward. Phases are STAGING, PREPARED, OLD_STOPPED,
SNAPSHOT_COMPLETE, CANDIDATE_ACTIVATED, CANDIDATE_RUNNING, COMMITTING, COMMITTED,
ROLLING_BACK, ROLLBACK_COMPLETE and CRITICAL. Paths derive only from fixed layout
and validated transaction IDs, never remote JSON paths. Known mixed old/new
publication gaps can recover; unknown binaries/receipts/generations fail closed.

The exact drop-in `telemt.service.d/50-telemt-web-manager-update.conf` requires and
orders the root `telemt-web-manager-recovery.service` before Telemt, disables forced
kill during a graceful stop, and invokes a read-only root ExecCondition. It allows
only a terminal authoritative generation or a short-lived supervised `/run` permit
binding transaction/generation/binary, boot ID, supervisor PID/starttime and phase.
The recovery service uses Type=notify: restoration precedes READY=1, then supervised
old startup and full health precede ROLLBACK_COMPLETE. It shares the manager lock,
but a live transaction dependency never waits on its own lock-holding supervisor.

Nonterminal recovery restores the original full old DATA, binary and receipt,
reloads systemd and proves old process, WEB, path and current-invocation journal
health with a 15-second dwell. Repeated recovery is idempotent, including a crash
after the restarted old process legitimately writes data. COMMITTED is authoritative
and boots the new generation. Catchable INT/TERM/HUP perform rollback; SIGKILL or
power loss is recovered on the next boot/locked mutation. A killed manager can
leave an already-started candidate serving in the same boot until recovery runs.
Failed or ambiguous recovery enters CRITICAL, stops Telemt, closes the gate and
retains evidence. Do not delete the journal/gate or mix binary/data manually;
review the complete receipt, sealed index and backups before root-led recovery.
Disk/fsync failure and external root modifications cannot guarantee recovery.

Activation proves exact process image hash, PID/starttime/invocation, UID/GID,
CAP_NET_ADMIN, cgroup/OOM/NRestarts, PID-owned listener, Nginx/local/public TLS/HTTP,
optional SOCKS, authenticated WEB session and current journal. Acceptance samples
0/5/15/30/60/90/120/150 seconds after readiness; a graceful stop/restart and another
45 seconds follow. A full WEB probe runs after each readiness, with one lightweight
probe at each interval end. Timed samples retain identity/cgroup/listener/path,
current journal and deployment contracts without opening a new WEB session each
time. Persistent DATA/quota is validated while stopped before restart.
Exact byte invariants cover manager-owned TOML, link, base unit, manifest, renewal
hook, certificate ownership record, WEB/ACME vhosts and managed stream fragments.
Certbot may rotate its valid owned lineage: current paths, private-key permissions,
domain/key pairing and renewal ownership are checked, not historical PEM/renewal
bytes. Foreign firewall and unrelated Nginx changes are never restored or flushed;
Telemt-owned firewall cleanup and objective topology/TLS checks remain required.
WARN stays diagnostic; ERROR/FATAL/panic,
malformed log transport or any objective failure blocks commit.

After durable commit, one full old LKG is root-normalized with original restore
metadata retained in the sealed index. The preceding LKG is validated and retired
only afterward, with a durable resumable retirement marker. Historical audit/binary
backups remain. Post-commit cleanup failure reports accepted Update plus an explicit
cleanup warning, never rolls back the accepted generation; it must be resolved
before another mutation. No menu action restores historical LKG.

The final double latest-release inventory check runs before stopping old Telemt.
Later revalidation checks only the frozen release/tag/assets; a newly published
unrelated release cannot change an activated transaction. After graceful stop,
every supported DATA file and directory is fsynced through no-follow descriptors
and rechecked before the rollback generation is sealed. Recovery unit publication
precedes the drop-in that activates its dependency. A valid terminal authoritative
generation may boot while housekeeping is pending; cleanup errors stay visible
and block subsequent mutation/bootstrap until resolved.

Fresh Install writes the unchanged 3.5.12 baseline receipt/generation/gate before
first start. Repair remains conservative. Uninstall removes the exact live update
controls, DATA marker, drop-in and recovery unit, while root-owned retained backups/
LKG and existing certificate policy remain. Account ownership scans stay strict.
The bootstrap parses deployed recovery schemas and candidate declarations as
data, without executing either candidate file. Pending/critical/corrupt state,
unsupported schemas, changed gate contracts and unsafe legacy downgrade refuse
before atomic manager-pair replacement, including explicit downgrade requests.

## Check and repair

`--check` leaves managed configuration/services unchanged. It reports versions,
systemd state, SubState/NRestarts, identity/capabilities, listener, Nginx/HTTP/TLS,
expiry, SOCKS and classifications from the last five minutes of logs. Raw journal
lines are not printed. Root is required; private temporary diagnostics are deleted.
Version reporting is local: manager, receipted installed Telemt and Install baseline
3.5.12. A valid receipted newer version can pass objective health without baseline
equality; no GitHub query is made. A pristine legacy 3.5.12 can report receipt
migration pending, without mutating it during Check. Pending/CRITICAL Update refuses
read-only Check/Show; a locked mutation performs recovery first. WARN records only
contribute a diagnostic count. ERROR/FATAL and genuine
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
cleanup even in tracked mode. Telemt 3.5.12 requires `conntrack` on its PATH;
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
sudo python3 tests/web_link_fixture.py # Root-owned private link, real PTY; mocked Install lifecycle
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
stream/PROXY/TLS and canonical X-Forwarded-For. Fixtures do not replace live acceptance.
Successful 0.1.2 acceptance on Ubuntu 26.04.1 LTS x86_64 is recorded in the
[primary README](../README.md#проверено-на-vps) and [English README](../README.en.md#vps-validation);
it does not establish arm64 or all Telegram client/topology combinations.
That history covers Telemt 3.5.11. Separate owner-run live acceptance of the exact
PR #6 manager 0.1.3 files completed on Ubuntu 26.04.1 LTS x86_64: normal
`telemt-web-manager --update` upgraded managed 3.5.11 to 3.5.12 with exit code 0.
TOML and WEB link were byte-identical; unit, manifest, managed Nginx, Certbot renewal
config and certificate serial/fingerprint/public key were unchanged. The service
remained active/running with `NRestarts=0`, effective CAP_NET_ADMIN and a PID-owned
listener. Local/public Nginx/TLS/HTTP checks and final `--check` passed; the same
WEB link worked from a real Telegram client. Current-invocation logs reported
`errors=0, warnings=1`: the single known `config reload: censorship settings changed; restart required` WARN accompanied `Check result: OK`, not a new regression or
release blocker. This pin update alone does not require a reboot. No Reinstall
operation is introduced; this acceptance does not establish all deployment combinations.

The reviewed xPROMSx/3x-ui-auto-nginx Fresh Install script is downloaded at commit
`59ff07f3bfeaf4b33bc5d803dfe9a3334ab8c1fd` (blob
`c19f7c2116adf41dcc7509fd47ecf2c64f5c1c81`); Nginx heredocs are rendered with
inert values. The installer is never executed. Supported order is 3x-ui Fresh
Install → manager Install. A deliberate destructive 3x-ui full rebuild requires
Telemt installation/integration again; patcher reruns are not a mandatory contract.
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

Manager 0.1.2 provides [transactional managed uninstall](#managed-uninstall):
`--uninstall --confirm-uninstall` preserves the certificate by default.
Manual recovery remains necessary for unsafe/ambiguous ownership or incomplete
rollback; automatic adoption/removal of an unmanaged deployment is refused.
After reviewing ownership and dependencies, manual removal requires stopping
and disabling Telemt, removing only its proven owned files and exact SNI
entry/`twm_frontend`, and validating/reloading Nginx. Preserve unrelated routes,
certs, x-ui DB, firewall and backups. Remove the `telemt` account only after
confirming nothing else uses it.
If the certificate is still needed, retain persistent ACME vhost/webroot/hook or
first move renewal to another strategy. Removing them can break renewal.
Certificate deletion requires the explicit managed-uninstall option
`--delete-certificate`; never delete Certbot objects blindly.

Failed fresh installs remove only transaction-owned Telemt directories/accounts
after service, identity and mount checks. Committed certificates and ACME renewal
state remain. Unsafe or incomplete rollback emits CRITICAL and retains the private
ownership journal/backups; inspect them before manual recovery or retry.

## Live acceptance fixes: MIME data and release compatibility

A normal Ubuntu nginx.conf includes mime.types. Earlier real-Nginx tests used a
synthetic main config without this include: upstream heredocs were covered but
package-owned configuration was omitted. CI now copies the installed package's
actual mime.types bytes into each isolated trusted Nginx tree, parses both plans,
asserts its snapshot hash, then runs real Nginx with it, including the pinned
xPROMSx/3x-ui-auto-nginx Fresh Install topology. No production config or include trust expansion is needed.

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
`staging.sh` now verifies the official pinned 3.5.12 digest and runs the actual
binary through fresh orchestration in direct and SOCKS modes. It proves the old
absent-directory state and a missing index fail, usable staging succeeds, strict
unknown keys fail, final paths never contain staging, config semantics match,
and incompatible/missing-decoy candidates never reach even the mocked Certbot
boundary. OS/account/systemd/ACME actions remain fixtures; this is not live issuance.

Universal Update validates the installed receipt/runtime and the newest stable
official candidate, with full old-generation rollback. Config, base unit, certificate
and Nginx are not migrated. Compatibility is tested, never inferred from a future
version number. The separate Install-baseline runtime smoke
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
The manager's release channel is independent from the fixed Telemt 3.5.12 Install
baseline and Universal Update's compatibility-driven official release discovery.

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

Keep the installation root-owned and unwritable by others. Menu actions may offer
missing tool packages after confirmation; CLI users install them manually without
replacing the working Nginx stack. Manual development tooling example:

```bash
apt-get update
apt-get install git shellcheck bash python3 curl ca-certificates tar openssl jq \
  dnsutils util-linux iproute2 coreutils libc-bin passwd findutils mawk grep sed diffutils \
  certbot iptables nftables conntrack
```

On a clean package Nginx, stream usually needs `libnginx-mod-stream`; match modules
to the installed Nginx and verify `nginx -t`. The manager checks dependencies.
Bootstrap options: `--version v0.1.1` selects a published release; `--no-start`
suppresses the menu. See [manager bootstrap](#manager-bootstrap).

## Missing Ubuntu tools (0.1.4)

After selecting a menu action, missing tool commands and their fixed Ubuntu
packages are listed together. One `Install missing packages now? [y/N]` prompt
allows only Y/y. With that confirmation, apt-get updates metadata and installs only
the listed, deduplicated requested packages with `--no-install-recommends` and
`DEBIAN_FRONTEND=noninteractive`; normal required package dependencies remain apt's
responsibility. Executables are rechecked, including Python tomllib and conntrack
on systemd's default PATH, before the selected action continues in the same process.
No apt operation occurs when tools are present or confirmation is declined.
Update/install failure or unresolved commands prevents the manager action.

Explicit CLI actions never offer/install packages, even on a TTY. Missing tools
produce a manual command, for example:

```bash
apt-get update && apt-get install -y --no-install-recommends conntrack
```

Root, Bash 5+, active systemd, supported Ubuntu 24.04/26.04 and x86_64/aarch64 must
be proven before an apt offer. Existing systemctl/systemd-path/journalctl and
existing Nginx/topology are environment requirements, not auto-install targets.
No Nginx, init system, Xray/SOCKS/WARP, repositories or firewall are provisioned.
Show current WEB link checks only python3, flock and stat; with those present it
retains its no-service/no-certificate-health path. If one is missing, any package
offer additionally requires the immutable platform validation.

| Commands | Fixed Ubuntu package |
| --- | --- |
| curl / tar / openssl / jq / python3 / certbot | corresponding same-name package |
| dig | dnsutils |
| flock, unshare, setpriv, mount | util-linux |
| ss, ip | iproute2 |
| iptables, ip6tables, iptables-save, ip6tables-save | iptables |
| nft / conntrack | nftables / conntrack |
| getent, ldd (trusted Ubuntu helpers only, never a candidate) | libc-bin |
| useradd, userdel, groupadd, groupdel | passwd |
| find | findutils |
| awk / grep / sed / cmp | mawk / grep / sed / diffutils |
| cat, chmod, chown, chroot, cp, cut, date, dirname, id, install, mktemp, mv, readlink, rm, rmdir, sha256sum, sleep, stat, timeout, tr, uname, wc | coreutils |

Install/Update/Check/Repair retain the shared tool prerequisites; Uninstall also
checks groupadd, find and IPv4/IPv6 save commands before mutation. Archive tar is
retained from the prior declared prerequisites; safe extraction itself is Python.
Git and ShellCheck in the manual development example are not manager auto-install
targets. Package names never come from user input or external release data.

Owner acceptance of v0.1.4 completed on clean Ubuntu 26.04.1 LTS: missing tool
installation through the manager, fresh Install, Show current WEB link, real
Telegram client use and final Check OK. That historical acceptance does not cover
Universal Update 0.2.0. Its separate owner acceptance is now complete: baseline 3.5.12,
real automatic Update to 3.5.14, Telegram WEB, 150s + 45s acceptance, controlled restart,
COMMITTED metadata and final Check OK. Separate 1.0.0 cover/UI acceptance is also
complete; the exact candidate and results are recorded below.

## Current WEB link (manager 0.1.4)

```text
1. Install
2. Update
3. Check
4. Repair
5. Show current WEB link
6. Change cover site
7. Uninstall Telemt
8. Exit
```

Item 5 uses a shared manager lock and reads the existing private
`/var/lib/telemt-web-manager/web-link.txt` (root, 0600). It validates safe paths,
root ownership/modes, the schema-1 manifest and the exact single-line URL against
the managed TOML domain and web-user secret. It does not require service or
certificate health, mutate state, regenerate a secret or repair a missing link.
Unsafe/missing/mismatched state fails without printing credentials.

The link is a bearer secret; store it privately. Both input and output must be
interactive terminals. The same presentation follows a committed fresh Install
selected from the menu, never a CLI `--install` or failed/rolled-back Install.
Redirected/unattended Install reports the saved path only. Colors require stdout
TTY and are disabled by nonempty `NO_COLOR` or `TERM=dumb`. No public CLI prints
the secret. Config, journals and backups also require secret-safe handling.

## Managed uninstall

Managed uninstall was introduced in 0.1.2 as `--uninstall --confirm-uninstall`.
In the 1.0.0 menu, Uninstall is item 7 and Exit is item 8.
The interactive confirmation is the exact word `UNINSTALL`;
only then is certificate deletion offered with default N. `--delete-certificate`
requires both uninstall and explicit confirmation. This removes Telemt, not the
manager, and does not adopt or replace manual/unmanaged installations.

Ownership validation is separate from the normal installation health loader.
The complete schema-1 manifest, exact generated base unit with only the approved
manager update gate/drop-in where installed, exact WEB
vhost/map/upstream, managed configuration/link, safe exclusive roots and exact
private UID/GID are required. Unknown schema, links/hardlinks, mounted managed
roots, changed entries, shared account ownership or supplementary groups refuse
before destructive mutation. A stopped/failed Telemt service or near-expiry
certificate is removable; certificate identity/key/renewal ownership and a valid,
recognized active Nginx remain required. No arbitrary firewall rule deletion is
performed. Residual Telemt-named firewall state after stop causes rollback and
manual review.

The exclusive manager lock covers the transaction. Before stop, the canonical
root-only backup durably records binary/TOML/unit/manifest/link, static DATA
anchors (including `public/index.html`), root identities, Nginx sources/edit plan,
account UID/GID, certificate ownership and prior enabled/active state. It does not
enumerate or hash mutable DATA descendants while Telemt is running. The account
ownership scan inspects external paths without traversing managed runtime roots.
The service is then stopped and disabled; inactive/failed service state, absence
of managed UID processes, listener and Telemt firewall state must be proven.
Only then does `objects-stopped` capture and durably back up the complete current
deployment, including final shutdown writes, before any Nginx/files/account removal.
Nginx source hashes/include set
are rechecked, exact WEB integration removed atomically, tested and reloaded.
Only then are managed files removed with no-follow identity checks, systemd
reloaded, and the account/private group removed. Final absence checks cover the
binary/unit/config/data/manifest/link/account, private 18080/7444 listeners, WEB
integration and Telemt-owned firewall names. Manager program/launcher and backups
are retained.

DATA is the validated `/var/lib/telemt` mutable boundary. Unknown ordinary files
and directories anywhere beneath it are accepted without name/count allowlists;
manager-generated static anchors remain strict. The stopped walk rejects links,
hardlinks, sockets, FIFOs, devices, mount crossings, unsafe ownership/modes and
extended attributes. Every copied regular file is opened without following links,
fd-identity checked and hashed. The complete stopped snapshot is rechecked before
removal. Runtime outside DATA or future special object types need explicit review.

Before deployment-file removal, rollback leaves runtime bytes untouched and
restores prior service state. After removal starts, rollback restores the exact
authoritative stopped tree: membership, bytes, modes and UID/GID, including files
created/replaced/deleted before stop. Catchable INT/TERM/HUP and failures before
commit restore files as applicable, Nginx, account
identity and prior enabled state, and restart Telemt if it had been active.
Rollback never claims to make a previously broken service healthy. If an identity
was reused/changed or restoration fails, preserve the backup and perform manual
recovery; the manager reports CRITICAL. SIGKILL, power loss, disk failure and
concurrent manual root mutation remain manual-recovery boundaries. There is no
persistent “rollback last action” interface.

Certificate preservation is default. Schema-1
`/var/lib/telemt-web-manager/certificate.json` (root-owned 0600 in a 0700 directory)
contains domain, exact cert name, renewal kind and managed ACME webroot only—no
private key. New installs persist it after certificate validation; uninstall of
v0.1.1 can create it only from the proven manifest and current certificate
contracts. Keeping a webroot lineage also keeps the exact ACME marker/webroot,
ACME HTTP vhost and deploy hook. Standalone renewal retains its free-port-80
contract. Certbot timers/accounts are not removed.

Install → uninstall keeping the certificate → fresh Install of the same domain
revalidates the independent record, paths/key/hostname and supported renewal
state, then reuses the lineage. Missing, malformed or mismatched ownership is not
adopted just because the hostname matches. Fresh rollback retains validated
certificate-only state, while still removing its deployment and owned account.
Preservation avoids unnecessary ACME issuance and rate-limit consumption.

Explicit certificate deletion is a separate phase after core uninstall commits.
It validates all explicit Certbot lineage paths and the installed `delete`
interface, then uses `certbot delete --non-interactive --cert-name DOMAIN`.
No recursive Certbot directory removal is used. Only after confirmed lineage
absence can unused exact manager ACME assets and certificate ownership state be
removed. In-use/changed challenge state is refused. The exact canonical deploy
hook is removed only with the last supported manager-owned lineage. Explicit
references to its hook/webroot/lineage from another renewal or Nginx source
refuse certificate cleanup before Certbot deletion. Nginx is tested
before/after removal; a failed activation restores the previous ACME vhost.
Failure reports “Telemt uninstall succeeded. Certificate cleanup failed or
requires manual review” and retains backup evidence; Telemt is not resurrected.


## Cover sites and Update presentation (1.0.0)

Fresh Install automatically selects one of three manager-owned single-file covers.
The bounded schema-1 manifest records stable IDs, byte sizes and SHA256. HTML and
manifest are embedded in the atomically installed canonical helper; the collection
is shipped from the same exact manager commit, without runtime downloads or a
companion-repository dependency. Only local HTML/CSS is allowed. Invalid assets
fall back to the built-in Service Status / All systems operational page.

Menu item 6 offers Random new cover, Restore Service Status and Cancel. Random
avoids the current known site when another exists. Unknown/manual HTML (including
a legacy Welcome page) is not overwritten: manual review is required. Manager
ownership, TOML identity, account, safe ancestors, root ownership and 0440 mode
are verified under the exclusive mutation lock; pending Update is refused.
The publication uses a same-directory no-follow temporary file, root:telemt, 0440,
file/directory fsync and atomic replace. Failed publication verification restores
previous bytes and removes staging files. Telemt snapshots static_directory assets
at config load, so the existing verified restart/readiness/path/journal checks are
required. Failed activation restores the old cover and verifies its restart.
The operation does not change TOML, certificate, Nginx, receipt, generation or journal,
and does not create an Update transaction. Normal full-DATA Update preserves covers.

TTY Update shows five stages and elapsed stability/restart progress, without hiding
the cursor or using a background process. NO_COLOR disables ANSI colors; TERM=dumb
and non-TTY keep line-oriented diagnostics. The renderer does not change 150s + 45s
acceptance, validation samples, WEB probes, transaction order or rollback decisions.
Failure ends the progress line and retains stage/error/rollback information.
Owner live acceptance of these 1.0.0 paths completed on Ubuntu 26.04 x86_64 after
`xPROMSx/3x-ui-auto-nginx` Fresh Install, using exact manager commit
`1b23cf92b1a1a6b69b7d47b3e47ac3bd28dfcc9d`. Telemt Fresh Install 3.5.12 reused the
existing Let's Encrypt certificate; SOCKS5 upstream and real Telegram WEB passed.
The initial inline-CSS CSP failure was fixed with local `/cover.css`, preserving
strict CSP. Fake Sites, Service Status, random cover changes and TTY progress passed.

Normal Update 3.5.12 → 3.5.14 passed 150s stability + 45s restart acceptance.
TOML, index.html, cover.css and WEB-link bytes remained identical through Update.
The journal was COMMITTED (`kind=update`, `error=null`, `restored=false`,
`normalized=true`), with identical receipt/manager/DATA generation IDs. Official
3.5.14 commit: `9d5b896bb695c55e2905b82f276da84e45a0a2ec`; installed binary SHA256:
`feb1d8779de0b86c6c43d1b871020ec94b11fad9fec5612b07b278edfd2181ff`.
A subsequent random cover change changed index.html while cover.css remained
6772 bytes, SHA256 `8bf41f327d642d6f5b63e2efa368335c18729e58a389357ff56175c0f860c4d4`.
Final Check: OK, errors=0, warnings=0. Real Telegram passed after both Update and
cover change. This records owner-provided live evidence, not a new Codex VPS test.
