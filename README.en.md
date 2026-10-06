# ✈️ Telemt WEB Manager

**An easy way to install and maintain a Telegram WEB Proxy on your Ubuntu VPS.**
The manager sets up Telemt, HTTPS and a Fake Site for your domain, gives you a
Telegram connection link, and restores the working version if an update fails its checks.

[![checks](https://github.com/xPROMSx/telemt-web-manager/actions/workflows/checks.yml/badge.svg)](https://github.com/xPROMSx/telemt-web-manager/actions/workflows/checks.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20%7C%2026.04-E95420?logo=ubuntu&logoColor=white)
[![Release](https://img.shields.io/github/v/release/xPROMSx/telemt-web-manager)](https://github.com/xPROMSx/telemt-web-manager/releases/latest)

[Русский](README.md) · [Releases](https://github.com/xPROMSx/telemt-web-manager/releases) · [3x-ui Auto Nginx](https://github.com/xPROMSx/3x-ui-auto-nginx) · [Issues](https://github.com/xPROMSx/telemt-web-manager/issues)

## ✨ What it does

- ✈️ Installs and configures [Telemt WEB Proxy](https://github.com/telemt/telemt).
- 🔐 Sets up HTTPS with Let's Encrypt, including reuse of certificates saved by the manager.
- 🥸 Automatically serves a Fake Site on the public domain instead of a technical proxy response.
- 🎨 Lets you switch Fake Sites from the menu or restore the neutral Service Status page.
- 🔄 Finds new stable Telemt releases and checks compatibility before installing them.
- 🛟 Restores the working version and its data if an update fails validation.
- 🔧 Checks Telemt, Nginx, HTTPS and connectivity with one command.
- 🌐 Connects directly or through SOCKS5 when the VPS cannot reach Telegram directly.

## ⚡ Quick start

Start with an Ubuntu VPS running a supported Nginx configuration.
**3x-ui Auto Nginx**, described below, can prepare it for you. Run as root:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xPROMSx/telemt-web-manager/main/install.sh)
```

This installs the published manager release and opens its menu.
Choose **1. Install**. The manager asks for your domain, public IPv4 and whether to use SOCKS5.
For a new certificate, supply an email and accept Let's Encrypt's terms; see the commands below.

After installation, the manager gives you a ready `tg://webproxy?...` link that
can be added directly to Telegram. Your domain also serves an automatically
selected Fake Site, which you can change from the menu.

## 🖥️ Need a ready-to-use 3x-ui and Xray server?

Our other project, [**3x-ui Auto Nginx**](https://github.com/xPROMSx/3x-ui-auto-nginx),
sets up **3x-ui, Xray, Nginx and HTTPS**. Telemt WEB Manager then adds
a Telegram WEB Proxy to the same server through a separate installation.

**Recommended order:**

1. 3x-ui Auto Nginx.
2. Telemt WEB Manager.

The projects work independently: neither installer runs the other.
A full 3x-ui reinstall requires Telemt integration again; see the documentation below.

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

**The connection link contains a secret key for accessing your proxy.** Do not
publish it or share it with strangers. Item 5 displays the validated saved link
without generating a new one or changing settings. Storage:
`/var/lib/telemt-web-manager/web-link.txt` (root, mode `0600`). Menu-based Install
shows it after successful completion; unattended commands and redirected output do not print it.

**Change cover site** chooses a different random Fake Site or restores Service Status.
Pages are local, without external CDNs or resources, and survive Telemt updates.
Manually edited HTML is not overwritten.

**Update** checks the new stable release and shows installation progress.
If checks fail, it restores the working version.
`NO_COLOR` disables colors; `TERM=dumb` keeps the output plain.

**Uninstall Telemt** requires typing `UNINSTALL` and only removes Telemt installed
by this manager. The manager and backups stay. By default, the certificate is
kept for the same domain; deletion requires separate confirmation.

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

Unattended commands never install packages. Menu actions install missing Ubuntu
tools only after you answer `Y/y`. Update the **manager itself** by running
the quick-start command again; Telemt stays installed.
There is no automatic downgrade.

## Requirements

- Ubuntu **24.04 / 26.04**, root access, Bash 5+ and a running systemd environment.
- An existing supported Nginx configuration with `stream`, `ssl_preread` and PROXY protocol.
- One correct DNS A record pointing to the server's public IPv4, with no CNAME or AAAA.
- Free local Telemt ports: `127.0.0.1:18080` and `127.0.0.1:7444`.
- GNU builds for x86_64 and aarch64; native ARM servers under systemd have not been live-tested.

Supported Telemt: **3.5.12** — the version used for a fresh installation. Update selects
the newest stable official release and checks compatibility while preserving your configuration.
The manager does not install Nginx/Xray/3x-ui, configure the firewall automatically
or manage manually installed Telemt. See the documentation for detailed requirements.

## Tested on a real server

Version 1.0.0 was tested on an Ubuntu 26.04 x86_64 VPS after 3x-ui Auto Nginx setup:
fresh installation, HTTPS, SOCKS5, Telegram, Fake Sites, page switching and the
Telemt **3.5.12 → 3.5.14** update all passed. Final check: **OK**.

## Documentation

[Operations, requirements and recovery](docs/OPERATIONS.md) ·
[Safe updates and restoring the working version](docs/OPERATIONS.md#universal-update-020) ·
[Test coverage and limitations](docs/CI-COVERAGE.md) ·
[Telemt sources and release verification](docs/UPSTREAM.md) · [MIT License](LICENSE)
