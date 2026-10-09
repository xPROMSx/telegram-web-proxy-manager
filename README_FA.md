<div align="center">

[🇷🇺 Русский](README.md) · [🇬🇧 English](README.en.md) · [🇪🇬 العربية](README_AR.md) · **🇮🇷 فارسی** · [🇨🇳 简体中文](README_ZH_CN.md) · [🇪🇸 Español](README_ES.md) · [🇹🇷 Türkçe](README_TR.md)

<h1 align="center">Telegram Web Proxy Manager</h1>

### پروکسی اختصاصی تلگرام روی VPS، بدون پیکربندی دستی

**HTTPS · سایت پوششی · SOCKS5 · به‌روزرسانی امن**

اتصال مستقیم به سرورهای تلگرام یا از طریق SOCKS5.

[![بررسی‌ها](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml/badge.svg)](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20%7C%2026.04-E95420?logo=ubuntu&logoColor=white)
[![انتشارها](https://img.shields.io/github/v/release/xPROMSx/telegram-web-proxy-manager)](https://github.com/xPROMSx/telegram-web-proxy-manager/releases/latest)

[انتشارها](https://github.com/xPROMSx/telegram-web-proxy-manager/releases) · [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) · [گزارش مشکل](https://github.com/xPROMSx/telegram-web-proxy-manager/issues)

</div>

**Telegram Web Proxy Manager** پروکسی Telegram WEB را نصب و پیکربندی می‌کند، اتصال امن HTTPS به آن را فراهم می‌سازد و به‌صورت خودکار یک سایت پوششی برای دامنه ایجاد می‌کند. اگر سرور VPS دسترسی مستقیم به تلگرام نداشته باشد، می‌توان برای اتصال به سرورهای تلگرام از پروکسی SOCKS5 استفاده کرد.

هنگام به‌روزرسانی Telemt، برنامه نسخه جدید را بررسی می‌کند و در صورت ناموفق بودن بررسی‌ها، نسخه سالم قبلی را برمی‌گرداند.

**سازگاری:** مجموعه کامل آزمون‌های یکپارچه‌سازی شامل بررسی کارکرد هم‌زمان با [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) است. [پوشش آزمون‌ها و محدودیت‌ها](docs/CI-COVERAGE.md).

## ✨ قابلیت‌ها

- نصب و راه‌اندازی پروکسی تلگرام با یک فرمان.
- ارتباط امن HTTPS با گواهی Let's Encrypt.
- راه‌اندازی خودکار سایت پوششی روی دامنه.
- به‌روزرسانی امن با بازگشت به نسخه سالم در صورت خطا.
- اتصال مستقیم به تلگرام یا استفاده از SOCKS5.
- بررسی وضعیت و دسترسی‌پذیری پروکسی.

## 🚀 شروع سریع

به یک VPS با **Ubuntu 24.04 یا 26.04**، دسترسی **root**، سرویس Nginx از پیش راه‌اندازی‌شده با پیکربندی سازگار، و **یک دامنه یا زیردامنه مستقل** نیاز دارید که رکورد DNS نوع A آن به IPv4 عمومی سرور اشاره کند. این نام **نباید در 3X-UI (از جمله REALITY) یا سایت دیگری در Nginx استفاده شده باشد**.

اگر سرور هنوز آماده نیست، ابتدا می‌توانید [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) را نصب کنید.

فرمان زیر را با دسترسی root اجرا کنید:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xPROMSx/telegram-web-proxy-manager/main/install.sh)
```

در منوی تعاملی، گزینه **Install** را انتخاب کنید و مراحل را دنبال کنید. پس از نصب، پیوند آماده‌ای با ساختار `tg://webproxy?...` برای افزودن پروکسی به تلگرام نمایش داده می‌شود. دامنه نیز سایت پوششی را از طریق HTTPS نمایش می‌دهد.

برای مدیریت بعدی، فرمان `telegram-web-proxy-manager` را اجرا کنید.

> **مهم:** پیوند اتصال حاوی کلید دسترسی به پروکسی شماست. آن را عمومی نکنید.

## 🤝 استفاده در کنار 3X-UI AUTO NGINX

اگر به **3X-UI** و Xray هم روی VPS نیاز دارید، از [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) استفاده کنید؛ این پروژه Nginx و HTTPS و پیکربندی 3X-UI را آماده می‌کند.

**ترتیب نصب:** ابتدا 3X-UI AUTO NGINX و سپس Telegram Web Proxy Manager. هر دو پروژه می‌توانند روی یک VPS اجرا شوند، اما سرویس‌ها و گواهی‌های خود را مستقل مدیریت می‌کنند. تلگرام به **دامنه یا زیردامنه آزاد و اختصاصی** نیاز دارد.

## فناوری زیربنایی

موتور پروکسی [Telemt](https://github.com/telemt/telemt) است. مدیر، Telemt را به‌صورت خودکار نصب، پیکربندی و به‌روزرسانی می‌کند و نیازی به نصب جداگانه آن نیست.

## پیش‌نیازها و آزمون‌ها

- **Ubuntu 24.04 یا 26.04** و دسترسی **root**.
- دامنه یا زیردامنه مستقل با رکورد DNS A به IPv4 عمومی VPS، بدون استفاده در 3X-UI / REALITY یا سایت دیگر Nginx.
- Nginx فعال با [پیکربندی پشتیبانی‌شده](docs/OPERATIONS.md).

پروژه دارای آزمون‌های خودکار، از جمله آزمون یکپارچه‌سازی Nginx و سازگاری با 3X-UI AUTO NGINX است. [پوشش آزمون‌ها و محدودیت‌ها](docs/CI-COVERAGE.md) را ببینید.

## مستندات

- [بهره‌برداری و بازیابی](docs/OPERATIONS.md)
- [پوشش آزمون‌ها و محدودیت‌ها](docs/CI-COVERAGE.md)
- [منابع Telemt و اعتبارسنجی انتشارها](docs/UPSTREAM.md)
- [مجوز GPL-3.0](LICENSE)
