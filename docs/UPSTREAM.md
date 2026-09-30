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
обновить version gate и contract test. После второго review binary update тоже
ограничен audited release 3.5.9: успешный healthcheck будущей версии сам по себе
не доказывает совместимость её runtime write paths. До нового source audit
неизвестный релиз требует manual review, существующий TOML не меняется.

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

## Runtime paths and systemd audit, full second review

Rechecked official latest stable/main and both 3x-ui-pro scripts immediately before
this pass: revisions are unchanged from the records above. The following table
covers the generated WEB profile, API disabled, middle proxy disabled, direct or
SOCKS upstream. References below use the audited Telemt tag 3.5.9.

| Path / upstream default | Reads/writes and applicability | Manager decision |
| --- | --- | --- |
| Config `/etc/telemt/telemt.toml` | [bootstrap.rs](https://github.com/telemt/telemt/blob/3.5.9/src/maestro/bootstrap.rs) reads explicit config, can create defaults if absent; API can edit config only when enabled. | Existing root:telemt 0640 config, API disabled, ProtectSystem strict. Missing config is not writable to the service. |
| Runtime base / `general.data_path` | Bootstrap enters runtime directory; [helpers.rs](https://github.com/telemt/telemt/blob/3.5.9/src/maestro/helpers.rs) prefers non-root WorkingDirectory, with explicit CLI/data path handling. | Explicit root-owned `/var/lib/telemt`, matching WorkingDirectory; no writable working-directory expansion. |
| `general.beobachten_file`, `cache/beobachten.txt` | Enabled by default; [runtime_tasks.rs](https://github.com/telemt/telemt/blob/3.5.9/src/maestro/runtime_tasks.rs) periodically writes snapshots through [helpers/runtime.rs](https://github.com/telemt/telemt/blob/3.5.9/src/maestro/helpers/runtime.rs). Unix atomic writer uses sibling temporary file/rename, mode 0600. | `/var/lib/telemt/state/beobachten.txt`. |
| `general.quota_state_path`, `telemt.limit.json` | [orchestrator.rs](https://github.com/telemt/telemt/blob/3.5.9/src/maestro/orchestrator.rs) loads at startup; [shutdown.rs](https://github.com/telemt/telemt/blob/3.5.9/src/maestro/shutdown.rs) saves even for this profile; [quota_state.rs](https://github.com/telemt/telemt/blob/3.5.9/src/quota_state.rs) atomically replaces mode 0600 through secure_fs. | Explicit `/var/lib/telemt/state/telemt.limit.json`; fixes an active unwritable default. Sibling temporary files remain in state. |
| `general.unknown_dc_log_path`, `unknown-dc.txt` | [direct_relay/routing.rs](https://github.com/telemt/telemt/blob/3.5.9/src/proxy/direct_relay/routing.rs) can append; [defaults.rs](https://github.com/telemt/telemt/blob/3.5.9/src/config/defaults.rs) defaults file logging to false. | Explicit `unknown_dc_file_log_enabled = false`; inactive path still redirected to `/var/lib/telemt/state/unknown-dc.txt`. |
| `network.cache_public_ip_path`, `cache/public_ip.txt` | Field exists in schema/defaults/hot-reload diff; source-wide search finds no runtime read/write of this field. [probe.rs](https://github.com/telemt/telemt/blob/3.5.9/src/network/probe.rs), probe/local and stun use network sockets/in-memory results. | Set `/var/lib/telemt/state/public_ip.txt` defensively; do not claim the cache is currently persisted. STUN/DC startup probes remain enabled. |
| `general.proxy_secret_path`, `proxy-secret` | [me_startup.rs](https://github.com/telemt/telemt/blob/3.5.9/src/maestro/me_startup.rs) returns immediately for `use_middle_proxy = false`. Otherwise secret fetcher reads/writes an atomic cache. | Inactive; explicit `/var/lib/telemt/state/proxy-secret`. |
| `general.proxy_config_v4_cache_path` / `proxy_config_v6_cache_path`, `cache/proxy-config-v4.txt` / `cache/proxy-config-v6.txt` | Startup snapshot fallback and ME supervisors read/write caches only in middle-proxy lifecycle. | Inactive; both explicit paths under `/var/lib/telemt/state/`. |
| `censorship.tls_front_dir` | [tls_bootstrap.rs](https://github.com/telemt/telemt/blob/3.5.9/src/maestro/tls_bootstrap.rs) returns before cache construction when tls_emulation is false. Otherwise TLS cache reads and writes domain JSON. | Inactive; explicit `/var/lib/telemt/state/tls-front`. |
| `[logging].path` | [logging/file.rs](https://github.com/telemt/telemt/blob/3.5.9/src/logging/file.rs) can create/rotate logs when file logging is selected. | Explicit `destination = "stderr"`, no file log; journald still receives upstream links. |
| Decoy static directory | WEB static-directory loader reads the root-owned snapshot; does not create service files. | `/var/lib/telemt/public`, root:telemt, index 0440. |
| PID file, daemon logs, init/service output | [maestro/mod.rs](https://github.com/telemt/telemt/blob/3.5.9/src/maestro/mod.rs) acquires PID file only for daemonization or explicit --pid-file; init/service generators are separate CLI paths. | Default Run is foreground, without these flags. No PID file/daemonization/init writes in the unit. |

Fresh config now enables `[general].config_strict = true`; unknown-key rejection
is tested with the real verified release binary for direct and SOCKS configs.
Update never rewrites existing TOML. `runtime-contract` refuses active write paths
outside state, middle-proxy/TLS-emulation/file-log changes and mismatched data_path.
Earlier manager installations with the default relative quota path require manual
review; there are zero automatic migrations.

The unit retains User/Group telemt, CAP_NET_ADMIN only, ProtectSystem=strict,
WorkingDirectory=/var/lib/telemt and ReadWritePaths=/var/lib/telemt/state.
AF_INET/AF_INET6 cover upstream/probes and firewall helpers, AF_UNIX local sockets,
AF_NETLINK netfilter/interface operations. No CAP_SYS_ADMIN/NET_BIND_SERVICE.
[CLI](https://github.com/telemt/telemt/blob/3.5.9/src/cli.rs) default Run already
matches foreground Type=simple; `run --foreground` would not change this contract,
so ExecStart is retained. SIGTERM is handled by upstream graceful shutdown, then
conntrack/SYN cleanup, control-plane stop and quota save. Firewall helper timeouts
are 30s per command. TimeoutStopSec is increased from 45 to 180s for headroom,
without promising persistence if shutdown exceeds that bound.

## ACME compatibility contract

Both reviewed 3x-ui-pro scripts also emit `sites-available/80.conf`: one IPv4
listen 80, exact panel/reality names and `return 301 https://$host$request_uri`.
For occupied port 80, the manager verifies sockets belong to the active Nginx
master or its workers, with matching executable, and parses the recognized stream
and HTTP trees. Only exact names and recognized redirect-only port-80 servers
are automated; unknown HTTP routing, wildcard/regex names, flags and conflicting
FQDNs require manual review. The new ACME vhost is IPv4-only; existing IPv6 listeners
are preserved, and WEB DNS AAAA remains refused.

According to the official [Certbot webroot guide](https://eff-certbot.readthedocs.io/en/stable/using.html#webroot),
the authenticator writes challenge files below `.well-known/acme-challenge` and
needs an existing server to expose them. The manager creates a separate persistent
root-owned webroot/vhost, validates Nginx before reload and probes an actual local
challenge file before calling `certonly --webroot`. Other requests return 404.
Issuance failure/signals restore only ACME changes; Nginx is never stopped.
Successful issuance is a separate committed transaction so renewal remains possible
even if later Telemt setup fails. The Certbot renewal file's authenticator/path
and optional per-domain map are checked, alongside the managed vhost/marker.
No new scheduler is created; normal Certbot renewal and the validation/reload hook
are used. Free port 80 retains standalone mode. Real ACME issuance/renewal and
systemd runtime persistence remain live-acceptance tasks, not CI claims.

## Additional security findings addressed

- Check previously skipped locking when the file did not exist. Shared creation/open
  now validates a regular single-link private owner file; exclusive mutations use
  the same inode. Tests synchronize actual child processes with FIFOs, not sleeps.
- Candidate validation could race a root TOML editor. Config hashes are now captured
  before validation, checked afterwards and immediately before activation.
- Root-owned destination checks previously covered only the final symlink. All
  existing ancestors now reject symlinks and unsafe ownership/write permissions;
  root-owned sticky temp directories are permitted. Nginx read trees and write
  destinations share these checks. Legitimate sites-enabled links resolve only
  within the expected config tree. Root edits still require external coordination.
- Archive shape checks lacked a size/time bound. HTTPS download and regular member
  are capped at 128 MiB; extraction times out at 60s. Python reads a single named
  regular member without extracting paths, and rejects links/traversal/duplicates.
- SOCKS host and port checks are shared by CLI probe/config diagnostics, with range
  1..65535 and valid IPv4/hostname/localhost; auth and IPv6 remain unsupported.
- Nginx socket ownership is tied to systemd MainPID/worker ancestry and executable,
  rather than only the process name. Telemt listener checks also recheck MainPID.
- Port-80 runtime/config disagreement now refuses issuance, instead of selecting
  standalone while a pending Nginx reload would subsequently occupy port 80.
- Stream-context directives and upstreams are explicitly constrained: a map/router
  and named upstreams with one plain loopback server each; extra globals/options,
  duplicate upstreams and unresolved selector targets are refused.
- Modified existing Nginx files retain mode/ownership as well as original bytes
  outside the exact insertions. Certificate/private-key ownership, safe archive
  targets and matching public keys are verified before use.
- Future-release healthcheck success cannot prove future write-path compatibility;
  unknown runtime releases now require another source audit instead of auto-adoption.

Existing safeguards retained: HTTPS-only release/redirect protocols, exact official
asset URL and unambiguous digest, no candidate execution before verification,
root-only config/backups/staging, suppressed candidate diagnostics and raw journals,
signal rollback, managed manifest/hash checks and required public HTTPS probe.
No production VPS or secrets were used. See both READMEs for intentional boundaries.
