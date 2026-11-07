<div align="center">

[🇷🇺 Русский](README.md) · [🇬🇧 English](README.en.md) · [🇪🇬 العربية](README_AR.md) · [🇮🇷 فارسی](README_FA.md) · 🇨🇳 **简体中文** · [🇪🇸 Español](README_ES.md) · [🇹🇷 Türkçe](README_TR.md)

<h1 align="center"><img src="assets/branding/logo.png" alt="Telegram Web Proxy Manager" width="560"></h1>

### 在自己的 VPS 上部署支持 HTTPS 和完整伪装网站的 Telegram WEB 代理

**TELEMT · NGINX · HTTPS · 伪装网站 · SOCKS5 · 安全更新**

一台 VPS、一个独立域名，以及可直接添加到 Telegram 的连接链接。

[![检查](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml/badge.svg)](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20%7C%2026.04-E95420?logo=ubuntu&logoColor=white)
[![版本发布](https://img.shields.io/github/v/release/xPROMSx/telegram-web-proxy-manager)](https://github.com/xPROMSx/telegram-web-proxy-manager/releases/latest)

[📦 版本发布](https://github.com/xPROMSx/telegram-web-proxy-manager/releases) · [⚙️ 3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) · [❤️ 支持项目](#support-development) · [🐛 反馈问题](https://github.com/xPROMSx/telegram-web-proxy-manager/issues) · [💬 交流反馈](https://t.me/promsdev)

</div>

**Telegram Web Proxy Manager (TWPM)** 是一款免费的 VPS Telegram WEB 代理安装与维护工具。它以 [Telemt](https://github.com/telemt/telemt) 为代理核心，通过 Nginx 提供 HTTPS、按域名路由和伪装网站。管理器负责配置必要组件、申请 Let's Encrypt 证书，并生成可直接添加到 Telegram 的连接链接。

**不仅仅是 Telemt 安装脚本：** 每次全新安装都会创建一个经过个性化设计的原创多页面网站。网站直接使用现有 Nginx，无需额外部署 Web 服务器；代理、证书与网站统一纳入管理。

TWPM 和 [**3X-UI AUTO NGINX**](https://github.com/xPROMSx/3x-ui-auto-nginx) 是 xPROMSx 旗下两个为协同运行而开发的项目。它们可以在同一台 VPS 上共享 Nginx，同时独立管理各自的设置、证书和服务。**TWPM 也支持其他符合要求的 Nginx 配置**，无需强制安装 3X-UI。

## ✨ 主要功能

| | |
| --- | --- |
| **完整的伪装网站**<br>三种原创主题、多页面、可用的导航、插图以及适配手机的界面。 | **每次安装都有独特外观**<br>创建网站时自动选择名称、配色、文字和图片。 |
| **通过 Nginx 提供 HTTPS**<br>独立域名、Let's Encrypt、SNI 路由，并可与其他服务共享 TCP/443。 | **集成 3X-UI AUTO NGINX**<br>可从配套项目的菜单安装或启动 Telegram 代理，不替换原有连接。 |
| **安全更新 Telemt**<br>发现官方版本、验证来源与运行状态，并保留上一正常版本。 | **保留现有安装**<br>日常维护不会替换设置、密钥、数据、证书和网站。 |
| **直连或 SOCKS5**<br>当 VPS 无法直连 Telegram 时，可选择经由代理访问。 | **简单管理**<br>提供英语和俄语菜单，可安装、更新、检查、修复、查看链接及卸载。 |

<a id="quick-start"></a>

## 🚀 快速开始

需要一台运行 **Ubuntu 24.04 或 26.04** 的 **VPS**、**root** 权限、已运行且采用受支持 SNI 配置的 Nginx，以及**独立域名或子域名**。域名的 DNS A 记录必须指向 VPS 的公网 IPv4 地址。申请 HTTPS 证书需要 TCP/80 可访问，代理连接需要 TCP/443 可访问。

> [!IMPORTANT]
> Telegram 代理域名必须**尚未被使用**。不要复用 3X-UI 面板、REALITY、Vision 或现有 Nginx 网站的域名。

**如果已经安装了 3X-UI AUTO NGINX**，打开其主菜单，选择 **4 — Telegram Web Proxy Manager**，即可安装 TWPM 或启动已安装的管理器。

**如果独立安装**，请在已配置受支持 Nginx 的 VPS 上以 root 身份执行：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xPROMSx/telegram-web-proxy-manager/main/install.sh)
```

启动后选择 **1 — English** 或 **2 — Русский**。管理器目前仅提供英语和俄语界面。随后会显示主菜单（以下保留英语界面的实际选项名称）：

- **1 — Install Telegram proxy：** 全新安装，或检查已有安装而不重新安装。
- **2 — Update Telemt：** 检查并安全更新代理核心。
- **3 — Check status：** 在不修改设置的情况下检查运行状态。
- **4 — Check and restart services：** 验证配置、重启 Telemt 并重新加载 Nginx 配置。
- **5 — Show connection link：** 再次显示添加到 Telegram 的代理链接。
- **6 — Uninstall Telegram proxy：** 经确认后移除管理器负责的安装。
- **0 — Exit：** 退出。

第一次安装时，选择 **1 — Install Telegram proxy**。管理器会依次询问：

1. **WEB proxy domain（WEB 代理域名）。** 输入提前准备好的独立且未被占用的域名或子域名。
2. **Public IPv4（公网 IPv4）。** 管理器会尝试自动检测 VPS 的 IP 地址。请将结果与服务器实际 IPv4 及该域名的 DNS A 记录核对。正确时直接按 **Enter**；检测失败或地址错误时请手动输入正确地址。
3. **Use SOCKS5 upstream? [y/N]（使用 SOCKS5 上游代理？）** SOCKS5 是可选的中间代理，可让 VPS 通过它连接 Telegram 服务器。**如果 VPS 能直接访问 Telegram，就不需要 SOCKS5：直接按 Enter 或选择 N。** 如果无法直连，请在安装前自行配置一个可用的 SOCKS5 代理，再选择 **Y** 并填写主机地址和端口。**不清楚 SOCKS5 是什么？选择 N 即可。**

安装完成后，管理器会配置 HTTPS 和伪装网站，并显示 `tg://webproxy?...` 格式的链接，用于将代理添加到 Telegram。

以后管理代理时运行：

```bash
telegram-web-proxy-manager
```

> [!CAUTION]
> Telegram 连接链接包含你的私有代理访问密钥，请勿公开或分享给他人。

## 🌐 伪装网站与 Nginx

**不再是简单的占位页面，而是完整的网站。** 每次全新安装都会自动创建以下三种原创设计之一：

- **Botanical Journal** — 植物主题杂志。
- **Night Sky Guide** — 夜空观测指南。
- **Home Kitchen** — 家庭烹饪网站。

每套设计包含 **11 个本地文件**，提供多个页面、样式和插图。网站适配移动设备，无需加载外部资源，并具有独特的个性化外观。更新和维护时会保留已选设计；旧版安装的网站也不会被替换。

**网站与代理共同使用已安装的 Nginx。** 无需 Docker 或额外的 Web 服务器。

## 🤝 与 3X-UI AUTO NGINX 集成

**两个独立项目，共享兼容的基础设施。** [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) 安装和管理 3X-UI/Xray 及共享的 Nginx 配置。**Telegram Web Proxy Manager** 通过受支持的 Nginx 路由和自己的域名添加独立的 Telegram WEB 代理。

- **推荐安装顺序：** 先安装 3X-UI AUTO NGINX，再安装 TWPM。前者负责安装 Nginx，TWPM 不会自行安装。
- **共享 TCP/443：** SNI 路由让多个服务可共用一台 VPS，而不替换现有 3X-UI 路由。
- **独立维护：** TWPM 只管理自己的 Telemt、网站和证书，不接管 3X-UI 的设置或数据。
- **兼容 Backup v3：** 当前的 3X-UI AUTO NGINX 可识别 TWPM 的标准配置。但 3X-UI 备份**不能代替单独备份 Telemt 自身的数据**。

**其他 Nginx 配置也可使用**，前提是符合 TWPM 已知的 stream/SNI 布局，包括部分使用独立 `include` 文件的布局。管理器不会自动改造任意 Nginx 配置；遇到未知或冲突的布局时会安全拒绝。参见[技术要求](docs/OPERATIONS.md#nginx-requirements)。

> [!IMPORTANT]
> TWPM 仅支持 **Ubuntu 24.04 和 26.04**。3X-UI AUTO NGINX 支持 Debian，并不代表 Telegram Web Proxy Manager 也支持 Debian。

## 🔄 更新与维护

首次安装时，管理器会部署经过验证的 Telemt 版本。**Universal Update** 独立查找最新的官方稳定兼容版本，并在切换前进行验证。更新失败时提供恢复上一个正常版本和保留数据状态的机制。

更新 **TWPM 管理器本身**与更新 **Telemt 核心**是不同操作。日常维护不会重新生成网站、重置密钥，也不会未经同意将旧安装迁移到新布局。

可从菜单检查运行状态，必要时对受支持的安装执行修复。卸载只清理已确认属于管理器的对象；删除证书需要单独确认。

## ⚙️ 系统要求与测试

- **系统：** Ubuntu 24.04 / 26.04，x86_64 或 ARM64，root 权限及 systemd。
- **网络：** 独立域名或子域名、正确的 DNS A 记录以及所需 TCP 端口可访问。
- **Nginx：** 已存在且受支持的 stream/SNI 配置。管理器不会安装 Nginx、3X-UI 或 Xray，也不会修改系统防火墙规则。
- **Telemt：** 由 TWPM 安装；全新安装使用经过验证的基准版本 **3.5.16**，Universal Update 独立运行。

项目在受支持的 Ubuntu 版本上进行自动化和集成测试，包括真实的 Nginx 与 Telemt 测试。非标准 Nginx 配置需要单独验证兼容性。[测试范围与限制](docs/CI-COVERAGE.md)。

## 📖 文档

- [运行维护、Nginx 兼容性与恢复](docs/OPERATIONS.md)
- [测试覆盖范围与限制](docs/CI-COVERAGE.md)
- [Telemt 来源与更新安全](docs/UPSTREAM.md)
- [GPL-3.0 许可证](LICENSE)

## 💬 交流与反馈

关注 [Telegram 频道 @promsdev](https://t.me/promsdev)，了解 xPROMSx 项目动态。可以通过[频道私信](https://t.me/promsdev?direct)提出问题和建议，并在 [GitHub Issues](https://github.com/xPROMSx/telegram-web-proxy-manager/issues) 中报告错误。

<a id="support-development"></a>

## ❤️ 支持项目开发

Telegram Web Proxy Manager 免费开放使用。如果项目对你有帮助，欢迎[自愿支持其持续开发](docs/SUPPORT_ZH_CN.md)。捐助不会影响任何功能的使用权限。

<div align="center">

**自己的 Telegram 代理。安全 HTTPS。完整的伪装网站。**

⭐ 如果你觉得项目有用，欢迎[点亮 Star](https://github.com/xPROMSx/telegram-web-proxy-manager)，帮助更多人发现它。

[安装](#quick-start) · [版本发布](https://github.com/xPROMSx/telegram-web-proxy-manager/releases) · [问题反馈](https://github.com/xPROMSx/telegram-web-proxy-manager/issues)

</div>
