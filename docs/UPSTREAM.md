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
обновлении не меняются.

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

## Границы доказательств

CI проверяет конфигурацию настоящим скачанным и проверенным бинарником 3.5.9.
Сетевые, systemd, Certbot и rollback сценарии проверяются изолированными mocks.
Это не подтверждение работы на конкретном VPS или конкретной сборке Telegram.
Проверка native iOS/Desktop, реального DNS/TLS, egress и host netfilter обязательна
на тестовом VPS перед production rollout.
