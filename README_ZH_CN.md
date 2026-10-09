<div align="center">

[🇷🇺 Русский](README.md) · [🇬🇧 English](README.en.md) · [🇪🇬 العربية](README_AR.md) · [🇮🇷 فارسی](README_FA.md) · 🇨🇳 **简体中文** · [🇪🇸 Español](README_ES.md) · [🇹🇷 Türkçe](README_TR.md)

<h1 align="center"><img src="assets/branding/logo.png" alt="Telegram Web Proxy Manager" width="560"></h1>

### 无需手动配置，在 VPS 上部署自己的 Telegram 代理

**HTTPS · 伪装网站 · SOCKS5 · 安全更新**

直连 Telegram 服务器，或通过 SOCKS5 连接。

[![检查](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml/badge.svg)](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20%7C%2026.04-E95420?logo=ubuntu&logoColor=white)
[![版本发布](https://img.shields.io/github/v/release/xPROMSx/telegram-web-proxy-manager)](https://github.com/xPROMSx/telegram-web-proxy-manager/releases/latest)

[版本发布](https://github.com/xPROMSx/telegram-web-proxy-manager/releases) · [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) · [反馈问题](https://github.com/xPROMSx/telegram-web-proxy-manager/issues)

</div>

**Telegram Web Proxy Manager** 可自动安装和配置 Telegram WEB 代理，通过安全的 HTTPS 提供连接，并为域名创建伪装网站。如果 VPS 无法直接访问 Telegram，可以使用上游 SOCKS5 代理连接 Telegram 服务器。

更新 Telemt 时，管理器会验证新版本；如果检查失败，将恢复此前正常运行的版本。

**兼容性：** 完整的集成测试包含与 [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) 共存的兼容性检查。[测试覆盖范围与限制](docs/CI-COVERAGE.md)。

## ✨ 功能

- 一条命令安装并配置 Telegram 代理。
- 使用 Let's Encrypt 证书提供安全 HTTPS。
- 自动为域名部署伪装网站。
- 安全更新；失败时恢复上一正常版本。
- 直连 Telegram，或通过 SOCKS5 访问。
- 检查代理运行状态与连通性。

## 🚀 快速开始

需要一台运行 **Ubuntu 24.04 或 26.04** 的 VPS、**root** 权限、已运行且配置兼容的 Nginx，以及**一个独立的域名或子域名**。其 DNS A 记录必须指向服务器的公网 IPv4 地址。该域名**不能已用于 3X-UI（包括 REALITY）或其他 Nginx 网站**。

如果服务器尚未准备好，可以先安装 [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx)。

以 root 身份运行：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xPROMSx/telegram-web-proxy-manager/main/install.sh)
```

在交互式菜单中选择 **Install**，然后按提示操作。安装完成后，管理器会显示 `tg://webproxy?...` 格式的连接链接，可用于将代理添加到 Telegram。该域名也会通过 HTTPS 提供伪装网站。

日后管理代理时，运行 `telegram-web-proxy-manager`。

> **注意：** 连接链接包含代理访问密钥，请勿公开。

## 🤝 与 3X-UI AUTO NGINX 共存

如果 VPS 还需要运行 **3X-UI** 和 Xray，可以使用 [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx)，它会准备 Nginx、HTTPS 和 3X-UI 配置。

**安装顺序：** 先安装 3X-UI AUTO NGINX，再安装 Telegram Web Proxy Manager。两个项目可以在同一台 VPS 上运行，并分别管理各自的服务和证书。Telegram 必须使用**独立且未被占用的域名或子域名**。

## 底层组件

代理使用 [Telemt](https://github.com/telemt/telemt)。管理器会自动安装、配置和更新 Telemt，无需单独部署。

## 环境要求与测试

- **Ubuntu 24.04 或 26.04**，具有 **root** 权限。
- 独立的域名或子域名，其 DNS A 记录指向 VPS 公网 IPv4，且未被 3X-UI / REALITY 或其他 Nginx 网站使用。
- 正在运行的 Nginx，使用[受支持的配置](docs/OPERATIONS.md)。

项目包含自动化测试，其中覆盖 Nginx 集成及与 3X-UI AUTO NGINX 的兼容性。详见[测试范围与限制](docs/CI-COVERAGE.md)。

## 文档

- [运行维护与恢复](docs/OPERATIONS.md)
- [测试覆盖范围与限制](docs/CI-COVERAGE.md)
- [Telemt 来源与发布版本验证](docs/UPSTREAM.md)
- [GPL-3.0 许可证](LICENSE)
