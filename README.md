# Telemt WEB Manager

English | [Русский](README.ru.md)

A conservative Bash manager for [Telemt WEB Proxy](https://github.com/telemt/telemt)
behind an existing Nginx SNI router. Install, update, check and repair deployments
with direct or optional SOCKS5 egress. For Ubuntu VPS hosts already sharing HTTPS
port 443 through Nginx `stream` / `ssl_preread`.

## Features

- Interactive menu and non-interactive commands.
- Recognized Nginx integration with existing routes preserved.
- Official release SHA256 verification and configuration validation.
- Health checks, bounded startup readiness and automatic transaction rollback.
- Hardened systemd service; existing TOML preserved during updates.

## Quick installation

Run in a **root shell**, initially on a disposable test VPS:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xPROMSx/telemt-web-manager/main/install.sh)
```

The installer installs the manager and opens its menu when stdin/stdout are a TTY.
It needs Bash, curl, CA certificates and Python 3.11+; it does not install packages
or change Telemt, Nginx, Certbot or Xray. Review the script first if preferred.

Both program files come from one published manager release resolved to a commit.
The highest stable SemVer is selected; if none exists, the highest prerelease is
used. Automatic manager downgrades are refused. Testing an unpublished commit
uses the advanced/manual workflow below. [Release policy and recovery](docs/OPERATIONS.md#manager-bootstrap).

## First run

Open the menu again after installation:

```bash
telemt-web-manager
```

Choose Install and supply your WEB domain, public IPv4 and optional SOCKS5 address.
DNS must contain exactly one matching A record, with no CNAME or AAAA.
Ports `127.0.0.1:7444` and `127.0.0.1:18080` must be free.
For a new certificate the menu asks for an ACME email and agreement consent.

The private Telegram link is saved in
`/var/lib/telemt-web-manager/web-link.txt` (0600). Telemt also logs links to journald.
Treat the link, config, journals and backups as secrets.

## Common examples

Replace the example domain and TEST-NET address with your own values.

Direct egress:

```bash
telemt-web-manager --install \
  --domain proxy.example.com \
  --public-ip 203.0.113.10
```

SOCKS5 egress:

```bash
telemt-web-manager --install \
  --domain proxy.example.com \
  --public-ip 203.0.113.10 \
  --socks 127.0.0.1:1080
