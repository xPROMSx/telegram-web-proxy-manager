# Operations, security and recovery

[English front page](../README.md) | [Русская главная](../README.ru.md) | [Upstream audit](UPSTREAM.md)

This document contains the detailed deployment and trust-boundary material.
Start with the README installation commands. Examples use TEST-NET and example.com.

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
Validation failure stops the update. There is no major/minor/exact-version allowlist.
SemVer comparison refuses downgrades, including a release reclassified as prerelease.
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

## Check and repair

`--check` leaves managed configuration/services unchanged. It reports versions,
systemd state, SubState/NRestarts, identity/capabilities, listener, Nginx/HTTP/TLS,
expiry, SOCKS and classifications from the last five minutes of logs. Raw journal
lines are not printed. Root is required; private temporary diagnostics are deleted.
Unavailable GitHub latest yields an unknown latest version and nonzero result.

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
cleanup even in tracked mode. The known 3.5.9 missing-chain warning is classified
narrowly; other conntrack errors fail. Evidence is in upstream notes.

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
for file in telemt-web-manager.sh tests/*.sh; do bash -n "$file"; done
shellcheck -x telemt-web-manager.sh tests/*.sh
bash tests/run.sh
bash tests/fresh.sh
bash tests/download.sh   # Mock download, bad digest, symlink, redaction
bash tests/contracts.sh  # Strict config, writable paths, unit
bash tests/locks.sh      # Shared/exclusive races, unsafe lock paths
bash tests/acme.sh       # Certbot mocks, refusal, rollback, renewal/idempotence
sudo bash tests/renewal.sh # Root-owned hook, standalone sockets, scheduler visibility
bash tests/upstream.sh   # Internet: official release asset and SHA256
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

Failed fresh installs can intentionally leave accounts, empty directories and
issued certificates. Accounts/certs are never automatically removed; inspect
leftovers and backups before retrying.

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

Fresh install verifies official stable metadata, asset/digest/archive and binary
SemVer, then stages the exact intended TOML before Certbot or persistent setup.
Semantic WEB/write-path checks, positive healthcheck and unknown-key rejection
run on private copies. Hash checks reject candidate changes; the original TOML
is not passed as a writable CLI input. A temporary working directory is used
before DATA exists; if a candidate requires unavailable paths, it is refused
before issuance. The same staged TOML is copied unchanged into the installation
and revalidated there, followed by systemd foreground startup, bounded readiness,
owned listener, UID/capabilities, HTTP/TLS/SOCKS and journal checks.

Updates validate the installed runtime/configuration, compare SemVer, refuse an
older stable, preserve equal-version behavior, validate the newer candidate on
current TOML copies, back up and atomically activate it. Startup/path/log/hash
failures restore the previous binary. Config, unit, certificate and Nginx are
not migrated. SemVer includes prerelease precedence and ignores build metadata
for ordering. Normal selection rejects draft/prerelease metadata and SemVer
prerelease tags. Pinned prerelease binaries may still be tested explicitly in CI.

These checks evaluate future stable releases; they do not guarantee every future
implementation's compatibility. Unknown schema/CLI or runtime behavior can fail
contracts. The source audit remains evidence for the historical baseline, while
systemd read-only paths and single-listener ownership enforce runtime boundaries.
The exact 3.5.9 missing-chain warning exception is diagnostic evidence, not a
release eligibility gate; it is deliberately not generalized to unknown versions.
