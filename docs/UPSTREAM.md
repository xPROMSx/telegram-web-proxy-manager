# Исследование upstream

Проверено 30 сентября 2026 через официальный GitHub API и исходники.
`GET /repos/telemt/telemt/releases/latest` вернул **3.5.9** (stable,
опубликован 28 сентября 2026). Тег и HEAD `main` при проверке соответствовали
`e3f62db3474fdad12b4b9a20bdbac59b26b311bb`.

## Принятые решения

| Область | Источник и результат |
| --- | --- |
| WEB/TLS | [WEB_PROXY.en.md](https://github.com/telemt/telemt/blob/3.5.9/docs/WEB/WEB_PROXY.en.md): Telemt принимает plain HTTP/1.1, TLS завершает Nginx. |
| iOS | В той же документации metadata-free iOS поддерживает только `https`. Менеджер не включает negotiation и lanes. |
| Decoy | Поддержан `static_directory`, файлы загружаются снимком. Root-owned каталог исключает запись со стороны сервиса. |
| SOCKS | [Reference](https://github.com/telemt/telemt/blob/3.5.9/docs/Config_params/CONFIG_PARAMS.en.md): `[[upstreams]]`, `type = "socks5"`, `address = "host:port"`. Без SOCKS используется явный `type = "direct"`. |
| IPv4 | `[network] ipv4 = true`, `ipv6 = false`, `prefer = 4`; deprecated `prefer_ipv6` не используется. |
| Healthcheck | [src/healthcheck.rs](https://github.com/telemt/telemt/blob/3.5.9/src/healthcheck.rs): сначала загружает конфигурацию; при `server.api.enabled = false` возвращает успех без runtime-пробы. Поэтому проверка candidate не заменяет проверки listener/HTTP/TLS. |
| CLI | [src/cli.rs](https://github.com/telemt/telemt/blob/3.5.9/src/cli.rs): `telemt healthcheck /path/config.toml`. |
| Startup | [startup.rs](https://github.com/telemt/telemt/blob/3.5.9/src/startup.rs), [runtime_startup.rs](https://github.com/telemt/telemt/blob/3.5.9/src/maestro/runtime_startup.rs): network probe и подготовка runtime предшествуют готовому listener. Ожидание ограничено 90 секундами; тест моделирует 18 секунд. |
| Capabilities | [service generator](https://github.com/telemt/telemt/blob/3.5.9/src/service/mod.rs) выдаёт NET_BIND_SERVICE и NET_ADMIN. Для порта 18080 оставлен только NET_ADMIN. |
| Conntrack | [reference](https://github.com/telemt/telemt/blob/3.5.9/docs/Config_params/CONFIG_PARAMS.en.md#inline_conntrack_control): `false` очищает notrack rules, а не гарантирует отсутствие привилегированного cleanup. |
| Cleanup | [transaction.rs](https://github.com/telemt/telemt/blob/3.5.9/src/conntrack_control/firewall/transaction.rs) и [actor.rs](https://github.com/telemt/telemt/blob/3.5.9/src/conntrack_control/firewall/actor.rs): recovery/cleanup вызывается для initial Unknown state, а также при завершении. Режим `tracked` не устраняет эту операцию. |
| Известная ошибка | [command.rs](https://github.com/telemt/telemt/blob/3.5.9/src/conntrack_control/firewall/command.rs): `is_not_found_error()` не распознаёт `Chain 'TELEMT_NOTRACK' does not exist`. Проверенный `main` содержал тот же код. |

В менеджере это предупреждение считается известным non-fatal только при сочетании:
Telemt 3.5.9, Ubuntu 26.04, `iptables --version` с `nf_tables`, уровень WARN,
контекст `Failed to reconcile conntrack firewall policy`, startup recovery и
точный текст отсутствующей цепочки. Дополнительная ошибка, другой backend,
версия или контекст приводят к failure. Правила iptables менеджер не создаёт.

`CAP_NET_ADMIN` даёт сервису широкие права в сетевом namespace. Это осознанный
компромисс с текущим upstream cleanup, а не утверждение, что WEB listener сам
по себе требует привилегий. `CAP_SYS_ADMIN` и `CAP_NET_BIND_SERVICE` не выдаются.

FakeTLS masking/emulation отключены явно, потому что этот профиль обслуживает
только WEB и собственный static decoy. Middle proxy отключён, Telegram TCP egress
идёт через выбранный direct/SOCKS upstream. Поля пользовательского TOML при
обновлении не меняются. `general.beobachten_file` направлен в writable
`/var/lib/telemt/state/beobachten.txt`: upstream default `cache/beobachten.txt`
несовместим с root-owned рабочим каталогом hardened unit.

## Релиз и целостность

[Release 3.5.9](https://github.com/telemt/telemt/releases/tag/3.5.9) содержит fix
trusted helper argv0 для multi-call firewall binaries и обновление документации.
Для переносимости на старые x86 процессоры не используется вариант x86_64-v3.

| Asset | SHA256 архива из GitHub API |
| --- | --- |
| `telemt-x86_64-linux-gnu.tar.gz` | `565fe659765cd0f4e0f851b3d06a50ab9c25bf3bdd9c680646864215d56c258b` |
| `telemt-aarch64-linux-gnu.tar.gz` | `808eac1217e53147484029b3cb89f764c78b8b0506c36969c024905acaba23bc` |

Upstream также публикует `.sha256` assets. Менеджер использует официальный
`assets[].digest`, полученный по HTTPS, и не запускает бинарник до совпадения
SHA256. Это проверка целостности относительно GitHub, **не независимая подпись**.
Если digest исчезнет, установка/обновление прекращаются.

Fresh install запрашивает latest при каждом запуске, но отказывается автоматически
создавать конфигурацию для ещё не исследованного релиза. Для нового релиза нужно
обновить version gate и contract test. Binary update допускает новый stable после
проверки его healthcheck на неизменном текущем TOML и последующих runtime-проб.

## Повторная проверка 3x-ui-pro

30 сентября 2026 повторно проверены latest stable Telemt (по-прежнему 3.5.9),
его main (тот же commit выше, missing-chain bug не исправлен) и текущий main
`mozaroc/3x-ui-pro`: `a2c430cd6dec7c86d873dcda3544a61e7ac41144`.

- [x-ui-latest.sh, строки 289-307](https://github.com/mozaroc/3x-ui-pro/blob/a2c430cd6dec7c86d873dcda3544a61e7ac41144/x-ui-latest.sh#L289-L307),
  Git blob `671ca1e17b0162493b05cf3086968d1b43b5547f`.
- [x-ui-patch.sh, строки 213-231](https://github.com/mozaroc/3x-ui-pro/blob/a2c430cd6dec7c86d873dcda3544a61e7ac41144/x-ui-patch.sh#L213-L231),
  Git blob `dc506e80e371c7768177881fd0b3b7676c55bf3f`.

Оба создают один `$sni_name` map с `hostnames;`, xray/www upstreams и один
router с `set_real_ip_from unix:;`, `listen 443;`, `listen [::]:443;`, исходящим
`proxy_protocol on;` и `ssl_preread on;`. HTTP vhosts повторно включают общий
`snippets/includes.conf`, содержащий экранированные regex и `${safe}`.
Именно эти формы первая версия отвергала. Исправление сохраняет existing routes,
default, listens, trust directive и все HTTP файлы; добавляет только mapping,
managed upstream и отдельный vhost.

По [Nginx stream map](https://nginx.org/en/docs/stream/ngx_stream_map_module.html)
`hostnames;` должен находиться перед значениями. Менеджер принимает этот flag,
но намеренно отвергает wildcard/regex SNI. По
[Nginx stream realip](https://nginx.org/en/docs/stream/ngx_stream_realip_module.html)
`unix:` обозначает UNIX sockets; получение PROXY header требует отдельного
`listen ... proxy_protocol`. Публичные listens здесь такого flag не имеют.
Менеджер сохраняет точный существующий trust directive, не расширяет его и
по-прежнему отказывает на входящем PROXY protocol на публичном порту.

Тесты формируют все шесть Nginx heredocs каждого pinned скрипта без выполнения
shell-кода upstream. Изменения тестовых ports/cert paths изолируют настоящий
Nginx от системной конфигурации CI. Это проверка совместимости с указанными
исходниками, а не обещание принимать любые будущие изменения 3x-ui-pro.

## Границы доказательств

CI проверяет конфигурацию настоящим скачанным и проверенным бинарником 3.5.9.
Nginx stream/PROXY/TLS и канонизация X-Forwarded-For проверяются настоящим Nginx
на private test ports. Systemd, Certbot и rollback сценарии проверяются mocks.
Это не подтверждение работы на конкретном VPS или конкретной сборке Telegram.
Проверка native iOS/Desktop, реального DNS/TLS, egress и host netfilter обязательна
на тестовом VPS перед production rollout.
