# Telegram Web Proxy Manager

**Your own Telegram proxy on an Ubuntu VPS, without manual proxy configuration.**

The manager installs and configures your proxy, sets up HTTPS and adds a cover
site to your domain. If an update fails its checks, the previous working version
is restored automatically.
Use SOCKS5 when your VPS cannot reach Telegram directly.

[![checks](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml/badge.svg)](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20%7C%2026.04-E95420?logo=ubuntu&logoColor=white)
[![Release](https://img.shields.io/github/v/release/xPROMSx/telegram-web-proxy-manager)](https://github.com/xPROMSx/telegram-web-proxy-manager/releases/latest)

[Русский](README.md) · [Releases](https://github.com/xPROMSx/telegram-web-proxy-manager/releases) · [3x-ui Auto Nginx](https://github.com/xPROMSx/3x-ui-auto-nginx) · [Issues](https://github.com/xPROMSx/telegram-web-proxy-manager/issues)

## ✨ Features

- One-command proxy setup.
- HTTPS with Let's Encrypt.
- A cover site on your domain.
- Safe updates that restore the working version if checks fail.
- Direct or SOCKS5 connectivity to Telegram.
- Proxy health and connectivity checks.

## Quick start

You need an Ubuntu VPS, a separate domain or subdomain with a DNS A record pointing
to the server (not used by 3x-ui, including REALITY, or other Nginx sites),
root access and Nginx already running a compatible configuration.
If your server is not ready yet, 3x-ui Auto Nginx can help — see below.

Run as root:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xPROMSx/telegram-web-proxy-manager/main/install.sh)
```

The installer opens a menu. Choose **Install** and follow the prompts.
Once setup is complete, you receive a ready `tg://webproxy?...` link
for adding the proxy to Telegram. Your domain also serves a cover site.
You can open the manager again at any time with `telegram-web-proxy-manager`.

**The connection link contains the key to your proxy. Do not publish it.**

## Using it with 3x-ui Auto Nginx

If you also want 3x-ui and Xray on your VPS, use our other project,
[3x-ui Auto Nginx](https://github.com/xPROMSx/3x-ui-auto-nginx).
It prepares the server and sets up Nginx and HTTPS.

Install **3x-ui Auto Nginx** first, then **Telegram Web Proxy Manager**.
The projects can run together on the same VPS and are managed independently.

## Under the hood

The proxy runs on [Telemt](https://github.com/telemt/telemt).
The manager installs, configures and updates it for you;
no separate Telemt setup or knowledge is required.

## Requirements

- Ubuntu **24.04 or 26.04**.
- Root access.
- A separate domain or subdomain with a DNS A record pointing to the VPS's public
  IPv4 address, not used by 3x-ui (including REALITY) or other Nginx sites.
- An existing Nginx installation with a compatible configuration.

See the [operations guide](docs/OPERATIONS.md) for the full requirements
and supported configurations.

The project is tested automatically and on a real Ubuntu VPS.
See the [test coverage documentation](docs/CI-COVERAGE.md) for details and limitations.

## Documentation

- [Operations and recovery](docs/OPERATIONS.md)
- [Test coverage and limitations](docs/CI-COVERAGE.md)
- [Telemt sources and release verification](docs/UPSTREAM.md)
- [MIT License](LICENSE)
