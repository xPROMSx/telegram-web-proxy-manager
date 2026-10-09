<div align="center">

🇷🇺 **Русский** · [🇬🇧 English](README.en.md) · [🇪🇬 العربية](README_AR.md) · [🇮🇷 فارسی](README_FA.md) · [🇨🇳 简体中文](README_ZH_CN.md) · [🇪🇸 Español](README_ES.md) · [🇹🇷 Türkçe](README_TR.md)

<h1 align="center"><img src="assets/branding/logo.png" alt="Telegram Web Proxy Manager" width="560"></h1>

### Свой Telegram-прокси на VPS без ручной настройки

**HTTPS · Сайт-прикрытие · SOCKS5 · Безопасные обновления**

Прямое подключение к серверам Telegram или работа через SOCKS5.

[![Проверки](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml/badge.svg)](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20%7C%2026.04-E95420?logo=ubuntu&logoColor=white)
[![Выпуск](https://img.shields.io/github/v/release/xPROMSx/telegram-web-proxy-manager)](https://github.com/xPROMSx/telegram-web-proxy-manager/releases/latest)

[Релизы](https://github.com/xPROMSx/telegram-web-proxy-manager/releases) · [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) · [Сообщить о проблеме](https://github.com/xPROMSx/telegram-web-proxy-manager/issues)

</div>

**Telegram Web Proxy Manager** устанавливает и настраивает современный Telegram WEB-прокси, обеспечивает подключение к нему по защищённому HTTPS и автоматически создаёт сайт-прикрытие для домена. Если VPS не имеет прямого доступа к Telegram, можно использовать SOCKS5-прокси.

При обновлении Telemt менеджер проверяет новую версию и в случае ошибки возвращает предыдущую рабочую версию.

**Совместимость:** полный набор интеграционных тестов включает проверку совместной работы с [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx). [Подробнее о проверках и их ограничениях](docs/CI-COVERAGE.md).

## ✨ Возможности

- Установка и настройка Telegram-прокси одной командой.
- Защищённый HTTPS с сертификатом Let's Encrypt.
- Автоматический сайт-прикрытие на домене.
- Безопасное обновление с возвратом к рабочей версии при ошибке.
- Прямое подключение к Telegram или работа через SOCKS5.
- Проверка состояния прокси и подключения.

## 🚀 Быстрый старт

Нужны VPS с **Ubuntu 24.04 или 26.04**, права **root**, уже работающий Nginx с совместимой конфигурацией и **отдельный домен или поддомен**, DNS A-запись которого указывает на публичный IPv4 сервера. Этот домен **не должен использоваться в 3X-UI (в том числе для REALITY) или других сайтах Nginx**.

Если сервер ещё не подготовлен, можно сначала установить [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx).

Запустите от root:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xPROMSx/telegram-web-proxy-manager/main/install.sh)
```

В открывшемся меню выберите **Install** и следуйте подсказкам. После установки менеджер покажет готовую ссылку вида `tg://webproxy?...` для добавления прокси в Telegram. По HTTPS на домене будет доступен сайт-прикрытие.

Для последующего управления используйте команду `telegram-web-proxy-manager`.

> **Важно:** ссылка содержит ключ доступа к прокси. Не публикуйте её.

## 🤝 Совместная работа с 3X-UI AUTO NGINX

Если на VPS также нужны **3X-UI** и Xray, используйте [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx): он подготавливает Nginx, HTTPS и конфигурацию 3X-UI.

**Порядок установки:** сначала 3X-UI AUTO NGINX, затем Telegram Web Proxy Manager. Проекты могут работать на одном VPS, но независимо управляют своими службами и сертификатами. Для Telegram требуется **собственный свободный домен или поддомен**.

## Что используется внутри

Основа прокси — [Telemt](https://github.com/telemt/telemt). Менеджер самостоятельно устанавливает, настраивает и обновляет его; отдельно устанавливать Telemt не нужно.

## Требования и проверки

- **Ubuntu 24.04 или 26.04**, права **root**.
- Отдельный домен или поддомен с DNS A-записью на публичный IPv4 VPS, не занятый в 3X-UI / REALITY или другом Nginx-сайте.
- Рабочий Nginx с [поддерживаемой конфигурацией](docs/OPERATIONS.md).

Проект проходит автоматические проверки, в том числе интеграционные испытания Nginx и совместимости с 3X-UI AUTO NGINX. Подробности и ограничения указаны в [описании тестирования](docs/CI-COVERAGE.md).

## Документация

- [Эксплуатация и восстановление](docs/OPERATIONS.md)
- [Проверки и ограничения](docs/CI-COVERAGE.md)
- [Источники Telemt и проверка выпусков](docs/UPSTREAM.md)
- [Лицензия GPL-3.0](LICENSE)
