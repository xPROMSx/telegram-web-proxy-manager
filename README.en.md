<div align="center">

[🇷🇺 Русский](README.md) · **🇬🇧 English** · [🇪🇬 العربية](README_AR.md) · [🇮🇷 فارسی](README_FA.md) · [🇨🇳 简体中文](README_ZH_CN.md) · [🇪🇸 Español](README_ES.md) · [🇹🇷 Türkçe](README_TR.md)

<h1 align="center">Telegram Web Proxy Manager</h1>

### Your own Telegram proxy on a VPS, without manual setup

**HTTPS · Cover site · SOCKS5 · Safe updates**

Connect directly to Telegram servers or through SOCKS5.

[![Checks](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml/badge.svg)](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20%7C%2026.04-E95420?logo=ubuntu&logoColor=white)
[![Releases](https://img.shields.io/github/v/release/xPROMSx/telegram-web-proxy-manager)](https://github.com/xPROMSx/telegram-web-proxy-manager/releases/latest)

[Releases](https://github.com/xPROMSx/telegram-web-proxy-manager/releases) · [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) · [Report an issue](https://github.com/xPROMSx/telegram-web-proxy-manager/issues)

</div>

**Telegram Web Proxy Manager** installs and configures a modern Telegram WEB proxy, serves it over secure HTTPS, and automatically creates a cover site for your domain. If your VPS cannot reach Telegram directly, you can use an upstream SOCKS5 proxy.

When updating Telemt, the manager verifies the new version and restores the previous working one if a check fails.

**Compatibility:** the full integration test suite includes coexistence checks with [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx). [Test coverage and limitations](docs/CI-COVERAGE.md).

## ✨ Features

- Install and configure a Telegram proxy with one command.
- Secure HTTPS with a Let's Encrypt certificate.
- An automatically deployed cover site on your domain.
- Safe updates with rollback to the working version on failure.
- Direct access to Telegram or an upstream SOCKS5 proxy.
- Proxy health and connectivity checks.

## 🚀 Quick start

You need a VPS running **Ubuntu 24.04 or 26.04**, **root** access, an already configured and compatible Nginx instance, and a **separate domain or subdomain** with a DNS A record pointing to your server's public IPv4 address. The hostname **must not already be used by 3X-UI (including REALITY) or another Nginx site**.

If the VPS is not prepared yet, you can first install [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx).

Run as root:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xPROMSx/telegram-web-proxy-manager/main/install.sh)
```

The interactive menu opens. Choose **Install** and follow the prompts. When installation finishes, the manager displays a `tg://webproxy?...` connection link to add the proxy to Telegram. Your domain serves a cover site over HTTPS.

For later management, run `telegram-web-proxy-manager`.

> **Important:** the connection link contains the access key for your proxy. Do not publish it.

## 🤝 Coexistence with 3X-UI AUTO NGINX

If you also need **3X-UI** and Xray on the VPS, use [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx). It prepares Nginx, HTTPS, and the 3X-UI configuration.

**Install order:** first 3X-UI AUTO NGINX, then Telegram Web Proxy Manager. Both projects can run on the same VPS while managing their own services and certificates independently. Telegram needs **its own unused domain or subdomain**.

## Under the hood

The proxy is powered by [Telemt](https://github.com/telemt/telemt). The manager installs, configures, and updates Telemt; you do not need to install it separately.

## Requirements and testing

- **Ubuntu 24.04 or 26.04**, **root** access.
- A separate domain or subdomain with a DNS A record pointing to the VPS's public IPv4 address, not used by 3X-UI / REALITY or another Nginx site.
- A running Nginx instance with a [supported configuration](docs/OPERATIONS.md).

The project undergoes automated testing, including Nginx integration and compatibility with 3X-UI AUTO NGINX. See [test coverage and limitations](docs/CI-COVERAGE.md).

## Documentation

- [Operations and recovery](docs/OPERATIONS.md)
- [Test coverage and limitations](docs/CI-COVERAGE.md)
- [Telemt sources and release verification](docs/UPSTREAM.md)
- [GPL-3.0 License](LICENSE)
