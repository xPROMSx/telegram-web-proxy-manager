# CI coverage truth table

Supported Telemt: **3.5.12** (fresh Install baseline). Manager 1.1.0 Update selects
the newest verified official stable release by compatibility, without a major/minor
restriction. This inventory describes `.github/workflows/checks.yml`.
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
| Private WEB link/root PTY | M (fresh fixture) | M | M | M | R | — | — |
| Fresh account rollback (sudo) | — | — | — | R | R | — | — |
| Pin provenance / upstream | R/M | — | — | — | R | — | — |
| Pinned staging | R | M | M | M | R | M | M |
| Real pinned runtime (sudo/unshare) | R | R | — | — | R | R | R |
| Pin evidence equality | — | — | — | — | — | — | — |
| Manager bootstrap (sudo) | — | — | — | — | R | — | — |
| Version/parser/offline receipt | R/M | — | — | — | R | — | — |
| Managed uninstall/certificate cycle | R/M | M | M | M | R | M | M |
| Universal official provenance (both GNU arches) | R | — | — | — | R | — | — |
| Universal transaction/crash matrix (sudo) | M | M | M | M | R | M | M |
| Bootstrap recovery barrier (sudo) | — | — | — | — | R | — | — |
| Ubuntu 24.04/26.04 boot + power cut | R/M | R | R | R | R | R | R |
| ARM64 CLI (qemu-user) | R | R (CLI only) | — | — | R | — | — |
| nf_tables diagnostic bridge | — | — | — | — | — | R | R |
| Writable-state/unit contracts | — | — | — | — | — | — | — |
| Shared/exclusive lock races | — | — | — | — | R | — | — |
| ACME transactions | — | — | M | — | R | — | — |
| Renewal hook/socket/scheduler (sudo) | — | — | M | — | R | — | — |
| Nginx stream/TLS | — | — | — | — | R | — | — |
| Reviewed 3x-ui Fresh topology | — | — | — | — | R | — | — |

| Same CI step/test | listener | HTTP | TLS | Nginx | Certbot | SOCKS | journal/log classifier |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Install tools / runtime PATH | — | — | — | — | — | — | — |
| Bash syntax / ShellCheck | — | — | — | — | — | — | — |
| Parser/unit / `run.sh` | M | M | M | M | M | M | R (synthetic records) |
| Fresh / fresh-rollback | M | M | M | M | M | M | R (mock journal transport) |
| Download integrity | — | — | — | — | — | — | — |
| Bootstrap SemVer / preflight | — | — | — | — | — | — | — |
| Private WEB link/root PTY | — | — | — | — | — | — | — |
| Fresh account rollback (sudo) | — | — | — | — | — | — | — |
| Pin provenance / upstream | — | — | — | — | — | M (config only) | — |
| Pinned staging | M | M | M | M | M | M (config real) | R (mock journal transport) |
| Real pinned runtime (sudo/unshare) | R | R | — | — | — | — | R (actual streams + injected fatal negatives) |
| Pin evidence equality | — | — | — | — | — | — | — |
| Manager bootstrap (sudo) | — | — | — | — | — | — | — |
| Version/parser/offline receipt | — | — | — | — | — | M (config only) | — |
| Managed uninstall/certificate cycle | M | M | R (self-signed) | M | R (local deletion)/M | — | M |
| Universal official provenance (both GNU arches) | — | — | — | — | — | — | — |
| Universal transaction/crash matrix (sudo) | M | M | M | M | — | M | M |
| Bootstrap recovery barrier (sudo) | — | — | — | — | — | — | — |
| Ubuntu 24.04/26.04 boot + power cut | R | R | R (self-signed) | R | M (local lineage) | — | R |
| ARM64 CLI (qemu-user) | — | — | — | — | — | R (config only) | — |
| nf_tables diagnostic bridge | — | — | — | — | — | — | R (synthetic WARN containing real diagnostic) |
| Writable-state/unit contracts | — | — | — | — | — | — | — |
| Shared/exclusive lock races | — | — | — | — | — | — | — |
| ACME transactions | M | M | M | M | M | — | — |
| Renewal hook/socket/scheduler (sudo) | M | — | R (self-signed) | M | M (renewal settings) | — | — |
| Nginx stream/TLS | R | R | R (self-signed) | R | — | — | — |
| Reviewed 3x-ui Fresh topology | R | R | R (self-signed) | R | — | — | — |

