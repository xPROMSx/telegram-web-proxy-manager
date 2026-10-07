# ✈️ Telegram Web Proxy Manager

**Your own Telegram WEB Proxy on an Ubuntu VPS with one command.**
Get HTTPS, a ready `tg://webproxy?...` link for Telegram and an automatically selected
Fake Site on your domain. The manager checks updates and restores the working version
and its data if validation fails. Use SOCKS5 when your VPS cannot reach Telegram directly.

[![checks](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml/badge.svg)](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20%7C%2026.04-E95420?logo=ubuntu&logoColor=white)
[![Release](https://img.shields.io/github/v/release/xPROMSx/telegram-web-proxy-manager)](https://github.com/xPROMSx/telegram-web-proxy-manager/releases/latest)

[Русский](README.md) · [Releases](https://github.com/xPROMSx/telegram-web-proxy-manager/releases) · [3x-ui Auto Nginx](https://github.com/xPROMSx/3x-ui-auto-nginx) · [Issues](https://github.com/xPROMSx/telegram-web-proxy-manager/issues)

## ✨ What it does

- ✈️ Installs and configures your own Telegram WEB Proxy.
- 🔐 Sets up HTTPS with Let's Encrypt, including reuse of certificates saved by the manager.
- 🥸 Automatically serves a Fake Site on the public domain instead of a technical proxy response.
- 🎨 Lets you switch Fake Sites from the menu or restore the neutral Service Status page.
- 🔄 Finds new stable proxy engine releases and checks compatibility before installing them.
- 🛟 Restores the working version and its data if an update fails validation.
- 🔧 Checks the proxy, Nginx, HTTPS and connectivity with one command.
- 🌐 Connects directly or through SOCKS5 when the VPS cannot reach Telegram directly.

## ⚡ Quick start

Start with an Ubuntu VPS running a supported Nginx configuration.
**3x-ui Auto Nginx**, described below, can prepare it for you. Run as root:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xPROMSx/telegram-web-proxy-manager/main/install.sh)
```

Before the manual GitHub repository rename, use the same command with
`https://raw.githubusercontent.com/xPROMSx/telemt-web-manager/main/install.sh`.
Bootstrap validates the official repository and works before and after the rename.

This installs the published manager release and opens its menu.
Use `telegram-web-proxy-manager` to open it again;
the previous `telemt-web-manager` command remains available.
Choose **1. Install**. The manager asks for your domain, public IPv4 and whether to use SOCKS5.
If the domain does not have a certificate yet, the manager also asks for an email address and confirmation of the Let's Encrypt terms.

After installation, the manager gives you a ready `tg://webproxy?...` link that
can be added directly to Telegram. Your domain also serves an automatically
selected Fake Site, which you can change from the menu.

## 🖥️ Need a ready-to-use 3x-ui and Xray server?

Our other project, [**3x-ui Auto Nginx**](https://github.com/xPROMSx/3x-ui-auto-nginx),
sets up **3x-ui, Xray, Nginx and HTTPS**. Telegram Web Proxy Manager then adds
a Telegram WEB Proxy to the same server through a separate installation.

**Recommended order:**

1. 3x-ui Auto Nginx.
2. Telegram Web Proxy Manager.

The projects work independently: neither installer runs the other.
A full 3x-ui reinstall requires Telegram proxy integration again; see the documentation below.

## Manager 1.1.0 menu

```text
1. Install
2. Update
3. Check
4. Repair
5. Show current WEB link
6. Change cover site
7. Uninstall Telegram proxy
8. Exit
```

**The connection link contains a secret key for accessing your proxy.** Do not
publish it or share it with anyone who should not have access. Item 5 displays the validated saved link
without generating a new one or changing settings. Storage:
`/var/lib/telemt-web-manager/web-link.txt` (root, mode `0600`). Menu-based Install
shows it after successful completion; unattended commands and redirected output do not print it.

**Change cover site** chooses a different random Fake Site or restores Service Status.
Pages are local, without external CDNs or resources, and survive Telemt updates.
Manually edited HTML is not overwritten.

**Update** checks the new stable release and shows installation progress.
If checks fail, it restores the working version.
`NO_COLOR` disables colors; `TERM=dumb` keeps the output plain.

**Uninstall Telegram proxy** requires typing `UNINSTALL` and only removes the proxy installed
by this manager. The manager and backups stay. By default, the certificate is
kept for the same domain; deletion requires separate confirmation.

## Unattended commands

```bash
telegram-web-proxy-manager --install --domain proxy.example.com --public-ip 203.0.113.10
# If needed: --socks 127.0.0.1:1080
# For a new certificate: --email operator@example.com --agree-tos
telegram-web-proxy-manager --update
telegram-web-proxy-manager --check
telegram-web-proxy-manager --repair
telegram-web-proxy-manager --uninstall --confirm-uninstall
# Explicitly delete the managed certificate too:
telegram-web-proxy-manager --uninstall --confirm-uninstall --delete-certificate
```

Unattended commands never install packages. Menu actions install missing Ubuntu
tools only after you answer `Y/y`. Update the **manager itself** by running
the quick-start command again; Telemt stays installed.
There is no automatic downgrade.

## Proxy engine

Telegram Web Proxy Manager uses [Telemt](https://github.com/telemt/telemt) as its proxy engine.
No separate Telemt installation or manual Telemt configuration is required.
Internal paths containing `telemt-web-manager` stay unchanged for compatibility
with existing installations.

## Requirements

- Ubuntu **24.04 / 26.04**, root access, Bash 5+ and a running systemd environment.
- An existing supported Nginx configuration with `stream`, `ssl_preread` and PROXY protocol.
- One correct DNS A record pointing to the server's public IPv4, with no CNAME or AAAA.
- Free local Telemt ports: `127.0.0.1:18080` and `127.0.0.1:7444`.
- x86_64 has been validated on a real server. ARM64/aarch64 has not been live-tested.

A fresh installation uses Telemt **3.5.12**. For updates, the manager selects the newest
stable official release and checks compatibility while preserving your configuration.
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
