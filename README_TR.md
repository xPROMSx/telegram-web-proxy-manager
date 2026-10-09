<div align="center">

[🇷🇺 Русский](README.md) · [🇬🇧 English](README.en.md) · [🇪🇬 العربية](README_AR.md) · [🇮🇷 فارسی](README_FA.md) · [🇨🇳 简体中文](README_ZH_CN.md) · [🇪🇸 Español](README_ES.md) · **🇹🇷 Türkçe**

<h1 align="center">Telegram Web Proxy Manager</h1>

### Elle yapılandırma gerektirmeden VPS'inizde kendi Telegram proxy'niz

**HTTPS · Kamuflaj sitesi · SOCKS5 · Güvenli güncellemeler**

Telegram sunucularına doğrudan veya SOCKS5 üzerinden bağlanın.

[![Kontroller](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml/badge.svg)](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20%7C%2026.04-E95420?logo=ubuntu&logoColor=white)
[![Sürümler](https://img.shields.io/github/v/release/xPROMSx/telegram-web-proxy-manager)](https://github.com/xPROMSx/telegram-web-proxy-manager/releases/latest)

[Sürümler](https://github.com/xPROMSx/telegram-web-proxy-manager/releases) · [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) · [Sorun bildir](https://github.com/xPROMSx/telegram-web-proxy-manager/issues)

</div>

**Telegram Web Proxy Manager**, bir Telegram WEB proxy sunucusunu kurup yapılandırır, güvenli HTTPS bağlantısı sağlar ve alan adınız için otomatik olarak bir kamuflaj sitesi oluşturur. VPS'iniz Telegram'a doğrudan erişemiyorsa çıkış bağlantısı için bir SOCKS5 proxy kullanabilirsiniz.

Telemt güncellenirken yeni sürüm doğrulanır; kontroller başarısız olursa önceki çalışan sürüm geri yüklenir.

**Uyumluluk:** kapsamlı entegrasyon testleri, [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) ile birlikte çalışmayı da kapsar. [Test kapsamı ve sınırları](docs/CI-COVERAGE.md).

## ✨ Özellikler

- Tek komutla Telegram proxy kurulumu ve yapılandırması.
- Let's Encrypt sertifikasıyla güvenli HTTPS.
- Alan adında otomatik olarak yayımlanan kamuflaj sitesi.
- Hata durumunda çalışan sürüme dönen güvenli güncellemeler.
- Telegram'a doğrudan ya da SOCKS5 üzerinden erişim.
- Proxy durumu ve bağlantı kontrolleri.

## 🚀 Hızlı başlangıç

**Ubuntu 24.04 veya 26.04** çalıştıran bir VPS, **root** erişimi, önceden yapılandırılmış uyumlu bir Nginx kurulumu ve DNS A kaydı sunucunun genel IPv4 adresine işaret eden **ayrı bir alan adı veya alt alan adı** gerekir. Bu ad **3X-UI (REALITY dahil) veya başka bir Nginx sitesi tarafından kullanılmamalıdır**.

Sunucunuz henüz hazır değilse önce [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) kurabilirsiniz.

Root olarak çalıştırın:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xPROMSx/telegram-web-proxy-manager/main/install.sh)
```

Açılan menüde **Install** seçeneğini seçin ve yönergeleri izleyin. Kurulum tamamlandığında Telegram'a proxy eklemek için `tg://webproxy?...` biçiminde bir bağlantı gösterilir. Alan adınız HTTPS üzerinden kamuflaj sitesini sunar.

Sonraki yönetim işlemleri için `telegram-web-proxy-manager` komutunu kullanın.

> **Önemli:** bağlantı, proxy erişim anahtarınızı içerir. Bağlantıyı herkese açık paylaşmayın.

## 🤝 3X-UI AUTO NGINX ile birlikte kullanım

VPS'inizde **3X-UI** ve Xray de kullanmak istiyorsanız Nginx, HTTPS ve 3X-UI yapılandırmasını hazırlayan [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) projesini kullanın.

**Kurulum sırası:** önce 3X-UI AUTO NGINX, ardından Telegram Web Proxy Manager. İki proje aynı VPS üzerinde çalışabilir; hizmetlerini ve sertifikalarını bağımsız olarak yönetir. Telegram için **ayrı ve kullanılmayan bir alan adı veya alt alan adı** gerekir.

## Altyapı

Proxy, [Telemt](https://github.com/telemt/telemt) kullanır. Yöneticisi Telemt'yi otomatik kurar, yapılandırır ve günceller; ayrıca kurmanız gerekmez.

## Gereksinimler ve testler

- **Ubuntu 24.04 veya 26.04**, **root** erişimi.
- DNS A kaydı VPS'in genel IPv4 adresine işaret eden ve 3X-UI / REALITY ya da diğer Nginx sitelerince kullanılmayan ayrı bir alan adı veya alt alan adı.
- [Desteklenen yapılandırmaya](docs/OPERATIONS.md) sahip, çalışan bir Nginx kurulumu.

Proje, gerçek Nginx entegrasyonu ve 3X-UI AUTO NGINX uyumluluğu dahil otomatik testlerden geçer. [Test kapsamı ve sınırlamalar](docs/CI-COVERAGE.md) belgesine bakın.

## Belgeler

- [İşletim ve kurtarma](docs/OPERATIONS.md)
- [Test kapsamı ve sınırlamalar](docs/CI-COVERAGE.md)
- [Telemt kaynakları ve sürüm doğrulaması](docs/UPSTREAM.md)
- [GPL-3.0 Lisansı](LICENSE)