`upstream.sh`, `staging.sh` and the positive download probe execute the real pinned
binary's version/healthcheck CLI, not a server. Healthcheck with API disabled is
configuration validation. `REAL_CANDIDATE` in fresh means that same boundary only;
readiness, service lifecycle, path health and journal source remain fixtures.
`upstream.sh` also runs strict parser/version regressions with its real verified
3.5.12 binary and unchanged TOML. Complete binary/DATA activation and rollback now
run in the stronger universal root transaction suite and the real boot fixtures;
the previous binary-only shell transaction is no longer production Update.

The runtime step has no mocked helpers, process, socket, HTTP or capability result.
It starts the actual official digest-verified pin with production-generated config
and index in a new network namespace. It checks real namespace identity and kernel
capabilities, real helpers, PID-owned listener, HTTP body, actual merged stdout/
stderr, absent owned chains before startup, measured >=10-second post-readiness
dwell with a second actual listener/HTTP check, and absence of pinned conntrack
reconciliation/retry/shutdown failure fragments. Clean exit and nft/IPv4/IPv6
inspection follow. These absence assertions are upstream runtime contracts, not
production WARN exceptions. The seven 3.5.10 WARNs remain historical classifier
regressions, not healthy 3.5.12 runtime expectations. Fatal injection tests the
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
checked by real Telemt healthcheck; actual SOCKS egress is not exercised by CI.

