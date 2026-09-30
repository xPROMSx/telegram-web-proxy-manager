# Telemt WEB Manager

English | [Русский](README.ru.md)

A safety-oriented Bash manager for installing, updating, validating and repairing
[Telemt](https://github.com/telemt/telemt) WEB Proxy deployments behind Nginx.

Designed for VPS environments where port 443 may already be shared between
multiple services through Nginx `stream` / `ssl_preread` SNI routing.
An independent open-source project under MIT.

Manager version: `0.1.0`. Audited upstream: **3.5.9**.
Sources and decisions: [docs/UPSTREAM.md](docs/UPSTREAM.md).

## Highlights

- Interactive install, update, check and repair modes
- Telemt WEB Proxy behind Nginx HTTPS
- Optional SOCKS5 upstream routing
- Safe integration with recognized existing SNI routing
- Release integrity verification
- Candidate configuration validation before update
- Automatic rollback after failed updates
- Bounded readiness checks instead of fixed startup delays
- Conservative fail-closed behavior
- systemd hardening with minimal required capabilities
- Automated regression tests and GitHub Actions

## Tested compatibility

Tests cover complete sanitized configurations emitted by `x-ui-latest.sh` and
`x-ui-patch.sh` from [`mozaroc/3x-ui-pro`](https://github.com/mozaroc/3x-ui-pro),
revision `a2c430cd6dec7c86d873dcda3544a61e7ac41144`. The manager recognizes this
Nginx `stream` / `ssl_preread` topology and adds Telemt without changing existing
Xray or 3x-ui routing. CI uses real Nginx; installation, Certbot and systemd are
mocked. Live VPS acceptance has not been performed. Compatibility is limited to
the documented topology/revision, not arbitrary custom or future configurations.

> Telemt WEB Manager is an independent project and is not affiliated with,
> endorsed by, or part of Telemt, 3x-ui, or 3x-ui-pro.

## What it does not do

- Rewrite unknown Nginx topologies
- Modify the 3x-ui database or Xray routing
- Change firewall/UFW rules
- Guess configuration migrations
- Automatically adopt arbitrary existing Telemt installations
- Suppress validation failures to complete installation

## Supported scope

- Ubuntu 24.04 / 26.04, Bash 5+, systemd; x86_64 and aarch64 (arm64).
- Nginx with HTTP SSL, HTTP/2, realip, stream and ssl_preread modules.
- One recognized SNI router on IPv4 `:443`, optionally with an existing `[::]:443`,
  and outgoing `proxy_protocol on` already enabled. Both reviewed 3x-ui-pro
  scripts are tested at the documented revision.
- Dedicated TLS frontend `127.0.0.1:7444`; Telemt `127.0.0.1:18080`.
- Python 3.11+ standard library for strict TOML/Nginx parsing, diagnostics,
  bounded archive extraction and path checks. No external Python packages.
  Bash handles orchestration and transactions.

```text
Telegram WEB -> HTTPS :443 -> Nginx stream/SNI
             -> PROXY + TLS 127.0.0.1:7444
             -> HTTP/1.1 127.0.0.1:18080 -> Telemt
             -> direct or SOCKS5 -> Telegram DC
```

Unknown topology, changed managed vhosts, service drop-ins, TOML includes and
ambiguous addresses cause refusal. Do not weaken checks or rewrite configuration
to bypass a refusal.

## Obtaining and installing the manager

Use a root shell on a test VPS. The manager never invokes `sudo`.
Do not execute remote code through `curl | bash`.

```bash
git clone https://github.com/xPROMSx/telemt-web-manager.git
cd telemt-web-manager
# Before merge, the implementation is in work/initial-telemt-manager.
git switch work/initial-telemt-manager
git log --oneline -5
less telemt-web-manager.sh
less lib/safety.py
bash -n telemt-web-manager.sh
shellcheck telemt-web-manager.sh
sha256sum telemt-web-manager.sh lib/safety.py
# Compare published checksums for the chosen release, if available.
# A local hash records bytes; it does not authenticate the publisher.
install -d -m 0755 /opt/telemt-web-manager/lib
install -m 0755 telemt-web-manager.sh /opt/telemt-web-manager/
install -m 0644 lib/safety.py /opt/telemt-web-manager/lib/
/opt/telemt-web-manager/telemt-web-manager.sh --help
```

Copy both `.sh` and adjacent `lib/safety.py`. The installed directory must be
root-owned and not writable by others. The original MIT LICENSE is unchanged.
Install dependencies yourself without blindly replacing working Nginx:

```bash
apt-get update
apt-get install bash python3 curl ca-certificates tar openssl jq dnsutils \
  util-linux iproute2 coreutils passwd certbot iptables nftables
```

Stream is usually supplied by `libnginx-mod-stream` on clean Nginx installations.
Match modules to the installed package and run `nginx -t`.
The manager checks dependencies; it does not run `apt`.

## Fresh install

Point DNS A to the server IPv4. Exactly one matching A is required; real AAAA is
queried separately through DNS. CNAME, multiple A, AAAA and mapped IPv4 AAAA
require manual review. `getent` is not used for AAAA detection.
The TEST-NET address and example hostname below are placeholders:

```bash
/opt/telemt-web-manager/telemt-web-manager.sh --install \
  --domain proxy.example.com --public-ip 203.0.113.10
```

Without arguments: Install / Update / Check / Repair / Exit menu. Interactive
installation asks for domain, public IPv4 and optional SOCKS. Without a TTY,
missing parameters cause refusal instead of waiting for input.

Sequence: DNS/ports/Nginx checks, plan, latest stable, download and official SHA256,
certificate, backup, `telemt` account, private config, candidate healthcheck,
systemd, bounded readiness, Nginx validation/reload, local decoy, complete local
SNI/TLS path, public HTTPS and recent logs.

| Path | Purpose |
| --- | --- |
| `/usr/local/bin/telemt` | Verified upstream binary |
| `/etc/telemt/telemt.toml` | root:telemt, 0640; API disabled |
| `/etc/systemd/system/telemt.service` | Hardened unit |
| `/var/lib/telemt/public/index.html` | Root-owned static decoy, 0440 |
| `/var/lib/telemt/state/` | Service's only writable state directory |
| `/var/lib/telemt-web-manager/manifest.json` | Root-only managed installation metadata |
| `/var/lib/telemt-web-manager/web-link.txt` | `tg://webproxy` link, 0600 |
| `/etc/nginx/conf.d/telemt-web-manager.conf` | Dedicated TLS frontend |
| `/etc/nginx/conf.d/telemt-web-manager-acme.conf` | Persistent HTTP-01 vhost, webroot flow only |
| `/var/lib/telemt-web-manager-acme/` | Root-owned ACME webroot and ownership marker, webroot flow only |
| `/etc/letsencrypt/renewal-hooks/deploy/telemt-web-manager` | Nginx validation/reload after renewal |

`openssl rand -hex 16` generates the secret. The manager saves a private link file
without printing the secret. Upstream link logging in journald remains enabled.
Never publish the link file, config, complete journals or backups.

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

Existing certs are found in `/etc/letsencrypt/live/DOMAIN/`. Validation covers
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
existing vhosts are untouched. Successful issuance commits the persistent
vhost/webroot separately for renewal, even if later Telemt installation fails.
Empty webroot directories may remain after failure; inspect backup/marker before retrying.

Check external reachability of 80/443 yourself; firewall rules remain unchanged.
No new cron/timer is created. Missing known Certbot timers trigger a warning to
inspect existing scheduling. The deploy hook runs `nginx -t`, then reload.
If a standalone certificate's port 80 later becomes occupied, change renewal
strategy manually. After either flow run `certbot renew --dry-run` on a test VPS.
CI does not perform real ACME issuance.

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
Validation failure stops the update. Runtime/write-path auditing covers only 3.5.9:
newer latest releases require source audit and an updated version gate even if
their candidate might accept TOML. Older manager configs with quota outside
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

Fresh TOML sets `general.config_strict = true`, `data_path = /var/lib/telemt`.
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
bash tests/upstream.sh   # Internet: official release asset and SHA256
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
