<div align="center">

[🇷🇺 Русский](README.md) · [🇬🇧 English](README.en.md) · [🇪🇬 العربية](README_AR.md) · [🇮🇷 فارسی](README_FA.md) · [🇨🇳 简体中文](README_ZH_CN.md) · [🇪🇸 Español](README_ES.md) · 🇹🇷 **Türkçe**

<h1 align="center"><img src="assets/branding/logo.png" alt="Telegram Web Proxy Manager" width="560"></h1>

### HTTPS ve tam kapsamlı kamuflaj sitesiyle kendi Telegram WEB proxy'niz

**TELEMT · NGINX · HTTPS · KAMUFLAJ SİTESİ · SOCKS5 · GÜVENLİ GÜNCELLEMELER**

Tek VPS, ayrı bir alan adı ve Telegram'a eklemeye hazır bağlantı.

[![Kontroller](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml/badge.svg)](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20%7C%2026.04-E95420?logo=ubuntu&logoColor=white)
[![Sürüm](https://img.shields.io/github/v/release/xPROMSx/telegram-web-proxy-manager)](https://github.com/xPROMSx/telegram-web-proxy-manager/releases/latest)

[📦 Sürümler](https://github.com/xPROMSx/telegram-web-proxy-manager/releases) · [⚙️ 3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) · [❤️ Destekle](#-geliştirmeyi-destekleyin) · [🐛 Sorun bildir](https://github.com/xPROMSx/telegram-web-proxy-manager/issues) · [💬 Topluluk](https://t.me/promsdev)

</div>

**Telegram Web Proxy Manager (TWPM)**, VPS üzerinde kendi Telegram WEB proxy'nizi kurup yönetmenizi sağlayan ücretsiz bir yöneticidir. Proxy motoru olarak [Telemt](https://github.com/telemt/telemt), HTTPS, alan adına göre yönlendirme ve kamuflaj sitesi için Nginx kullanır. Gerekli bileşenleri yapılandırır, Let's Encrypt sertifikası alır ve Telegram için hazır bağlantı sunar.

**Telemt kurulumundan çok daha fazlası:** her yeni kurulum, kişiselleştirilmiş tasarıma sahip özgün, çok sayfalı bir web sitesi oluşturur. Ek bir web sunucusu yerine mevcut Nginx kullanılır; proxy, sertifikalar ve site birlikte yönetilir.

TWPM ve [**3X-UI AUTO NGINX**](https://github.com/xPROMSx/3x-ui-auto-nginx), birlikte çalışmaları gözetilerek geliştirilen iki xPROMSx projesidir. Aynı VPS ve Nginx kurulumunu paylaşırken ayarlarını, sertifikalarını ve hizmetlerini bağımsız yönetebilirler. **TWPM, desteklenen diğer Nginx yapılandırmalarıyla da çalışır**; 3X-UI kurulumu zorunlu değildir.

## ✨ Özellikler

| | |
| --- | --- |
| **Tam kapsamlı kamuflaj sitesi**<br>Üç özgün tema, birden çok sayfa, çalışan gezinme bağlantıları, görseller ve mobil uyumlu tasarım. | **Her kuruluma özel görünüm**<br>Site oluşturulurken adlar, renkler, metinler ve görseller belirlenir. |
| **Nginx üzerinden HTTPS**<br>Ayrı alan adı, Let's Encrypt, SNI yönlendirmesi ve TCP/443 üzerinde diğer hizmetlerle birlikte çalışma. | **3X-UI AUTO NGINX entegrasyonu**<br>Telegram proxy'sini diğer projenin menüsünden mevcut bağlantılarını değiştirmeden kurun veya açın. |
| **Güvenli Telemt güncellemeleri**<br>Resmî sürümlerin bulunması, kaynak ve çalışırlık doğrulaması, önceki çalışan sürümün korunması. | **Mevcut kurulum korunur**<br>Olağan bakımda ayarlar, anahtarlar, veriler, sertifikalar ve site değiştirilmez. |
| **Doğrudan bağlantı veya SOCKS5**<br>VPS'in Telegram sunucularına doğrudan erişemediği durumlarda bağlantı yolunu seçin. | **Kolay yönetim**<br>Kurulum, güncelleme, kontrol, onarım, bağlantı gösterme ve kaldırma için Rusça ve İngilizce menü. |

<a id="quick-start"></a>

## 🚀 Hızlı başlangıç

**Ubuntu 24.04 veya 26.04** yüklü bir **VPS**, **root** erişimi, desteklenen SNI yapılandırmasına sahip çalışan Nginx ve **ayrı bir alan adı veya alt alan adı** gerekir. DNS A kaydı VPS'in genel IPv4 adresine işaret etmelidir. HTTPS sertifikası için TCP/80, proxy bağlantıları için TCP/443 dışarıdan erişilebilir olmalıdır.

> [!IMPORTANT]
> Telegram proxy alan adı **başka bir yerde kullanılmıyor** olmalıdır. 3X-UI panelinin, REALITY'nin, Vision'ın veya mevcut başka bir Nginx sitesinin alan adını kullanmayın.

**3X-UI AUTO NGINX zaten kuruluysa**, ana menüsünü açıp **4 — Telegram Web Proxy Manager** seçeneğini kullanın. Buradan TWPM'yi kurabilir veya mevcut kurulumu başlatabilirsiniz.

**Bağımsız kurulum için**, desteklenen Nginx bulunan VPS'te root olarak çalıştırın:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xPROMSx/telegram-web-proxy-manager/main/install.sh)
```

Başlangıçta **1 — English** veya **2 — Русский** seçin. Yöneticinin arayüzü şu anda yalnızca İngilizce ve Rusçadır. Ardından ana menü açılır (aşağıda İngilizce arayüzdeki gerçek seçenek adları yer alır):

- **1 — Install Telegram proxy:** yeni kurulum veya mevcut kurulumu yeniden yüklemeden kontrol etme.
- **2 — Update Telemt:** proxy motorunun güncellemelerini kontrol edip güvenle yükleme.
- **3 — Check status:** ayarları değiştirmeden çalışırlığı kontrol etme.
- **4 — Check and restart services:** yapılandırmayı doğrulama, Telemt'yi yeniden başlatma ve Nginx'i yeniden yükleme.
- **5 — Show connection link:** Telegram proxy bağlantısını tekrar gösterme.
- **6 — Uninstall Telegram proxy:** onaydan sonra yönetilen kurulumu kaldırma.
- **0 — Exit:** çıkış.

İlk kurulum için **1 — Install Telegram proxy** seçeneğini seçin. Yönetici sırasıyla şunları sorar:

1. **WEB proxy domain (WEB proxy alan adı).** Önceden hazırladığınız, henüz kullanılmayan ayrı alan adını veya alt alan adını girin.
2. **Public IPv4 (genel IPv4).** Yönetici VPS'in IP adresini otomatik olarak bulmaya çalışır. Görüntülenen adresi sunucunun IPv4 adresi ve alan adının DNS A kaydıyla karşılaştırın. Doğruysa yalnızca **Enter** tuşuna basın. Tespit başarısızsa veya adres yanlışsa doğru adresi elle yazın.
3. **Use SOCKS5 upstream? [y/N] (SOCKS5 kullanılsın mı?)** SOCKS5, VPS'in Telegram sunucularına erişmek için kullanabileceği isteğe bağlı bir aracı proxy'dir. **VPS'iniz Telegram'a doğrudan bağlanabiliyorsa SOCKS5 gerekmez: Enter'a basın veya N seçin.** Doğrudan erişim yoksa, *kurulumdan önce* çalışan bir SOCKS5 proxy yapılandırın; ardından **Y** seçip sunucu adresini ve portunu girin. **SOCKS5'in ne olduğunu bilmiyor musunuz? N seçin.**

Kurulumun sonunda yönetici HTTPS ve kamuflaj sitesini hazırlar, Telegram'a proxy eklemek için `tg://webproxy?...` biçiminde hazır bir bağlantı gösterir.

Daha sonra yönetmek için:

```bash
telegram-web-proxy-manager
```

> [!CAUTION]
> Telegram bağlantısı proxy'nizin özel erişim anahtarını içerir. Bağlantıyı yayımlamayın veya başkalarıyla paylaşmayın.

## 🌐 Kamuflaj siteleri ve Nginx

**Basit bir yer tutucu yerine eksiksiz bir web sitesi.** Her yeni kurulumda TWPM üç özgün tasarımdan birini otomatik oluşturur:

- **Botanical Journal** — bitkiler hakkında bir dergi.
- **Night Sky Guide** — gece gökyüzü rehberi.
- **Home Kitchen** — ev yemekleri sitesi.

Her tasarımda farklı sayfalar, stiller ve görseller içeren **11 yerel dosya** bulunur. Site mobil cihazlara uygundur, dış kaynaklara ihtiyaç duymaz ve kendine özgü bir görünüme kavuşur. Tasarım güncellemelerde ve bakımda korunur; eski kurulumlardaki siteler değiştirilmez.

**Site ve proxy mevcut Nginx üzerinden çalışır.** Docker veya ek bir web sunucusu gerekmez.

## 🤝 3X-UI AUTO NGINX ile entegrasyon

**İki bağımsız proje, uyumlu bir altyapı.** [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx), 3X-UI/Xray'i ve paylaşılan Nginx yapılandırmasını kurup yönetir. **Telegram Web Proxy Manager** desteklenen Nginx yönlendirmesini ve kendi alan adını kullanarak ayrı bir Telegram WEB proxy ekler.

- **Önerilen kurulum sırası:** önce 3X-UI AUTO NGINX, sonra TWPM. Nginx'i ilk proje kurar; TWPM kurmaz.
- **TCP/443 paylaşımı:** SNI yönlendirmesi, mevcut 3X-UI yollarını değiştirmeden hizmetlerin aynı VPS üzerinde çalışmasını sağlar.
- **Bağımsız bakım:** TWPM kendi Telemt hizmetini, sitesini ve sertifikalarını yönetir; 3X-UI ayarlarının veya verilerinin kontrolünü devralmaz.
- **Backup v3 uyumluluğu:** güncel 3X-UI AUTO NGINX, TWPM'nin standart yapılandırmalarını tanır. Ancak 3X-UI yedeği **Telemt'nin kendi verilerinin ayrı yedeğinin yerini tutmaz**.

**Diğer Nginx yapılandırmaları da desteklenir**, ancak TWPM'nin tanıdığı stream/SNI düzenleriyle eşleşmelidir; bunlara ayrı `include` dosyaları kullanan bazı düzenler de dahildir. Yönetici rastgele Nginx yapılandırmalarını dönüştürmez; bilinmeyen veya çakışan düzenleri güvenli biçimde reddeder. [Teknik gereksinimler](docs/OPERATIONS.md#nginx-requirements).

> [!IMPORTANT]
> TWPM **Ubuntu 24.04 ve 26.04** sürümlerini destekler. 3X-UI AUTO NGINX'in Debian desteği, Telegram Web Proxy Manager'ın da Debian'ı desteklediği anlamına gelmez.

## 🔄 Güncellemeler ve bakım

İlk kurulumda yönetici doğrulanmış bir Telemt sürümü yükler. **Universal Update**, en yeni uyumlu resmî kararlı sürümü bağımsız olarak bulur ve geçişten önce doğrular. Güncelleme başarısız olursa önceki çalışan sürüme dönüş ve mevcut durumun korunması için mekanizma bulunur.

**TWPM'nin kendisini** güncellemek ve **Telemt'yi** güncellemek iki ayrı işlemdir. Olağan bakım siteyi yeniden oluşturmaz, gizli anahtarları sıfırlamaz veya eski kurulumları onay alınmadan yeni bir düzene taşımaz.

Durum kontrolü menüden yapılabilir; gerektiğinde desteklenen kurulumlar onarılabilir. Kaldırma yalnızca yöneticinin sahipliği doğrulanmış öğeleri etkiler; sertifikaların silinmesi için ayrıca onay gerekir.

## ⚙️ Gereksinimler ve testler

- **İşletim sistemi:** Ubuntu 24.04 / 26.04, x86_64 veya ARM64; root ve systemd.
- **Ağ:** ayrı alan adı veya alt alan adı, doğru DNS A kaydı ve gerekli TCP portlarına erişim.
- **Nginx:** önceden mevcut, desteklenen stream/SNI yapılandırması. Yönetici Nginx, 3X-UI veya Xray kurmaz ve sistem güvenlik duvarı kurallarını değiştirmez.
- **Telemt:** TWPM tarafından kurulur; yeni kurulumun doğrulanmış temel sürümü **3.5.16**'dır ve Universal Update ayrı çalışır.

Proje desteklenen Ubuntu sürümlerinde, gerçek Nginx ve Telemt kontrolleri dahil otomatik ve entegrasyon testlerinden geçer. Standart dışı Nginx yapılandırmaları ayrıca uyumluluk kontrolü gerektirir. [Test kapsamı ve sınırları](docs/CI-COVERAGE.md).

## 📖 Belgeler

- [İşletim, Nginx uyumluluğu ve kurtarma](docs/OPERATIONS.md)
- [Test kapsamı ve sınırlamalar](docs/CI-COVERAGE.md)
- [Telemt kaynakları ve güncelleme güvenliği](docs/UPSTREAM.md)
- [GPL-3.0 Lisansı](LICENSE)

## 💬 Topluluk ve geri bildirim

xPROMSx projelerinin haberlerini [@promsdev Telegram kanalından](https://t.me/promsdev) takip edin. Sorularınızı ve önerilerinizi [kanala mesaj göndererek](https://t.me/promsdev?direct) iletebilir, hataları [GitHub Issues](https://github.com/xPROMSx/telegram-web-proxy-manager/issues) üzerinden bildirebilirsiniz.

<a id="support-development"></a>

## ❤️ Geliştirmeyi destekleyin

Telegram Web Proxy Manager ücretsizdir ve herkesin kullanımına açıktır. Projeyi faydalı buluyorsanız [geliştirilmesini gönüllü olarak destekleyebilirsiniz](docs/SUPPORT_TR.md). Bağış yapmak herhangi bir özelliğe erişimi etkilemez.

<div align="center">

**Kendi Telegram proxy'niz. Güvenli HTTPS. Tam kapsamlı kamuflaj sitesi.**

⭐ Projeyi yararlı bulduysanız [Star verin](https://github.com/xPROMSx/telegram-web-proxy-manager). Böylece başkalarının da projeyi keşfetmesine yardımcı olursunuz.

[Kurulum](#-hızlı-başlangıç) · [Sürümler](https://github.com/xPROMSx/telegram-web-proxy-manager/releases) · [Sorunlar](https://github.com/xPROMSx/telegram-web-proxy-manager/issues)

</div>