```

For new non-interactive certificate issuance, append
`--email operator@example.com --agree-tos` after reviewing the ACME subscriber
agreement. An unrelated existing certificate is not automatically adopted.

## Update, check and repair

```bash
telemt-web-manager --update
telemt-web-manager --check
telemt-web-manager --repair
```

`--update` updates the **Telemt binary**, with validation and rollback;
it does not update the manager or rewrite TOML.
`--check` validates managed files, configuration, renewal state and service health.
`--repair` restarts/reloads only verified managed services, without reconstructing
changed files. To update the manager itself, rerun the quick installation command.
This preserves the existing Telemt deployment.

## Managed Telemt uninstall (manager 0.1.2)

```bash
telemt-web-manager --uninstall --confirm-uninstall
# Optional, explicit certificate deletion:
telemt-web-manager --uninstall --confirm-uninstall --delete-certificate
```

The menu includes **Uninstall Telemt** and requires typing `UNINSTALL`; certificate
removal is a separate `[y/N]` question. Uninstall removes only a deployment proven
manager-owned by its manifest, exact unit/Nginx/configuration contracts, paths and
private account identity. It can remove a stopped or unhealthy Telemt service.
Missing/ambiguous ownership causes refusal; arbitrary/manual Telemt is never removed.
Unmanaged replacement/adoption is outside this feature.

The manager itself stays in `/opt/telemt-web-manager` with its launcher. Private
backups in `/root/telemt-backups` are retained. Certificate preservation is the
default: the lineage, renewal config, independent root-only `certificate.json`,
and required ACME webroot/vhost/deploy hook remain. A fresh same-domain Install
validates and reuses that manager-owned certificate without a new ACME order.
Preserving a valid lineage avoids unnecessary issuance and rate-limit consumption.

Explicit deletion uses Certbot's exact-lineage deletion interface after Telemt
uninstall commits. It never removes the Certbot account or another lineage. If
certificate cleanup fails, Telemt remains uninstalled and ownership/backup evidence
is retained for manual review. [Transaction and recovery details](docs/OPERATIONS.md#managed-uninstall).

## Requirements and supported environment

Ubuntu 24.04/26.04, systemd, Bash 5+, Python 3.11+, active Nginx with SSL, HTTP/2,
realip and stream/ssl_preread modules. x86_64 or aarch64, one recognized Nginx SNI map/router,
IPv4 `:443`, optional existing `[::]:443`, outgoing PROXY protocol and an HTTP
`conf.d/*.conf` include. The manager adds a loopback TLS frontend and an IPv4-only
Telemt WEB listener. Telegram egress is direct or unauthenticated SOCKS5.
Supported Telemt: **3.5.11**. Fresh installs and updates use only this reviewed
release and embedded official SHA256 values. Older managed installs must pass
compatibility checks; newer installs are never downgraded. Supporting a future
release requires a new reviewed manager version. `--check` reports installed and
supported versions locally. WARN is diagnostic; genuine ERROR/FATAL/panic and
failed objective health checks cause failure. [CI coverage](docs/CI-COVERAGE.md).

HTTP-01 uses standalone on free port 80, or a persistent managed webroot when
port 80 belongs to the recognized Nginx redirect topology. Nginx is never stopped.
Verify external port 80/443 reachability and certificate renewal yourself.
Standalone renewal requires port 80 to remain free; `--check` fails on a conflict
and verifies the manager's deploy hook. No known Certbot timer produces a warning
to verify cron/custom scheduling manually.

## Tested 3x-ui-pro compatibility

Telemt WEB Manager is tested against the Nginx `stream` / `ssl_preread` topology
generated by [mozaroc/3x-ui-pro](https://github.com/mozaroc/3x-ui-pro) at revision
`a2c430cd6dec7c86d873dcda3544a61e7ac41144`, using both installer and patcher fixtures.
This is not an official integration. Arbitrary custom or future configurations
are not automatically supported. Xray and 3x-ui configuration/database are not modified.

CI uses the verified official Telemt binary and real Nginx traffic tests.
Systemd and Certbot lifecycle operations use mocks. Live VPS acceptance is still required.

The enabled conntrack-control contract requires the Ubuntu `conntrack` package,
iptables/ip6tables/nft and CAP_NET_ADMIN. Preflight checks `conntrack` on both
the root shell PATH and systemd's default runtime PATH before installation work;
the manager does not install missing packages.

## Advanced / manual installation

Review a trusted checkout (or the PR checkout during acceptance) and install both
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
Bootstrap options: `--version v0.1.0` selects a published release; `--no-start`
suppresses the menu. See [operations](docs/OPERATIONS.md#manager-bootstrap).

## Technical documentation

- [Upstream audit and version/configuration contracts](docs/UPSTREAM.md).
- [Architecture, security, ACME recovery, tests and operations](docs/OPERATIONS.md).

## Important limitations

- Unknown Nginx topology or incompatible/changed managed runtime contracts fail closed.
- Unrelated existing Telemt installations and certificates require manual review.
- No firewall/UFW changes, automatic TOML migrations or automatic uninstall.
- WEB AAAA, authenticated/IPv6 SOCKS and custom HTTP-80 routing require manual review.
- A certificate can survive failed issuance post-validation. Retry refuses missing
  managed renewal state; see the recovery guide. Never blindly delete Certbot assets.
- SIGINT/TERM/HUP trigger transactional rollback. Power loss, SIGKILL, disk failure
  and concurrent root edits remain manual recovery boundaries.

## License and independence

[MIT License](LICENSE). Independent project, not affiliated with, endorsed by,
or part of Telemt, 3x-ui or 3x-ui-pro.