CI does not prove complete end-to-end VPS behavior. Successful 0.1.2 live acceptance
on Ubuntu 26.04.1 LTS x86_64 is recorded in the
[primary README](../README.md#проверено-на-vps) and [English README](../README.en.md#vps-validation).
That acceptance used Telemt 3.5.11. Separate owner-run live acceptance of manager
0.1.3 on Ubuntu 26.04.1 LTS x86_64 completed normal managed Update 3.5.11 → 3.5.12:
byte-identical TOML/WEB link and unchanged unit, manifest, managed Nginx, certificate
identity and renewal config; active service with `NRestarts=0`, final `--check` OK
and the same WEB link working from a real Telegram client. The single known
censorship/restart WARN accompanied `errors=0, warnings=1` and passing objective
checks; it is not a new regression or blocker. This is owner-provided live
evidence, separate from CI and its narrower contracts above.
Deployment-specific acceptance must cover the
telemt UID and complete systemd sandbox, actual host netfilter coexistence, restart/
repair and state persistence, real DNS/ACME renewal, public IPv4 TLS routing, real
SOCKS/Telegram egress and native Telegram iOS/Desktop clients. CAP_NET_ADMIN remains
broad network authority. Warnings can accompany operational degradation, so their
counts deserve review even when objective readiness succeeds. Rollback cannot
promise restoration of unrelated external changes or already-issued certificates.

## Managed uninstall and certificate reuse (0.1.2)

`tests/test_uninstall.py` adds read-only reverse-plan byte preservation, changed
or shared stream/vhost refusals, source-hash rechecks, fd/no-follow tree
backup/removal/restore, mount/link refusals and strict certificate-record parsing.
Direct INT/TERM/HUP cleanup checks preserve signal exit codes after successful
rollback and report rollback failures explicitly.
`sudo bash tests/uninstall.sh` runs root-owned temporary fixtures with inert NSS,
service/listener/firewall/issuance boundaries and an explicitly fixture-scoped
ownership scanner. It executes install → uninstall keep certificate → fresh
same-domain Install for standalone and webroot, asserting zero new issuance and
unchanged lineage/key/renewal bytes. Certificate deletion uses the installed real
Certbot CLI with private config/work/log directories and local self-signed
lineages; it never issues against Let's Encrypt.

The same suite checks stopped/near-expiry removal, exact-lineage delete and foreign
lineage/account preservation, deletion failure without Telemt resurrection,
rollback after stop/Nginx/file/account boundaries and a representative TERM,
including legacy certificate-state migration and partial group deletion. A real
process with the managed numeric UID proves refusal without killing that process.
Missing/malformed/unknown manifest, changed vhost/map/unit/drop-in, unsafe link,
ambiguous account, mismatched certificate state/lineage, shared UID files and lock
contention refuse before mutation. A real same-device bind mount is rejected in a
private mount namespace; the focused Python fixture also checks mount-table
handling. Existing bootstrap signal stress, pin/provenance, real
Telemt/nft/HTTP runtime, root account, renewal, topology and all other suites remain.

These orchestration fixtures do not claim live systemd lifecycle, host firewall
coexistence, public ACME issuance/renewal or Telegram client acceptance. The
unchanged separate real runtime/Nginx tests cover their existing narrower
contracts. Cloud root emulation cannot substitute for native root UID/GID checks;
hosted Actions must run the new suite without skip/fallback/continue-on-error.

The live-runtime race regressions use a synchronous Python child after completed
ownership validation and before service stop. The child proves the service is
still active, then rewrites/creates/deletes files, atomically replaces one and
creates nested directories; its completion gates the transaction without sleeps
or retries. Unknown safe DATA names, including an extra file below `public/`, are
present before planning. A final shutdown write is added after stop. Successful
uninstall verifies the complete `objects-stopped` backup independently; failure
after removal verifies exact stopped-tree bytes/membership/modes/UID/GID, account,
service, Nginx, manifest/link and unchanged certificate.

Focused refusal cases cover pre-stop metadata failure, failed stop, still-active
service, stopped-backup allocation failure, concurrent static/control/index/
certificate/Nginx drift, and actual stopped-tree symlink, hardlink, FIFO, Unix
socket, character/block device, same-device bind mount, unsafe owner/mode/xattr.
They assert no deletion, unchanged runtime, prior service restoration and no
successful-uninstall report. Python tests additionally prohibit pre-stop DATA
enumeration, prove external ownership scans prune DATA, reject a pre-stop ledger
as removal authority and refuse a write after the final stopped snapshot. These
are filesystem/orchestration regressions, not a claim of VPS live acceptance.

## Private WEB link display (0.1.4)

`test_web_link.py` checks canonical URL bytes, supported manifest schema and exact
TOML domain/secret identity without printing random fixture credentials.
`sudo python3 tests/web_link_fixture.py` uses real root ownership, safe private
paths, real PTYs and shared/exclusive locks. It covers the exact seven-entry menu,
read-only file hashes/modes, default ANSI colors, NO_COLOR/TERM=dumb and both TTY
gates. Missing files, symlinks/hardlinks/FIFO, wrong owner/mode, unsafe ancestors,
malformed URL/manifest and domain/secret mismatch refuse without secret output.

The existing fresh transaction fixture additionally exercises the actual Install
and common presentation under a PTY, with service/certificate/path health mocked:
link output follows ARMED=0, manifest and final health checks; rejected candidates
print no link. CLI Install even on a PTY, and redirected menu Install, report only
the saved private path. Menu provenance is checked separately. Captured PTY output
stays in memory and is never copied into CI diagnostics. The existing noninteractive
fresh-install redaction assertions remain and also forbid any `tg://` output.

## Menu dependency setup follow-up (0.1.4)

`test_dependencies.py` runs real main/menu/preflight dependency collection in PTYs
with isolated command files, a mocked immutable platform and a mocked apt-get.
It covers single confirmation, Y/y, decline/default, CLI even on TTY, redirected
output, fixed package deduplication, mandatory executable recheck, apt update and
install failures, unavailable apt, Nginx prerequisite refusal, Uninstall extras and
post-install conntrack systemd PATH refusal. Platform/action PID equality proves
continuation without a manager restart; no CI package set is changed by these tests.

The native-root WEB-link fixture additionally exercises actual Ubuntu/architecture/
init guards before apt and actual menu Show with conntrack, Nginx, Certbot and
systemd tools absent. The original strict private-file/TTY/color tests remain.
The owner clean Ubuntu finding is recorded in OPERATIONS. Live acceptance of
published v0.1.4 completed dependency installation, fresh Install, menu link
display, real Telegram connection and Check. Mocked apt fixtures themselves do
not claim real-server package installation. Owner acceptance of v0.2.0 is complete (3.5.12 → 3.5.14, real Telegram, final Check OK).

## Universal generation Update (0.2.0)

`test_update_metadata.py` covers double complete pagination (including exact page
multiples), all stable version series, the seven exact historical quarantines,
duplicate/malformed/ambiguous metadata, inventory drift, signed annotated tags,
commit/asset changes and both-architecture archive/sidecar/receipt agreement.
`test_update_protocol.py` checks authenticated Hello/Welcome, session replay,
uplink sequence/ack/replay even without conveyor negotiation, optional conveyor,
bounded idle 204 or Ping/Pong downlink, DELETE and malformed/decoy negatives. HTTP
transport is real for its bounded-header/body cases; protocol responses are fixtures.

`test_update_snapshot.py` uses real temporary files and bounded streaming, including
65 MiB ordinary and 70 MiB sparse files, short reads/writes, concurrent growth/
replacement/membership changes and unsealed partial clones. Root transactions add
real fsync/rename publication, ENOSPC/EIO/inode/block failures, every forward and
rollback intent/result crash boundary, partial metadata/clone/LKG publication,
INT/TERM/HUP, idempotent recovery, CRITICAL/gate refusal and retained root-owned LKG.
Service/API/isolation are explicitly mocked there. Synthetic compatible 4.0.0 and
incompatible/no-op/quota-reset candidates use the same policy as 3.5.13, including
ARM receipt policy; they are not an upstream 4.0.0 runtime claim. Late objective
failures restore full DATA/receipt/binary and prior controls without retries.

Bounded safety regressions distinguish exact manager-owned controls from valid
certificate renewal and foreign firewall/Nginx changes, including pre-stop aborts
and activated-candidate rollback. An endpoint/count fixture proves full inventory
discovery stays pre-downtime and frozen revalidation uses no history enumeration.
Scoped stopped-DATA fsync faults/interruption precede snapshot authority, three
recovery-unit/drop-in publication boundaries remain retryable, and terminal boot
authority survives persistent housekeeping failure while the next mutation and
bootstrap refuse incomplete cleanup. Runtime/bootstrap immutable-key boundaries
and shell/helper manager/baseline constants have mechanical parity regressions.
The existing Ubuntu boot cycle additionally exercises persistent disposable-evidence
cleanup failure across actual COMMITTED and ROLLBACK_COMPLETE reboots, with ordinary
CLI mutation refusal; this adds one focused terminal reboot, not another matrix.

The bootstrap root suite validates terminal receipts/journals, generation/binary/
DATA identity and exact gate contracts without executing the downloaded pair.
Pending, corrupt, unknown-schema and explicit legacy-downgrade cases refuse before
pair staging. The Uninstall suite also runs generation-aware preserve/reinstall,
explicit delete and removal-failure rollback: new receipt/journal/gate controls
are removed or restored, root-normalized LKG stays retained, and fresh same-domain
Install uses the actual verified baseline ELF with zero certificate issuance.

`update_provenance.py` actually queries official GitHub metadata, verifies the
signed 3.5.13 tag, downloads and hashes both GNU archives/sidecars, extracts each
ELF safely and writes schema-1 receipts outside the checkout. It independently
verifies the 3.5.12 baseline archive and embedded ELF identity. It executes no ELF.

`update_boot.sh` runs offline disposable QEMU guests with real Ubuntu 24.04 and
26.04 PID 1 systemd. Each family exercises the official 3.5.12 baseline and full
3.5.13 Update: exact generated TOML/base unit, real Telemt UID/CAP_NET_ADMIN,
private namespaces/cgroups and strict parser, stopped full-DATA rehearsal/quota
readback, authenticated WEB, PID-owned listener, real local/public-path Nginx TLS/
HTTP and actual journal. Public-path DNS resolves to the guest fixture, not the
Internet. Acceptance dwells 150 seconds, restarts gracefully and dwells 45 seconds;
Timed samples retain process/cgroup/path/journal/deployment checks; full WEB runs
once at each readiness and lightweight WEB once at each interval end.
The real Update and power-cut rollback use actual empty baseline quota
`{"last_reset_epoch_secs":0,"users":{}}`, with no synthetic production user.
A separate private CI rehearsal tests a non-empty user with a noncanonical top-level
reset timestamp; canonicalization is accepted while per-user semantics survive.
Focused quota tests reject user disappearance, used_bytes decrease and user reset
changes. All immutable controls and unrelated real firewall state are preserved.

Four hostile compiled ELF probes exercise denied host files/environment/systemd/
network access, a hung version command with detached child, bounded log flooding
and an always-successful fake 4.0.0 healthcheck rejected by the unknown-key negative.
Eleven real unsafe DATA objects include same-device bind mounts, devices, ACL and
capability xattrs. A committed reboot proves the new generation starts through the
exact gate. The host then abruptly kills only the disposable QEMU container during
a second nonterminal Update; the next real boot restores old binary/full DATA/
receipt, rejects candidate-only data, proves old health and opens the gate under
the real recovery unit. Guest transport uses recorded, separately verified official
metadata/artifacts because the guest has no NIC; this does not replace the live
GitHub provenance step. Self-signed certificates/local renewal metadata avoid ACME.

`update_arm.sh` executes the actual official ARM64 3.5.13 ELF under qemu-user for
version, direct/SOCKS config healthcheck and strict unknown-key refusal, with no
network, a read-only image and dropped candidate capabilities. ARM metadata,
downloads, extraction, receipts and synthetic update/rollback policy are covered;
native ARM systemd/runtime acceptance is not claimed.

Every existing safety step remains enabled. Namespace, cgroup, boot, real-binary
or helper absence fails the job; there is no skip/fallback/continue-on-error.
CI proves these bounded contracts, not real Telegram transport, Internet SOCKS
egress, production Let's Encrypt renewal or owner-host coexistence. The owner completed live acceptance of the existing updater architecture.
Separate owner acceptance of 1.0.0 completed on Ubuntu 26.04 x86_64 after companion
3x-ui Auto Nginx Fresh Install. Existing Let's Encrypt certificate reuse, real
Telegram, CSP-compatible Fake Sites/Service Status, random cover changes and TTY
progress passed. Normal Update 3.5.12 → 3.5.14 completed 150s + 45s acceptance and
preserved TOML, index.html, cover.css and WEB-link bytes. COMMITTED journal and
matching receipt/manager/DATA generations were verified; final Check OK reported
errors=0, warnings=0. These are owner live results, not additional CI claims.


## Cover / progress targeted coverage (1.0.0)

`test_cover.py` checks embedded/source manifest parity, sizes/digests, bounded IDs,
external/active HTML refusal, random initial cover, fallback, different random cover,
restore, unknown-current refusal, no-follow/hardlink/mode checks, root:group 0440,
post-write failure restoration and unchanged controls. All three covers and Service
Status survive the existing mocked full-DATA transaction. `test_update_progress.py`
checks TTY progress, NO_COLOR, TERM=dumb/non-TTY diagnostic output, deadline-only
rendering and visible failure. Existing menu tests enforce all eight entries and
Uninstall item 7. Existing baseline namespace runtime smoke additionally proves
atomic replacement remains cached before restart and new Service Status is served
after graceful restart, with the PID-owned HTTP listener. No new QEMU/ARM matrix
or CI architecture was added; existing mandatory steps remain enabled.

## Public rebrand and bootstrap transition (1.1.0)

`test_rebrand.py` uses offline repository metadata and real root-owned temporary
launcher fixtures. It covers primary-before-legacy resolution, canonical repository
and release identity refusal, the v1.0.1 launcher upgrade, both public commands,
unsafe/conflicting launcher paths, failed second-wrapper publication and signal
interruption. Current-brand/version assertions run alongside the existing SemVer,
no-candidate-execution and recovery-barrier bootstrap tests. Persistent legacy
paths and markers remain compatibility ABI; the GitHub repository is renamed manually.
