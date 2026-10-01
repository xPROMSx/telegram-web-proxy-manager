# CI coverage truth table

Supported Telemt: **3.5.10**. This inventory describes `.github/workflows/checks.yml`.
R = REAL operation; M = MOCKED/synthetic operation; — = not exercised. R/M means
both occur in the named step. Static unit/config text inspection is not a running
systemd service or a real process capability test. Real filesystem ownership here
means temporary fixture ownership, not ownership of a deployed VPS installation.

| CI step/test | Telemt binary | Telemt process | systemd lifecycle | user/group lifecycle | filesystem ownership | nft/iptables | CAP_NET_ADMIN |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Install tools / runtime PATH | — | — | — | — | — | — | — |
| Bash syntax / ShellCheck | — | — | — | — | — | — | — |
| Parser/unit / `run.sh` | M | M | M | M | R | M | M |
| Fresh / fresh-rollback | M | M | M | M | R | M | M |
| Download integrity | R/M | — | — | — | R | — | — |
| Bootstrap SemVer / preflight | — | — | — | — | R | — | — |
| Fresh account rollback (sudo) | — | — | — | R | R | — | — |
| Pin provenance / upstream | R | — | — | — | R | — | — |
| Pinned staging | R | M | M | M | R | M | M |
| Real pinned runtime (sudo/unshare) | R | R | — | — | R | R | R |
| Pin evidence equality | — | — | — | — | — | — | — |
| Manager bootstrap (sudo) | — | — | — | — | R | — | — |
| Pinned upgrade/version rollback | M | M | M | M | R | M | M |
| nf_tables diagnostic bridge | — | — | — | — | — | R | R |
| Writable-state/unit contracts | — | — | — | — | — | — | — |
| Shared/exclusive lock races | — | — | — | — | R | — | — |
| ACME transactions | — | — | M | — | R | — | — |
| Renewal hook/socket/scheduler (sudo) | — | — | M | — | R | — | — |
| Nginx stream/TLS | — | — | — | — | R | — | — |
| Reviewed 3x-ui-pro topologies | — | — | — | — | R | — | — |

| Same CI step/test | listener | HTTP | TLS | Nginx | Certbot | SOCKS | journal/log classifier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Install tools / runtime PATH | — | — | — | — | — | — | — |
| Bash syntax / ShellCheck | — | — | — | — | — | — | — |
| Parser/unit / `run.sh` | M | M | M | M | M | M | R (synthetic records) |
| Fresh / fresh-rollback | M | M | M | M | M | M | R (mock journal transport) |
| Download integrity | — | — | — | — | — | — | — |
| Bootstrap SemVer / preflight | — | — | — | — | — | — | — |
| Fresh account rollback (sudo) | — | — | — | — | — | — | — |
| Pin provenance / upstream | — | — | — | — | — | — | — |
| Pinned staging | M | M | M | M | M | M (config real) | R (mock journal transport) |
| Real pinned runtime (sudo/unshare) | R | R | — | — | — | — | R (actual streams + injected fatal negatives) |
| Pin evidence equality | — | — | — | — | — | — | — |
| Manager bootstrap (sudo) | — | — | — | — | — | — | — |
| Pinned upgrade/version rollback | M | M | M | M | — | M | M |
| nf_tables diagnostic bridge | — | — | — | — | — | — | R (synthetic WARN containing real diagnostic) |
| Writable-state/unit contracts | — | — | — | — | — | — | — |
| Shared/exclusive lock races | — | — | — | — | — | — | — |
| ACME transactions | M | M | M | M | M | — | — |
| Renewal hook/socket/scheduler (sudo) | M | — | R (self-signed) | M | M (renewal settings) | — | — |
| Nginx stream/TLS | R | R | R (self-signed) | R | — | — | — |
| Reviewed 3x-ui-pro topologies | R | R | R (self-signed) | R | — | — | — |

`upstream.sh`, `staging.sh` and the positive download probe execute the real pinned
binary's version/healthcheck CLI, not a server. Healthcheck with API disabled is
configuration validation. `REAL_CANDIDATE` in fresh means that same boundary only;
readiness, service lifecycle, path health and journal source remain fixtures.

The runtime step has no mocked helpers, process, socket, HTTP or capability result.
It starts the actual official digest-verified pin with production-generated config
and index in a new network namespace. It checks real namespace identity and kernel
capabilities, real helpers, PID-owned listener, HTTP body, actual merged stdout/
stderr, clean exit and nft/IPv4/IPv6 firewall inspection. Fatal injection tests the
production classifier on captured output; it does not inject a runtime service
crash. The smoke runs as root in the disposable Actions namespace, not as the
production telemt account under the full systemd sandbox. It never proves systemd
hardening or production non-root capability inheritance. Namespace creation or
real helper failure is a hard test failure; no skip/fallback/continue-on-error.

Account rollback uses real temporary user/group creation and deletion in a separate
root fixture. Bootstrap tests real root-owned file identities and atomic paired
manager updates, with release/download/menu fixtures; it never creates releases.
The dependency step runs real conntrack under real systemd default PATH, not a
Telemt service. Contract tests inspect generated TOML/unit text only. Nginx tests
run actual Nginx/TLS/HTTP with a Python origin, not a running Telemt; ACME content
serving there is real, issuance is not performed. SOCKS configuration syntax is
checked by real Telemt healthcheck; actual SOCKS egress remains untested.

CI does not prove complete end-to-end VPS behavior. Live acceptance must cover the
telemt UID and complete systemd sandbox, actual host netfilter coexistence, restart/
repair and state persistence, real DNS/ACME renewal, public IPv4 TLS routing, real
SOCKS/Telegram egress and native Telegram iOS/Desktop clients. CAP_NET_ADMIN remains
broad network authority. Warnings can accompany operational degradation, so their
counts deserve review even when objective readiness succeeds. Rollback cannot
promise restoration of unrelated external changes or already-issued certificates.
