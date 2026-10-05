# ✈️ Telemt WEB Manager

**Telegram WEB proxy on your VPS — installation, HTTPS, safe updates
with rollback and Automatic Fake Site.**

[![checks](https://github.com/xPROMSx/telemt-web-manager/actions/workflows/checks.yml/badge.svg)](https://github.com/xPROMSx/telemt-web-manager/actions/workflows/checks.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20%7C%2026.04-E95420?logo=ubuntu&logoColor=white)
[![Release](https://img.shields.io/github/v/release/xPROMSx/telemt-web-manager)](https://github.com/xPROMSx/telemt-web-manager/releases/latest)

[Русский](README.md) · [Releases](https://github.com/xPROMSx/telemt-web-manager/releases) · [3x-ui Auto Nginx](https://github.com/xPROMSx/3x-ui-auto-nginx) · [Issues](https://github.com/xPROMSx/telemt-web-manager/issues)

## ⚡ Quick start

Prepare an Ubuntu VPS with an existing supported Nginx topology — for example,
using **3x-ui Auto Nginx** Fresh Install. Then run in a root terminal:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xPROMSx/telemt-web-manager/main/install.sh)
```

Choose **1. Install**, enter your domain and public IPv4, and receive the WEB link.
A cover page is selected automatically. Bootstrap installs the published manager
release; Telemt is installed through the separate Install action.

## Features

- ⚡ One-command manager installation; missing Ubuntu tools only after Y/y confirmation.
- ✈️ [Telemt WEB Proxy](https://github.com/telemt/telemt): direct or SOCKS5 upstream.
- 🔄 Universal Update: verified stable official candidate, preserving managed TOML.
- 🛟 Automatic rollback/recovery restores the binary and complete DATA.
- 🥸 Automatic Fake Site and menu-based cover changes, with no external resources.
- 🔐 HTTPS / Let's Encrypt, including certificate preservation and reuse.
- 🌐 Integration with an existing Nginx SNI router on shared port 443.
- 🔧 Check / Repair / managed Uninstall and private current WEB-link display.

## 🚀 Want a complete proxy stack?

### [3x-ui Auto Nginx](https://github.com/xPROMSx/3x-ui-auto-nginx)

The companion project deploys **3x-ui / Xray / Nginx / TLS / Fake Site**.
Telemt WEB Manager adds a managed Telegram WEB proxy while preserving recognized
routes and settings in the existing stack.

**Recommended order: 3x-ui Fresh Install → Telemt Install.**
Neither installer invokes the other; there is no runtime dependency between repositories.
A repeated destructive `x-ui-latest.sh` rebuilds Nginx: after an intentional full rebuild,
Telemt must be installed/integrated again.

## Manager 1.0.0 menu

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

**The WEB link is a bearer secret.** Successful interactive Install displays it
only after commit. Item 5 reads the existing manager-owned link, validates its
TOML identity, and never regenerates or repairs it.
Private storage: `/var/lib/telemt-web-manager/web-link.txt` (root, 0600).
CLI Install and redirected/unattended output never print the secret. `NO_COLOR`
disables colors; `TERM=dumb` selects plain output.

**Change cover site** offers Random new cover, Restore Service Status or Cancel.
Random selects a different current site when alternatives exist. HTML is replaced
atomically; a verified restart is required because Telemt caches static assets.
Unknown/manually changed HTML requires manual review and is not overwritten.
Covers are ordinary decoy pages, with no promises of invisible traffic or DPI bypass.
Your selected cover survives Telemt Update.

**Update** shows stages and stability/restart progress in a TTY.
Acceptance remains 150 + 45 seconds. CI/redirected output retains line-oriented
diagnostics; failures and rollback information remain visible.

**Uninstall** requires typing `UNINSTALL` and removes only proven manager-owned Telemt.
The manager and backups remain. Certificates are preserved by default; same-domain
Install reuses valid manager-owned certificate state without a new ACME order.
Certificate deletion requires separate explicit confirmation.

## Unattended commands

```bash
telemt-web-manager --install --domain proxy.example.com --public-ip 203.0.113.10
# If needed: --socks 127.0.0.1:1080
# For a new certificate: --email operator@example.com --agree-tos
telemt-web-manager --update
telemt-web-manager --check
telemt-web-manager --repair
telemt-web-manager --uninstall --confirm-uninstall
# Explicitly delete the managed certificate too:
telemt-web-manager --uninstall --confirm-uninstall --delete-certificate
```

CLI actions never install packages automatically. To update the **manager**,
repeat bootstrap: it atomically installs the manager/helper from one release commit,
preserving Telemt. Automatic downgrade is refused.

## Requirements and boundaries

Supported Telemt: **3.5.12** — Fresh Install baseline. Update selects the newest
stable official release and verifies compatibility, without TOML migration or downgrade.

Ubuntu **24.04 / 26.04**, root, Bash 5+, active systemd and an existing supported
Nginx `stream` / `ssl_preread` / PROXY protocol topology are required. The domain needs
one correct A record, no CNAME/AAAA; local Telemt ports must be free.
GNU x86_64/aarch64 binaries are supported; native ARM systemd live acceptance is not claimed.
Conntrack requires `CAP_NET_ADMIN`. This is not server provisioning: the manager does
not install Nginx/Xray/3x-ui, configure the firewall or adopt foreign Telemt deployments.
Unknown topologies/unsafe paths fail closed. Keep configs, journals and backups private.

Owner acceptance history: v0.1.1 — Install/recovery; v0.1.2 — Uninstall/certificates;
v0.1.3 — Update 3.5.11 → 3.5.12; v0.1.4 — WEB-link/dependency UX. Universal Update
architecture also passed owner live acceptance, including 3.5.12 → 3.5.14,
Telegram and final Check OK. New 1.0.0 cover/UI features require separate acceptance
before publication. CI does not establish support for every server/configuration.

## Documentation

[Operations / requirements / recovery](docs/OPERATIONS.md) ·
[Update, rollback and security model](docs/OPERATIONS.md#universal-update-020) ·
[CI coverage and limitations](docs/CI-COVERAGE.md) ·
[Upstream provenance](docs/UPSTREAM.md) · [MIT License](LICENSE)
