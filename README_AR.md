<div align="center">

[🇷🇺 Русский](README.md) · [🇬🇧 English](README.en.md) · **🇪🇬 العربية** · [🇮🇷 فارسی](README_FA.md) · [🇨🇳 简体中文](README_ZH_CN.md) · [🇪🇸 Español](README_ES.md) · [🇹🇷 Türkçe](README_TR.md)

<h1 align="center">Telegram Web Proxy Manager</h1>

### بروكسي Telegram خاص بك على خادم VPS دون إعداد يدوي

**HTTPS · موقع تمويه · SOCKS5 · تحديثات آمنة**

الاتصال بخوادم Telegram مباشرة أو عبر SOCKS5.

[![الفحوصات](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml/badge.svg)](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20%7C%2026.04-E95420?logo=ubuntu&logoColor=white)
[![الإصدارات](https://img.shields.io/github/v/release/xPROMSx/telegram-web-proxy-manager)](https://github.com/xPROMSx/telegram-web-proxy-manager/releases/latest)

[الإصدارات](https://github.com/xPROMSx/telegram-web-proxy-manager/releases) · [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) · [الإبلاغ عن مشكلة](https://github.com/xPROMSx/telegram-web-proxy-manager/issues)

</div>

يقوم **Telegram Web Proxy Manager** بتثبيت بروكسي Telegram WEB وتهيئته، ويتيح الاتصال به عبر HTTPS آمن، وينشئ تلقائيًا موقع تمويه على نطاقك. إذا تعذّر على خادم VPS الوصول مباشرةً إلى Telegram، فيمكن استخدام بروكسي SOCKS5 للاتصال بالخوادم.

عند تحديث Telemt، يتحقق البرنامج من الإصدار الجديد ويستعيد الإصدار السابق الذي كان يعمل إذا فشلت الفحوصات.

**التوافق:** تتضمن مجموعة اختبارات التكامل الكاملة التحقق من التشغيل المشترك مع [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx). [نطاق الاختبارات وحدودها](docs/CI-COVERAGE.md).

## ✨ المزايا

- تثبيت بروكسي Telegram وتهيئته بأمر واحد.
- اتصال HTTPS آمن بشهادة من Let's Encrypt.
- إنشاء موقع تمويه تلقائيًا على نطاقك.
- تحديثات آمنة مع الرجوع إلى الإصدار العامل عند حدوث خطأ.
- الاتصال بـ Telegram مباشرةً أو عبر SOCKS5.
- التحقق من حالة البروكسي وإمكانية الاتصال.

## 🚀 البدء السريع

تحتاج إلى خادم VPS يعمل بنظام **Ubuntu 24.04 أو 26.04**، وصلاحيات **root**، وخادم Nginx مُعد مسبقًا بإعداد متوافق، و**نطاق أو نطاق فرعي مستقل** يشير سجل DNS من النوع A الخاص به إلى عنوان IPv4 العام للخادم. يجب **ألا يكون هذا الاسم مستخدمًا في 3X-UI (بما في ذلك REALITY) أو في موقع آخر على Nginx**.

إذا لم يكن الخادم مجهزًا بعد، يمكنك تثبيت [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) أولًا.

نفّذ الأمر بصلاحيات root:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xPROMSx/telegram-web-proxy-manager/main/install.sh)
```

من القائمة التفاعلية، اختر **Install** واتبع التعليمات. بعد اكتمال التثبيت، سيظهر رابط اتصال بصيغة `tg://webproxy?...` لإضافة البروكسي إلى Telegram. وسيعرض نطاقك موقع تمويه عبر HTTPS.

لإدارة البروكسي لاحقًا، شغّل `telegram-web-proxy-manager`.

> **مهم:** يحتوي رابط الاتصال على مفتاح الوصول إلى البروكسي. لا تنشره.

## 🤝 التشغيل مع 3X-UI AUTO NGINX

إذا كنت تحتاج أيضًا إلى **3X-UI** وXray على خادم VPS، فاستخدم [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) لإعداد Nginx وHTTPS وتهيئة 3X-UI.

**ترتيب التثبيت:** ثبّت 3X-UI AUTO NGINX أولًا، ثم Telegram Web Proxy Manager. يمكن تشغيل المشروعين على الخادم نفسه، مع إدارة مستقلة للخدمات والشهادات الخاصة بكل منهما. يحتاج Telegram إلى **نطاق أو نطاق فرعي مستقل وغير مستخدم**.

## المكوّن المستخدم

يعتمد البروكسي على [Telemt](https://github.com/telemt/telemt). يتولى البرنامج تثبيته وتهيئته وتحديثه، لذا لا تحتاج إلى تثبيت Telemt بشكل منفصل.

## المتطلبات والاختبارات

- **Ubuntu 24.04 أو 26.04** وصلاحيات **root**.
- نطاق أو نطاق فرعي مستقل يشير سجل DNS A الخاص به إلى عنوان IPv4 العام للخادم، ولا يستخدمه 3X-UI / REALITY أو موقع آخر على Nginx.
- Nginx يعمل باستخدام [إعداد مدعوم](docs/OPERATIONS.md).

يخضع المشروع لاختبارات آلية، بما فيها اختبارات تكامل Nginx والتوافق مع 3X-UI AUTO NGINX. راجع [نطاق الاختبارات وحدودها](docs/CI-COVERAGE.md).

## الوثائق

- [التشغيل والاستعادة](docs/OPERATIONS.md)
- [نطاق الاختبارات وحدودها](docs/CI-COVERAGE.md)
- [مصادر Telemt والتحقق من الإصدارات](docs/UPSTREAM.md)
- [رخصة GPL-3.0](LICENSE)
