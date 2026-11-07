<div align="center">

[🇷🇺 Русский](README.md) · 🇬🇧 **English** · [🇪🇬 العربية](README_AR.md) · [🇮🇷 فارسی](README_FA.md) · [🇨🇳 简体中文](README_ZH_CN.md) · [🇪🇸 Español](README_ES.md) · [🇹🇷 Türkçe](README_TR.md)

<h1 align="center"><img src="assets/branding/logo.png" alt="Telegram Web Proxy Manager" width="560"></h1>

### Your own Telegram WEB proxy with HTTPS and a complete cover website

**TELEMT · NGINX · HTTPS · COVER WEBSITE · SOCKS5 · SAFE UPDATES**

One VPS, a dedicated domain, and a ready-to-use Telegram connection link.

[![Checks](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml/badge.svg)](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20%7C%2026.04-E95420?logo=ubuntu&logoColor=white)
[![Release](https://img.shields.io/github/v/release/xPROMSx/telegram-web-proxy-manager)](https://github.com/xPROMSx/telegram-web-proxy-manager/releases/latest)

[📦 Releases](https://github.com/xPROMSx/telegram-web-proxy-manager/releases) · [⚙️ 3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) · [❤️ Support](#support-development) · [🐛 Report an issue](https://github.com/xPROMSx/telegram-web-proxy-manager/issues) · [💬 Community](https://t.me/promsdev)

</div>

**Telegram Web Proxy Manager (TWPM)** is a free manager for deploying and maintaining your own Telegram WEB proxy on a VPS. It uses [Telemt](https://github.com/telemt/telemt) as the proxy engine and Nginx for HTTPS, domain-based routing, and the cover website. The manager configures the necessary components, obtains a Let's Encrypt certificate, and provides a ready-to-use Telegram connection link.

**More than a Telemt installer:** every fresh installation gets an original, personalized, multi-page website. It uses your existing Nginx rather than a separate web server; the proxy, certificates, and website are managed together.

TWPM and [**3X-UI AUTO NGINX**](https://github.com/xPROMSx/3x-ui-auto-nginx) are two xPROMSx projects developed to work together. They can share one VPS and one Nginx installation while managing their own settings, certificates, and services independently. **TWPM also supports other compatible Nginx configurations** — installing 3X-UI is optional.

## ✨ Features

| | |
| --- | --- |
| **Complete cover website**<br>Three original themes, multiple pages, working navigation, illustrations, and mobile-friendly design. | **Personalized installation**<br>Names, color schemes, text, and illustrations are chosen when the site is created. |
| **HTTPS through Nginx**<br>A dedicated domain, Let's Encrypt, SNI routing, and coexistence with other services on TCP/443. | **3X-UI AUTO NGINX integration**<br>Install or launch the Telegram proxy from the companion project's menu without replacing its connections. |
| **Safe Telemt updates**<br>Official release discovery, authenticity and health checks, with the previous working version preserved. | **Existing installation preserved**<br>Settings, keys, data, certificates, and the website are not replaced during routine maintenance. |
| **Direct connection or SOCKS5**<br>Choose how the VPS reaches Telegram servers if direct connectivity is unavailable. | **Simple management**<br>English and Russian menus for installation, updates, checks, repair, connection links, and removal. |

<a id="quick-start"></a>

## 🚀 Quick start

You need a **VPS with Ubuntu 24.04 or 26.04**, **root** access, a running Nginx instance with a supported SNI configuration, and a **dedicated domain or subdomain**. Its DNS A record must point to the VPS's public IPv4 address. TCP/80 must be reachable for HTTPS certificate issuance and TCP/443 for proxy connections.

> [!IMPORTANT]
> The Telegram proxy's domain must be **unused**. Do not reuse a 3X-UI panel, REALITY, Vision, or existing Nginx website domain.

**If 3X-UI AUTO NGINX is already installed**, open its main menu and select **4 — Telegram Web Proxy Manager**. You can install TWPM or launch an existing installation from there.

**For a standalone installation** on a VPS with supported Nginx, run as root:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xPROMSx/telegram-web-proxy-manager/main/install.sh)
```

Select **1 — English** or **2 — Русский** when prompted. The main menu will appear:

- **1 — Install Telegram proxy:** a fresh installation or a check of an existing one without reinstalling it.
- **2 — Update Telemt:** check for and safely install an engine update.
- **3 — Check status:** check functionality without changing settings.
- **4 — Check and restart services:** validate the configuration, restart Telemt, and reload Nginx.
- **5 — Show connection link:** display your Telegram proxy link again.
- **6 — Uninstall Telegram proxy:** remove the managed installation after confirmation.
- **0 — Exit.**

For your first installation, choose **1 — Install Telegram proxy**. The manager will ask for:

1. **WEB proxy domain.** Enter your prepared, unused domain or subdomain.
2. **Public IPv4.** The manager will attempt to detect the VPS's IP address automatically. Compare it with the server's IPv4 and the domain's DNS A record. If correct, simply press **Enter**. If detection fails or the address is wrong, enter the correct one manually.
3. **Use SOCKS5 upstream? [y/N]** SOCKS5 is an optional intermediary proxy through which your VPS can reach Telegram servers. **If your VPS can reach Telegram directly, you do not need SOCKS5: press Enter or choose N.** If direct access is unavailable, configure a working SOCKS5 proxy *before* installation, then select **Y** and enter its host and port. **Not sure what SOCKS5 is? Choose N.**

When installation finishes, the manager sets up HTTPS and the cover website and displays a ready-to-use `tg://webproxy?...` link to add the proxy to Telegram.

For later management, run:

```bash
telegram-web-proxy-manager
```

> [!CAUTION]
> The Telegram connection link contains your private proxy access key. Do not publish or share it.

## 🌐 Cover websites and Nginx

**A complete website instead of a generic placeholder.** Each fresh installation automatically creates one of three original designs:

- **Botanical Journal** — a journal about plants.
- **Night Sky Guide** — a guide to the night sky.
- **Home Kitchen** — a home cooking website.

Each design has **11 local files** with multiple pages, styling, and illustrations. The site is mobile-friendly, needs no external resources, and gets its own personalized appearance. Its design is preserved during updates and maintenance; existing websites from earlier installations are left untouched.

**The website and proxy run through your existing Nginx.** No Docker or additional web server is needed.

## 🤝 Integration with 3X-UI AUTO NGINX

**Two independent projects, one compatible infrastructure.** [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) installs and manages 3X-UI/Xray and the shared Nginx configuration. **Telegram Web Proxy Manager** adds a separate Telegram WEB proxy using supported Nginx routing and its own domain.

- **Recommended order:** install 3X-UI AUTO NGINX first, then TWPM. The first project installs Nginx; TWPM does not install it.
- **Shared TCP/443:** SNI routing lets the services share a VPS without replacing the existing 3X-UI routes.
- **Independent maintenance:** TWPM manages its own Telemt, website, and certificates without taking over 3X-UI configuration or data.
- **Backup v3 compatibility:** current 3X-UI AUTO NGINX recognizes standard TWPM configurations. However, the 3X-UI backup **does not replace a backup of Telemt's own data**.

**Other Nginx configurations are supported** if they match the known TWPM stream/SNI layouts, including certain layouts with separate `include` files. The manager does not rewrite arbitrary Nginx configurations: it refuses unsupported or conflicting layouts safely. [Technical requirements](docs/OPERATIONS.md#nginx-requirements).

> [!IMPORTANT]
> TWPM supports **Ubuntu 24.04 and 26.04**. Debian support in 3X-UI AUTO NGINX does not imply Debian support in Telegram Web Proxy Manager.

## 🔄 Updates and maintenance

On first installation, the manager deploys a verified Telemt version. **Universal Update** separately discovers the latest compatible official stable release and verifies it before switching. If an update fails, recovery of the previous working version and preservation of state are provided.

Updating **TWPM itself** and updating **Telemt** are separate operations. Routine maintenance does not recreate the website, reset secrets, or migrate older installations to a new layout without consent.

Status checks are available from the menu, and repair is available for supported installations when needed. Removal affects only verified manager-owned objects; certificate deletion requires separate confirmation.

## ⚙️ Requirements and testing

- **OS:** Ubuntu 24.04 / 26.04, x86_64 or ARM64; root access and systemd.
- **Network:** a dedicated domain or subdomain, correct DNS A record, and accessible required TCP ports.
- **Nginx:** an existing supported stream/SNI configuration. The manager does not install Nginx, 3X-UI, or Xray or change system firewall rules.
- **Telemt:** installed by TWPM; the fresh-install baseline is the verified **3.5.16** release, while Universal Update operates separately.

The project undergoes automated and integration tests on supported Ubuntu versions, including real Nginx and Telemt tests. Nonstandard Nginx configurations require separate compatibility checks. [Test coverage and limitations](docs/CI-COVERAGE.md).

## 📖 Documentation

- [Operations, Nginx compatibility, and recovery](docs/OPERATIONS.md)
- [Test coverage and limitations](docs/CI-COVERAGE.md)
- [Telemt sources and update security](docs/UPSTREAM.md)
- [GPL-3.0 License](LICENSE)

## 💬 Community & feedback

Follow xPROMSx project news in the [@promsdev Telegram channel](https://t.me/promsdev). Send questions and ideas through [channel messages](https://t.me/promsdev?direct), and report issues through [GitHub Issues](https://github.com/xPROMSx/telegram-web-proxy-manager/issues).

<a id="support-development"></a>

## ❤️ Support development

Telegram Web Proxy Manager is free and open for everyone to use. If it has been helpful, you can [voluntarily support its development](docs/SUPPORT.en.md). Donations never affect access to features.

<div align="center">

**Your own Telegram proxy. Secure HTTPS. A complete cover website.**

⭐ If you find the project useful, [give it a Star](https://github.com/xPROMSx/telegram-web-proxy-manager) to help others discover it.

[Installation](#quick-start) · [Releases](https://github.com/xPROMSx/telegram-web-proxy-manager/releases) · [Issues](https://github.com/xPROMSx/telegram-web-proxy-manager/issues)

</div>
