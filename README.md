# ✈️ Telemt WEB Manager

**Telegram WEB proxy на своём VPS — установка, HTTPS, безопасные обновления
с rollback и Automatic Fake Site.**

[![checks](https://github.com/xPROMSx/telemt-web-manager/actions/workflows/checks.yml/badge.svg)](https://github.com/xPROMSx/telemt-web-manager/actions/workflows/checks.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20%7C%2026.04-E95420?logo=ubuntu&logoColor=white)
[![Release](https://img.shields.io/github/v/release/xPROMSx/telemt-web-manager)](https://github.com/xPROMSx/telemt-web-manager/releases/latest)

[English](README.en.md) · [Releases](https://github.com/xPROMSx/telemt-web-manager/releases) · [3x-ui Auto Nginx](https://github.com/xPROMSx/3x-ui-auto-nginx) · [Issues](https://github.com/xPROMSx/telemt-web-manager/issues)

## ⚡ Быстрый старт

Подготовь Ubuntu VPS с существующей поддерживаемой схемой Nginx — например,
через Fresh Install **3x-ui Auto Nginx**. Затем выполни в root-консоли:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xPROMSx/telemt-web-manager/main/install.sh)
```

Выбери **1. Install**, укажи домен и публичный IPv4, получи WEB-ссылку.
Cover page выбирается автоматически. Bootstrap устанавливает опубликованный
релиз менеджера; Telemt устанавливается отдельным действием Install.

## Что внутри

- ⚡ Установка менеджера одной командой; недостающие Ubuntu tools — только после Y/y.
- ✈️ [Telemt WEB Proxy](https://github.com/telemt/telemt): прямой выход или SOCKS5.
- 🔄 Universal Update: проверенный стабильный официальный кандидат, TOML сохраняется.
- 🛟 Автоматический rollback/recovery с восстановлением бинарника и полного DATA.
- 🥸 Automatic Fake Site и смена cover из меню — без внешних ресурсов.
- 🔐 HTTPS / Let's Encrypt с сохранением и повторным использованием сертификата.
- 🌐 Интеграция в существующий Nginx SNI router на общем порту 443.
- 🔧 Check / Repair / managed Uninstall и приватный показ текущей WEB-ссылки.

## 🚀 Нужен полноценный proxy stack?

### [3x-ui Auto Nginx](https://github.com/xPROMSx/3x-ui-auto-nginx)

Companion-проект разворачивает **3x-ui / Xray / Nginx / TLS / Fake Site**.
Telemt WEB Manager добавляет управляемый Telegram WEB proxy, сохраняя
распознанные маршруты и настройки существующего stack.

**Рекомендуемый порядок: 3x-ui Fresh Install → Telemt Install.**
Один установщик не запускает другой; runtime-зависимости между repositories нет.
Повторный destructive `x-ui-latest.sh` пересоздаёт Nginx: после намеренного полного
rebuild Telemt требуется установить/интегрировать заново.

## Меню менеджера 1.0.0

```text
1. Install
2. Update
3. Check
4. Repair
5. Show current WEB link
6. Change cover site
7. Uninstall Telemt
8. Exit
```

**WEB-ссылка — bearer secret.** После успешного интерактивного Install она
показывается только после commit. Пункт 5 читает существующую manager-owned ссылку,
проверяет её соответствие TOML и ничего не регенерирует/не ремонтирует.
Приватный файл: `/var/lib/telemt-web-manager/web-link.txt` (root, 0600).
CLI Install и redirected/unattended output секрет не печатают. `NO_COLOR`
отключает цвета; `TERM=dumb` включает простой вывод.

**Change cover site** предлагает Random new cover, Restore Service Status или Cancel.
При наличии вариантов random отличается от текущего сайта. HTML меняется атомарно;
Telemt кеширует static assets, поэтому выполняется проверенный restart.
Неизвестный/изменённый HTML требует manual review и не перезаписывается.
Cover — обычная decoy page, без обещаний невидимости трафика или обхода DPI.
Выбранный сайт сохраняется при Telemt Update.

**Update** показывает стадии и прогресс stability/restart проверки в TTY.
Acceptance остаётся 150 + 45 секунд. В CI/redirected output сохраняются диагностические
строки; ошибки и информация об откате не скрываются.

**Uninstall** требует ввода `UNINSTALL`, удаляет только доказанно manager-owned Telemt.
Менеджер и backups остаются. Сертификат сохраняется по умолчанию; Install того же
домена повторно использует валидное manager-owned certificate state без нового ACME order.
Удаление сертификата — отдельное явное подтверждение.

## Команды без диалога

```bash
telemt-web-manager --install --domain proxy.example.com --public-ip 203.0.113.10
# При необходимости: --socks 127.0.0.1:1080
# Для нового сертификата: --email operator@example.com --agree-tos
telemt-web-manager --update
telemt-web-manager --check
telemt-web-manager --repair
telemt-web-manager --uninstall --confirm-uninstall
# Явно удалить и управляемый сертификат:
telemt-web-manager --uninstall --confirm-uninstall --delete-certificate
```

CLI никогда автоматически не устанавливает пакеты. Для обновления **менеджера**
повтори bootstrap: он атомарно устанавливает manager/helper из одного release commit,
сохраняя Telemt. Автоматическое понижение версии запрещено.

## Требования и границы

Supported Telemt: **3.5.12** — baseline Fresh Install. Update выбирает новейший
стабильный официальный релиз и проверяет совместимость, без TOML migration и downgrade.

Ubuntu **24.04 / 26.04**, root, Bash 5+, активный systemd и поддерживаемый существующий
Nginx `stream` / `ssl_preread` / PROXY protocol обязательны. Для домена нужна одна
правильная A-запись, без CNAME/AAAA; локальные Telemt порты должны быть свободны.
Поддерживаются GNU x86_64/aarch64 binaries; native ARM systemd live acceptance не заявляется.
Conntrack требует `CAP_NET_ADMIN`. Менеджер не provisioning-система и не устанавливает
Nginx/Xray/3x-ui, не настраивает firewall и не принимает чужой Telemt под управление.
Неизвестные схемы/небезопасные пути вызывают отказ. Не публикуй конфиги, журналы и backups.

История owner acceptance: v0.1.1 — Install/recovery; v0.1.2 — Uninstall/certificate;
v0.1.3 — Update 3.5.11 → 3.5.12; v0.1.4 — WEB-link/dependency UX. Архитектура
Universal Update также прошла owner live acceptance, включая 3.5.12 → 3.5.14,
Telegram и финальный Check OK. Новые cover/UI функции 1.0.0 требуют отдельной приёмки
перед публикацией. CI не подтверждает все серверы и конфигурации.

## Документация

[Operations / требования / восстановление](docs/OPERATIONS.md) ·
[Update, rollback и security model](docs/OPERATIONS.md#universal-update-020) ·
[CI coverage и ограничения](docs/CI-COVERAGE.md) ·
[Upstream provenance](docs/UPSTREAM.md) · [MIT License](LICENSE)
