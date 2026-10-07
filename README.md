# ✈️ Telegram Web Proxy Manager

**Свой Telegram WEB Proxy на Ubuntu VPS за одну команду.**
HTTPS, готовая ссылка `tg://webproxy?...` для Telegram и автоматически выбранная
Fake-Site страница на домене. Менеджер проверяет обновления и при ошибке возвращает
рабочую версию с её данными. Если с VPS нет прямого доступа к Telegram, используй SOCKS5.

[![checks](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml/badge.svg)](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20%7C%2026.04-E95420?logo=ubuntu&logoColor=white)
[![Release](https://img.shields.io/github/v/release/xPROMSx/telegram-web-proxy-manager)](https://github.com/xPROMSx/telegram-web-proxy-manager/releases/latest)

[English](README.en.md) · [Releases](https://github.com/xPROMSx/telegram-web-proxy-manager/releases) · [3x-ui Auto Nginx](https://github.com/xPROMSx/3x-ui-auto-nginx) · [Issues](https://github.com/xPROMSx/telegram-web-proxy-manager/issues)

## ✨ Что умеет

- ✈️ Устанавливает и настраивает свой Telegram WEB Proxy.
- 🔐 Подключает HTTPS с Let's Encrypt; сохранённый сертификат менеджера можно использовать повторно.
- 🥸 Автоматически показывает на домене Fake-Site страницу вместо технического ответа прокси.
- 🎨 Меняет Fake-Site из меню или возвращает нейтральную страницу Service Status.
- 🔄 Находит новые стабильные версии движка прокси и проверяет их совместимость перед установкой.
- 🛟 Если обновление не проходит проверку, автоматически возвращает рабочую версию и её данные.
- 🔧 Одной командой проверяет прокси, Nginx, HTTPS и подключение.
- 🌐 Работает напрямую или через SOCKS5, если с VPS нет прямого доступа к Telegram.

## ⚡ Быстрый старт

Нужен Ubuntu VPS с поддерживаемой настройкой Nginx. Подготовить сервер поможет
**3x-ui Auto Nginx** — о нём ниже. В консоли root выполни:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xPROMSx/telegram-web-proxy-manager/main/install.sh)
```

До ручного переименования GitHub repository используй ту же команду с адресом
`https://raw.githubusercontent.com/xPROMSx/telemt-web-manager/main/install.sh`.
Bootstrap проверяет официальный repository и работает до и после переименования.

Команда устанавливает опубликованную версию менеджера и открывает меню.
Позже открыть меню можно командой `telegram-web-proxy-manager`;
прежняя `telemt-web-manager` продолжает работать.
Выбери **1. Install**: менеджер спросит домен, публичный IPv4 и нужен ли SOCKS5.
Если сертификата ещё нет, менеджер также попросит e-mail и подтверждение условий Let's Encrypt.

После установки ты получишь готовую ссылку вида `tg://webproxy?...` для добавления
прокси в Telegram. На указанном домене одновременно будет работать автоматически
выбранная Fake-Site страница, которую можно менять через меню.

## 🖥️ Нужен готовый сервер с 3x-ui и Xray?

Для подготовки VPS можно использовать наш второй проект —
[**3x-ui Auto Nginx**](https://github.com/xPROMSx/3x-ui-auto-nginx).
Он настраивает **3x-ui, Xray, Nginx и HTTPS**. Telegram Web Proxy Manager отдельной
установкой добавляет Telegram WEB Proxy на тот же сервер.

**Рекомендуемый порядок:**

1. 3x-ui Auto Nginx.
2. Telegram Web Proxy Manager.

Оба проекта работают независимо: один установщик не запускает другой.
После полной переустановки 3x-ui Telegram-прокси нужно подключить заново — см. документацию ниже.

## Меню менеджера 1.1.0

```text
1. Install
2. Update
3. Check
4. Repair
5. Show current WEB link
6. Change cover site
7. Uninstall Telegram proxy
8. Exit
```

**Ссылка для подключения содержит секретный ключ доступа к прокси.** Не публикуй её
и не передавай посторонним. Пункт 5 показывает проверенную сохранённую ссылку,
не создавая новую и не меняя настройки. Файл:
`/var/lib/telemt-web-manager/web-link.txt` (root, права `0600`). При установке из меню
ссылка появляется после успеха; команды без диалога и вывод в файл её не печатают.

**Change cover site** выбирает другую случайную Fake-Site страницу или возвращает
Service Status. Все страницы локальные, без внешних CDN и ресурсов, и сохраняются
после обновления Telemt. Изменённый вручную HTML не перезаписывается.

**Update** проверяет новую стабильную версию и показывает прогресс установки.
При проблеме возвращает рабочую версию.
`NO_COLOR` отключает цвета; `TERM=dumb` оставляет простой текстовый вывод.

**Uninstall Telegram proxy** требует ввода `UNINSTALL` и удаляет только прокси, установленный
этим менеджером. Менеджер и резервные копии остаются. Сертификат по умолчанию
сохраняется для того же домена; удаление требует отдельного подтверждения.

## Команды без диалога

```bash
telegram-web-proxy-manager --install --domain proxy.example.com --public-ip 203.0.113.10
# При необходимости: --socks 127.0.0.1:1080
# Для нового сертификата: --email operator@example.com --agree-tos
telegram-web-proxy-manager --update
telegram-web-proxy-manager --check
telegram-web-proxy-manager --repair
telegram-web-proxy-manager --uninstall --confirm-uninstall
# Явно удалить и управляемый сертификат:
telegram-web-proxy-manager --uninstall --confirm-uninstall --delete-certificate
```

Команды без диалога не устанавливают пакеты. В меню недостающие инструменты Ubuntu
устанавливаются только после ответа `Y/y`. Сам **менеджер** обновляется повторным
запуском команды быстрого старта; Telemt остаётся установленным.
Автоматического понижения версии нет.

## Движок прокси

Telegram Web Proxy Manager использует [Telemt](https://github.com/telemt/telemt)
как движок прокси. Отдельно устанавливать Telemt или вручную настраивать его не нужно.
Внутренние пути с прежним именем `telemt-web-manager` сохраняются для совместимости
с существующими установками.

## Требования

- Ubuntu **24.04 / 26.04**, права root, Bash 5+ и работающий systemd.
- Уже настроенный Nginx с поддерживаемой конфигурацией `stream`, `ssl_preread` и PROXY protocol.
- Одна корректная DNS A-запись домена на публичный IPv4 сервера, без CNAME и AAAA.
- Свободные локальные порты Telemt: `127.0.0.1:18080` и `127.0.0.1:7444`.
- На реальном сервере проверена архитектура x86_64. ARM64/aarch64 в реальной эксплуатации не тестировался.

Для первой установки используется Telemt **3.5.12**. При обновлении менеджер выбирает
новейший стабильный официальный выпуск и проверяет его совместимость, сохраняя настройки.
Менеджер не устанавливает Nginx/Xray/3x-ui, не настраивает сетевой экран автоматически
и не управляет вручную установленным Telemt. Подробные условия — в документации.

## Проверено на реальном сервере

Версия 1.0.0 проверена на Ubuntu 26.04 x86_64 VPS после установки 3x-ui Auto Nginx:
первая установка, HTTPS, SOCKS5, Telegram, Fake-Site, смена страниц и обновление
Telemt **3.5.12 → 3.5.14** прошли успешно. Финальная проверка — **OK**.

## Документация

[Эксплуатация, требования и восстановление](docs/OPERATIONS.md) ·
[Безопасное обновление и возврат рабочей версии](docs/OPERATIONS.md#universal-update-020) ·
[Проверки и ограничения](docs/CI-COVERAGE.md) ·
[Источники и проверка выпусков Telemt](docs/UPSTREAM.md) · [Лицензия MIT](LICENSE)
