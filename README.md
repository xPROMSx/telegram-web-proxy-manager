# Telegram Web Proxy Manager

**Свой Telegram-прокси на Ubuntu VPS без ручной настройки.**

Программа устанавливает и настраивает прокси, подключает HTTPS и создаёт
сайт-прикрытие для домена. Если обновление не проходит проверку,
программа возвращается к предыдущей рабочей версии.
Если сервер не имеет прямого доступа к Telegram, можно использовать SOCKS5.

[![checks](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml/badge.svg)](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20%7C%2026.04-E95420?logo=ubuntu&logoColor=white)
[![Release](https://img.shields.io/github/v/release/xPROMSx/telegram-web-proxy-manager)](https://github.com/xPROMSx/telegram-web-proxy-manager/releases/latest)

[English](README.en.md) · [Releases](https://github.com/xPROMSx/telegram-web-proxy-manager/releases) · [3x-ui Auto Nginx](https://github.com/xPROMSx/3x-ui-auto-nginx) · [Issues](https://github.com/xPROMSx/telegram-web-proxy-manager/issues)

## ✨ Возможности

- Установка и настройка Telegram-прокси одной командой.
- HTTPS с сертификатом Let's Encrypt.
- Сайт-прикрытие на домене.
- Безопасное обновление с возвратом к рабочей версии при ошибке.
- Прямое подключение к Telegram или работа через SOCKS5.
- Проверка состояния прокси и подключения.

## Быстрый старт

Нужны Ubuntu VPS, отдельный домен или поддомен с DNS A-записью на сервер
(не используемый в 3x-ui, включая REALITY, или другими сайтами Nginx), права root
и уже настроенный Nginx с совместимой конфигурацией.
Если сервер ещё не подготовлен, поможет 3x-ui Auto Nginx — о нём ниже.

Выполните от root:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xPROMSx/telegram-web-proxy-manager/main/install.sh)
```

Установщик откроет меню. Выберите **Install** и следуйте подсказкам.
После установки вы получите готовую ссылку вида `tg://webproxy?...`
для добавления прокси в Telegram. На домене будет доступен сайт-прикрытие.
В дальнейшем открыть менеджер можно командой `telegram-web-proxy-manager`.

**Ссылка для подключения содержит ключ доступа к вашему прокси — не публикуйте её.**

## Совместимость с 3x-ui Auto Nginx

Если на VPS нужен не только Telegram-прокси, но и 3x-ui с Xray,
используйте наш второй проект —
[3x-ui Auto Nginx](https://github.com/xPROMSx/3x-ui-auto-nginx).
Он подготавливает сервер и настраивает Nginx и HTTPS.

Сначала установите **3x-ui Auto Nginx**, затем **Telegram Web Proxy Manager**.
Проекты рассчитаны на совместную работу на одном VPS и управляются независимо.

## Что используется внутри

Движок прокси — [Telemt](https://github.com/telemt/telemt).
Менеджер автоматически устанавливает, настраивает и обновляет его,
поэтому отдельно разбираться с Telemt не требуется.

## Требования

- Ubuntu **24.04 или 26.04**.
- Права root.
- Отдельный домен или поддомен с DNS A-записью на публичный IPv4 VPS,
  не используемый в 3x-ui (включая REALITY) или другими сайтами Nginx.
- Уже настроенный Nginx с совместимой конфигурацией.

Полные требования и поддерживаемые конфигурации описаны в
[документации по эксплуатации](docs/OPERATIONS.md).

Проект проверяется автоматическими тестами и на реальном Ubuntu VPS.
Состав проверок и их ограничения — в [документации](docs/CI-COVERAGE.md).

## Документация

- [Эксплуатация и восстановление](docs/OPERATIONS.md)
- [Проверки и ограничения](docs/CI-COVERAGE.md)
- [Источники Telemt и проверка выпусков](docs/UPSTREAM.md)
- [Лицензия MIT](LICENSE)
