# Telemt WEB Manager

[English](README.md) | Русский

Ориентированный на безопасность Bash-менеджер для установки, обновления,
проверки и восстановления WEB Proxy на базе
[Telemt](https://github.com/telemt/telemt) за Nginx.

Проект рассчитан в том числе на VPS, где порт 443 используется несколькими
сервисами и распределяется через Nginx `stream` / `ssl_preread` по SNI.
Независимый open-source проект под MIT.

Версия менеджера: `0.1.0`. Исследованный upstream: **3.5.9**.
Подробные источники и архитектурные решения: [docs/UPSTREAM.md](docs/UPSTREAM.md).

## Возможности

- Интерактивная установка, обновление, проверка и восстановление
- Telemt WEB Proxy за HTTPS/Nginx
- Опциональная маршрутизация через SOCKS5
- Безопасная интеграция в распознанную существующую SNI-схему
- Проверка целостности загружаемых релизов
- Проверка конфигурации новой версией до обновления
- Автоматический откат при неудачном обновлении
- Проверка реальной готовности вместо фиксированных задержек
- Консервативное fail-closed поведение
- Hardening systemd с минимально необходимыми capabilities
- Автоматические regression tests и GitHub Actions

## Проверенная совместимость

Протестированы полные sanitized конфигурации, которые создают текущие
`x-ui-latest.sh` и `x-ui-patch.sh` из
[`mozaroc/3x-ui-pro`](https://github.com/mozaroc/3x-ui-pro), revision
`a2c430cd6dec7c86d873dcda3544a61e7ac41144`.
Менеджер распознаёт эту схему Nginx `stream` / `ssl_preread` и добавляет Telemt,
не изменяя существующую маршрутизацию Xray и 3x-ui. CI использует настоящий
Nginx; установка/Certbot/systemd проверяются mocks. Live VPS acceptance ещё не
выполнялся. Это не гарантия поддержки произвольных или будущих конфигураций.

> Telemt WEB Manager является независимым проектом, не является частью
> Telemt, 3x-ui или 3x-ui-pro, не аффилирован с ними и не имеет их endorsement.

## Что менеджер намеренно не делает

- Не переписывает неизвестные схемы Nginx
- Не изменяет базу данных 3x-ui или маршрутизацию Xray
- Не меняет firewall/UFW
- Не угадывает миграции конфигурации
- Не захватывает произвольные существующие установки Telemt автоматически
- Не игнорирует ошибки validation ради завершения установки

## Поддерживаемая область

- Ubuntu 24.04 / 26.04, Bash 5+, systemd; x86_64 и aarch64 (arm64).
- Nginx с HTTP SSL, HTTP/2, realip, stream и ssl_preread modules.
- Один распознаваемый SNI-router: IPv4 `:443` и optional существующий `[::]:443`,
  `proxy_protocol on` уже включён. Проверена конфигурация обоих скриптов
  `mozaroc/3x-ui-pro` на commit, указанном в upstream notes.
- Отдельный TLS frontend `127.0.0.1:7444`, Telemt `127.0.0.1:18080`.
- Python 3.11+ используется только для строгого разбора TOML/Nginx и диагностики;
  bounded archive extraction и проверки путей; внешние Python-пакеты не нужны.
  Оркестрация и транзакции написаны на Bash.

```text
Telegram WEB -> HTTPS :443 -> Nginx stream/SNI
             -> PROXY + TLS 127.0.0.1:7444
             -> HTTP/1.1 127.0.0.1:18080 -> Telemt
             -> direct или SOCKS5 -> Telegram DC
```

Скрипт отказывает при неизвестной топологии, изменённом managed vhost, service
drop-ins, TOML includes или неоднозначных адресах. Отказ не является разрешением
упростить защиту или переписать существующий конфиг.

## Получение и установка менеджера

Работайте в root shell на тестовом VPS. `sudo` внутри менеджера не используется.
Не запускайте код напрямую через `curl | bash`.

```bash
git clone https://github.com/xPROMSx/telemt-web-manager.git
cd telemt-web-manager
# До merge первая реализация находится в work/initial-telemt-manager.
git switch work/initial-telemt-manager
git log --oneline -5
less telemt-web-manager.sh
less lib/safety.py
bash -n telemt-web-manager.sh
shellcheck telemt-web-manager.sh
sha256sum telemt-web-manager.sh lib/safety.py
# Если опубликованы контрольные суммы выбранного выпуска, сравните с ними.
# Собственный sha256sum фиксирует скачанные байты, но не подтверждает автора.
install -d -m 0755 /opt/telemt-web-manager/lib
install -m 0755 telemt-web-manager.sh /opt/telemt-web-manager/
install -m 0644 lib/safety.py /opt/telemt-web-manager/lib/
/opt/telemt-web-manager/telemt-web-manager.sh --help
```

Не переносите только `.sh`: нужен соседний `lib/safety.py`. Каталог установленного
менеджера должен принадлежать root и не быть доступен другим пользователям на запись.
MIT LICENSE сохранена без изменений.

Установите зависимости самостоятельно, не заменяя вслепую действующий Nginx:

```bash
apt-get update
apt-get install bash python3 curl ca-certificates tar openssl jq dnsutils \
  util-linux iproute2 coreutils passwd certbot iptables nftables
```

Для чистого Nginx пакет stream обычно предоставляется `libnginx-mod-stream`.
Согласуйте установку модулей с текущим пакетом Nginx и проверьте `nginx -t`.
Скрипт только проверяет зависимости, сам `apt` не запускает.

## Fresh install

Перед установкой настройте DNS A на IPv4 сервера. Менеджер требует ровно один
совпадающий A и отдельно запрашивает настоящую AAAA через DNS. CNAME, несколько A,
AAAA и IPv4-mapped AAAA требуют ручной проверки. `getent` для определения AAAA
не используется. В примерах ниже адрес TEST-NET и домен-заглушка: замените их.

```bash
/opt/telemt-web-manager/telemt-web-manager.sh --install \
  --domain proxy.example.com --public-ip 203.0.113.10
```

Без аргументов открывается меню Install / Update / Check / Repair / Exit.
Интерактивная установка спрашивает домен, публичный IPv4 и optional SOCKS.
Без TTY недостающие параметры приводят к отказу, а не ожиданию ввода.

Порядок: проверка DNS/портов/Nginx, план изменений, latest stable, загрузка и
официальный SHA256, сертификат, backup, пользователь `telemt`, private config,
candidate healthcheck, systemd, bounded readiness, Nginx validation/reload,
локальный decoy, полный локальный SNI/TLS путь, публичный HTTPS и свежие логи.

Создаются:

| Путь | Назначение |
| --- | --- |
| `/usr/local/bin/telemt` | Проверенный upstream binary |
| `/etc/telemt/telemt.toml` | root:telemt, 0640; API выключен |
| `/etc/systemd/system/telemt.service` | Hardened unit |
| `/var/lib/telemt/public/index.html` | Root-owned static decoy, 0440 |
| `/var/lib/telemt/state/` | Единственный writable state directory сервиса |
| `/var/lib/telemt-web-manager/manifest.json` | Root-only сведения о managed installation |
| `/var/lib/telemt-web-manager/web-link.txt` | `tg://webproxy` ссылка, 0600 |
| `/etc/nginx/conf.d/telemt-web-manager.conf` | Отдельный TLS frontend |
| `/etc/nginx/conf.d/telemt-web-manager-acme.conf` | Persistent HTTP-01 vhost, только для webroot flow |
| `/var/lib/telemt-web-manager-acme/` | Root-owned ACME webroot и ownership marker, только для webroot flow |
| `/etc/letsencrypt/renewal-hooks/deploy/telemt-web-manager` | Validation/reload Nginx после успешного renewal |

Secret генерируется `openssl rand -hex 16`. Менеджер не печатает его и сохраняет
ссылку в private файл. Upstream link logging в journald остаётся разрешённым.
Не публикуйте этот файл, конфигурацию, полные журналы или backups.

## Требования к Nginx

Менеджер разбирает дерево include-файлов, а не делает поиск/замену по regex.
Распознаваемый пример stream-контекста:

```nginx
map $ssl_preread_server_name $sni_name {
    hostnames;
    panel.example.com www;
    reality.example.com xray;
    default xray;
}
upstream xray { server 127.0.0.1:8443; }
upstream www { server 127.0.0.1:7443; }
server {
    proxy_protocol on;
    set_real_ip_from unix:;
    listen 443;
    listen [::]:443;
    proxy_pass $sni_name;
    ssl_preread on;
}
```

`http` должен непосредственно включать `conf.d/*.conf` (абсолютный или относительный
путь). Поддерживаются один stream/map/router, точные SNI имена, default route,
upstream selector и loopback frontend. Все существующие routes сохраняются.
Каждый named stream upstream должен содержать один простой loopback server;
дополнительные stream context directives и upstream options отвергаются.
`hostnames;` допускается один раз перед значениями, но SNI entries всё равно
должны быть точными именами. `set_real_ip_from unix:;` допускается только в
указанном виде; входящий PROXY protocol на публичном listener не допускается.
Общий HTTP snippet может включаться из нескольких vhosts. Обычные regex,
экранирование и `${variable}` в существующих HTTP directives сохраняются;
экранированные имена directives/include/listen и неоднозначный синтаксис отвергаются.
Повторная установка не дублирует mapping/upstream/vhost. Новые include-файлы или
изменение конфигов во время подготовки приводят к отказу.

Сложные regex/wildcard SNI maps, nested dynamic routing, несколько
router-серверов, нестандартные listen flags/адреса, custom `nginx -c/-p`, занятые private-порты и
direct HTTPS без stream-router в первой версии автоматически не настраиваются.
Скрипт не превращает неизвестную схему в этот пример.
Существующий `[::]:443` сохраняется, но IPv6 egress Telemt и новая AAAA-запись
для WEB-домена по-прежнему не включаются автоматически.

Frontend принимает PROXY только с loopback, формирует единственный X-Forwarded-For,
использует HTTP/1.1 к Telemt, отключает buffering/retries, устанавливает 90s
таймауты. Публичный HTTP/2 включён. Carrier фиксирован в `https`, поэтому WebSocket
Upgrade не включается. Access log отключён; error log vhost направлен в `/dev/null`,
чтобы URL с capability не попадали туда при ошибках. Это уменьшает детализацию
диагностики, но защищает bearer credentials.

## SOCKS5 и Telegram egress

```bash
/opt/telemt-web-manager/telemt-web-manager.sh --install \
  --domain proxy.example.com --public-ip 203.0.113.10 --socks 127.0.0.1:1080
```

Проверяется SOCKS handshake и проверяемое HTTPS-соединение с `api.telegram.org`
через SOCKS5h. Это проверка доступности Telegram, не доказательство географии
выхода и не полная проверка всех DC. Cloudflare trace не используется.
Xray/3x-ui не обязательны; их DB, конфиги, firewall и UFW менеджер не изменяет.
SOCKS authentication и IPv6 upstream оставлены ручной настройкой с review.

## TLS / Certbot

Существующий сертификат ищется в `/etc/letsencrypt/live/DOMAIN/`. Проверяются
hostname, срок более 7 дней, приватные permissions ключа, ownership, безопасные
Certbot symlinks в archive/DOMAIN и совпадение public key. TLS trust проверяется HTTP probes.
Для нового сертификата передайте `--email` и `--agree-tos`, явно принимая условия
ACME. При свободном 80 используется standalone HTTP-01, Nginx не останавливается.
Если 80 занят тем же проверенным Nginx master/workers, поддержан webroot flow
для распознанных HTTP redirect vhosts: `listen 80`, точные `server_name` и
`return 301 https://$host$request_uri`. Wildcard/regex names, custom HTTP routing,
conflicting domain или чужой процесс приводят к отказу.
Расхождение runtime/config по порту 80 тоже приводит к отказу: pending Nginx
конфигурация не должна нарушить renewal strategy standalone сертификата.

Перед mutation создаётся backup. Отдельный manager vhost обслуживает
`/.well-known/acme-challenge/` из root-owned webroot, остальные requests получают
404. После `nginx -t` и reload локальная probe проверяет отдачу challenge file.
Certbot выполняет `certonly --webroot --webroot-path`, сохраняет renewal settings;
менеджер проверяет certificate и renewal contract. Failure или signal откатывает
ACME-изменения и reload валидной старой конфигурации. Existing vhosts не меняются.
Успешная выдача отдельно фиксирует persistent vhost/webroot для renewal, даже если
дальнейшая установка Telemt не завершится. Пустые webroot directories после failure
могут остаться; осмотрите backup/marker перед повторной установкой.

Проверьте внешнюю доступность 80/443 самостоятельно. Firewall не меняется.
Новый cron/timer не создаётся. При отсутствии известного Certbot timer выдаётся
предупреждение: проверьте существующий cron/расписание. Deploy hook запускает
`nginx -t`, затем reload. Для standalone cert, если позже порт 80 занят, измените renewal
strategy вручную. Для обоих flows проверьте `certbot renew --dry-run` после
установки на тестовом VPS. Реальный ACME issuance в CI не выполняется.

## Обновление и откат

```bash
/opt/telemt-web-manager/telemt-web-manager.sh --update
```

Первый выпуск обновляет только распознанные manager-owned installations.
Существующий чужой Telemt нельзя автоматически перехватить: unit/config/topology
требуют review, даже если имя сервиса совпадает. Managed TOML можно редактировать,
но supported WEB contract должен сохраняться; неизвестные includes/схемы отвергаются.

При совпадении версии: `already up to date`, затем проверки состояния. Иначе:
проверенный новый candidate выполняет `healthcheck` **текущего файла**, затем
создаётся timestamped backup и бинарник атомарно заменяется. TOML сохраняется
byte-for-byte; Nginx, cert и unit во время binary update не меняются.
Автоматических TOML migrations нет. Ошибка validation останавливает обновление.
Аудит runtime/write paths выполнен только для 3.5.9. Если latest новее,
автоматическое обновление откажет до нового source audit/version gate, даже если
candidate мог бы принять TOML. Старые manager configs с quota path вне `state`
требуют ручного review; update не добавляет strict mode и не меняет paths.
Хеш TOML проверяется до/после candidate healthcheck и перед activation.

После restart менеджер до 90 секунд опрашивает systemd и реальный listener,
проверяет принадлежность порта PID Telemt, process UID/capabilities, decoy,
локальный полный TLS путь, публичный HTTPS, SOCKS и свежие журналы. Ошибка
возвращает старый binary и запускает старую версию. Если сам rollback неудачен,
выдаётся CRITICAL с путём backup. Возврат бинарника не восстанавливает TCP sessions.

Backups находятся в `/root/telemt-backups/TIMESTAMP.RANDOM/`, каталог 0700.
`files.tsv` сопоставляет номера копий и пути; `nginx-plan.json` хранит исходные
изменяемые Nginx-файлы и снимок хешей include-файлов. `nginx-snapshot/` содержит
копии полного прочитанного дерева конфигурации. Старые backups автоматически
не удаляются. Каталог содержит private TOML: резервируйте его как секрет.
SIGINT/TERM/HUP и обычные ошибки запускают rollback. SIGKILL, потеря питания и
сбой диска не могут быть обработаны Bash trap; понадобится ручное восстановление.

## Check и Repair

`--check` не меняет managed files/services: показывает версии, systemd state,
SubState/NRestarts, identity/capabilities, listener, результаты Nginx/HTTP/TLS,
срок сертификата, SOCKS и сводку ошибок последних 5 минут. Исходные строки
journald не печатаются. Для чтения system state требуются root-права; временные
private файлы диагностики удаляются. При недоступности GitHub latest неизвестен,
проверка завершается ненулевым кодом.
Check безопасно создаёт/open общий lock и получает shared flock, включая первый
запуск после reboot. Несколько checks разрешены; mutations получают exclusive
flock. Конфликт завершается немедленным отказом. Symlink/FIFO/hardlink и небезопасные
permissions lock отвергаются. Lock и временные файлы являются служебными записями
read-only диагностики; managed configuration/services не меняются.
Для managed webroot также сверяются persistent ACME vhost, marker и renewal settings.

`--repair` сверяет ownership manifest, хеши unit/vhost, топологию и config
healthcheck; делает backup, перезапускает Telemt и reload валидного Nginx.
Повреждённые/изменённые конфиги не реконструируются по догадке. Cert renewal,
неработающий Nginx и чужие unit/drop-ins требуют ручного review.

## Systemd и ограничения

`User=telemt`, `Group=telemt`, только `CAP_NET_ADMIN`; `NoNewPrivileges`,
`ProtectSystem=strict`, `ProtectHome`, private tmp/devices, защита kernel/control
groups, ограничения address families, realtime/SUID/namespaces, W^X и personality.
Ограничения: 65536 descriptors, 4096 tasks, MemoryMax=1G. Проверьте размер VPS
и нагрузку перед production. Изменение unit вне менеджера требует ручного review.

CAP_NET_ADMIN оставлен из-за upstream conntrack cleanup даже в tracked mode.
Известная ошибка missing-chain 3.5.9 классифицируется узко; все другие conntrack
errors считаются failures. Подробности и ссылки приведены в upstream notes.

Fresh TOML включает `general.config_strict = true`, `data_path = /var/lib/telemt`.
Активные beobachten и quota state явно находятся в `/var/lib/telemt/state`.
Пути unknown-DC log (file logging выключен), public-IP cache (поле не используется
проверенной реализацией probe), middle-proxy secret/config caches (middle proxy
выключен) и TLS-front cache (emulation выключена) тоже заданы внутри `state`.
File logging не включён: stderr попадает в journald. ReadWritePaths остаётся только
`/var/lib/telemt/state`, decoy и остальной DATA root-owned. Подробный audit table
есть в upstream notes; это source audit, а не runtime persistence test на VPS.

ExecStart с positional config сохранён: upstream default Run уже foreground,
без daemonization/PID file. systemd Type=simple напрямую контролирует процесс;
SIGTERM запускает graceful cleanup и quota save. TimeoutStopSec увеличен до 180s,
поскольку firewall helper commands могут ждать до 30s каждый. При превышении
systemd deadline процесс всё равно может быть убит до завершения persistence.

## Тесты

```bash
for file in telemt-web-manager.sh tests/*.sh; do bash -n "$file"; done
shellcheck -x telemt-web-manager.sh tests/*.sh
bash tests/run.sh
bash tests/fresh.sh
bash tests/download.sh  # Подмена download, неверный digest, symlink, redaction
bash tests/contracts.sh # Strict config, writable paths, unit
bash tests/locks.sh     # Shared/exclusive races, unsafe lock paths
bash tests/acme.sh      # Certbot mocks, refusal, rollback, renewal/idempotence
bash tests/upstream.sh  # Интернет: официальный release asset и SHA256
bash tests/nginx.sh     # Нужны nginx и libnginx-mod-stream; private test ports
bash tests/three-x-ui.sh # Интернет + Nginx: полные конфиги двух upstream-скриптов
```

Тесты не используют production credentials. Fixtures используют TEST-NET и
example.com. Secret генерируется только во временном окружении, не выводится.
CI выполняется на Ubuntu 24.04, включая настоящий Nginx stream/PROXY/TLS frontend
и проверку канонического X-Forwarded-For. Unit/fixture tests не подменяют live acceptance
на Ubuntu 26.04, arm64 и целевых клиентах Telegram.
Для 3x-ui-pro тест скачивает два скрипта с зафиксированного проверенного commit,
сверяет Git blob hashes и извлекает Nginx heredocs с безопасными example values.
Installer/patcher не исполняются. Проверяются full fresh-install orchestration
с mocks, повторный запуск, byte-for-byte rollback всех configs и настоящий
Nginx/TLS/PROXY/X-Forwarded-For по IPv4 и IPv6. Минимальная локальная fixture
отдельно проверяет отказ на небезопасных вариантах и include cycles.
Настоящий Nginx проверяет ACME challenge/404 и сохранение existing HTTP redirect.
Python tests покрывают traversal/hardlink/symlink/duplicate archives и опасные
ancestors; download ограничен 128 MiB, member size 128 MiB, extraction timeout 60s.
Разбор и snapshot проверки не блокируют внешнего root-редактора конфигурации:
не редактируйте configs параллельно установке. Symlink/write-permission checks
защищают от непривилегированных подмен; root administrator остаётся trust boundary.

## Ручное восстановление и удаление

Сначала сохраните private backup и откройте `files.tsv`. Остановите Telemt,
восстановите нужный binary с владельцем root и executable mode; TOML восстанавливайте
только осознанно из соответствующего backup (root:telemt, 0640). После восстановления
unit выполните `systemctl daemon-reload`. Перед reload Nginx всегда `nginx -t`.

Автоматического `--uninstall` нет. Для удаления сначала `systemctl disable --now
telemt.service`, затем вручную удалите только созданные manager files, его точную
SNI-строку и `twm_frontend` upstream, проверьте Nginx и reload. Не удаляйте чужие
routes, certs, x-ui DB, firewall rules или backups. Удаление аккаунта `telemt`
возможно только после проверки, что он больше ничем не используется.
Если certificate ещё нужен, сохраните persistent ACME vhost/webroot/renewal hook
либо сначала переведите renewal на другую challenge strategy. Их удаление может
нарушить renewal. Не удаляйте certificate автоматически.

После неудачного fresh install учётная запись, пустые каталоги и выпущенный
сертификат могут сохраняться намеренно. Менеджер не удаляет аккаунты/сертификаты
автоматически; осмотрите остатки и backup перед повторной установкой.
