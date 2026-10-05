# Upstream audit

Supported Telemt: **3.5.12** (fresh Install baseline).

The current release and source were verified through official GitHub metadata and
actual downloads on 3 October 2026 (UTC). Manager SCRIPT_VERSION is
1.0.0. Fresh Install stays deliberately fixed. Universal Update enumerates the
complete official release history, choosing the highest stable SemVer across all
series and verifying its compatibility; it does not select an unchecked latest URL.

| Provenance | Verified value |
| --- | --- |
| Release | [3.5.12](https://github.com/telemt/telemt/releases/tag/3.5.12), stable, not draft/prerelease |
| Tag/source commit | `c4555e25f39dd5be200ccf6353f7d82bfcf89131` |
| Signed annotated tag object | `3faef0f16619ba33bfc6e1afb3b2d14c824bdd44`; GitHub `verified=true`, `reason=valid` |
| x86_64 archive SHA256 | `92bfaa6177d87790bae79caea08d8ddddd0ca3ebc95545c1d62374897592c6c3` |
| aarch64 archive SHA256 | `16bfd0e78b746171b0434c935ca953358c88b43cfb0091d7b74cb982424202a3` |

Both architecture assets were downloaded and hashed independently. Production
constructs the exact official `releases/download/3.5.12/telemt-ARCH-linux-gnu.tar.gz`
URL, compares its hash with the embedded pin before extraction/execution, retains
strict archive validation, and verifies the binary's exact version. No x86_64-v3
asset is selected. Tag verification reports GitHub's result, not independent
signing-key authentication; asset digests are integrity checks, not signatures.
`tests/pinned.sh` compares official release/tag metadata and both asset hashes;
CI mechanically compares the production pin, docs, real downloaded binary, staging
healthcheck binary and runtime binary. A changed asset fails closed.

Fresh Install downloads only this pin. Check uses a local validated receipt plus
objective health, with no GitHub dependency or version equality. Universal Update
checks exact release identity even on equal versions and refuses downgrade/custom
build ambiguity. The full contract is in [OPERATIONS](OPERATIONS.md#universal-update-020).

## Universal Update 0.2.0 provenance and compatibility

The task-start official stable release was **3.5.13**, release ID `402625235`,
published `2026-10-03T17:52:11Z`. It is an actual test target, not a new Install pin.

| Official 3.5.13 evidence | Value |
| --- | --- |
| Signed annotated tag object | `d1b24a42e5d8ffc8b1ff4d33f56c2ff43fbf668b`; GitHub verified/valid |
| Source commit | `d3de9865cf5d088809fdf728059bcb2b0841db67` |
| x86_64 GNU archive SHA256 | `92021ad31520302bfbfe4a13b49adc9d129ec48a08699f81515e9c55668be9fa` |
| aarch64 GNU archive SHA256 | `9aec3a87e730c6dc0d1baaffcdde3dde9bada1e892c6b96195c0740919f3de52` |
| Extracted x86_64 ELF SHA256 | `c9cd424b51dfe1dfba870c4ed456baaf32615127cd3d89dc69baa94502c53942` |
| Extracted aarch64 ELF SHA256 | `d280700fe1508f4b1e13119d422c8a5dba20fd38a71e099fbcf68791c09903e3` |

Discovery verifies repository ID `1125007401` / `telemt/telemt`, two complete
paginated inventories, exact release/tag/commit identities, verified signed
annotated tag, architecture-specific GNU asset and checksum asset, API digests,
single exact checksum entry and downloaded bytes before safe extraction. Drift,
duplicate identities/JSON keys, ambiguous equal precedence, unsafe archives or
incomplete inventories refuse. Drafts/prereleases are excluded; exactly seven
malformed historical release identities are quarantined, not a general malformed
version exemption. Rechecks freeze identity throughout the transaction.

This trusts GitHub's verification and official release channel. SHA256 is integrity
evidence, not reproducible-build attestation or independent signer-key authentication.
An upstream/account/platform compromise remains a trust boundary.

The trusted WEB probe performs HMAC-authenticated bootstrap, Hello/Welcome,
session replay, sequenced uplink/ack/replay, conveyor negotiation when exposed,
bounded authenticated downlink and close without evaluating candidate Javascript.
The current upstream idle poll returns HTTP 204/cursor 0. A Ping, if emitted,
must pass cursor/replay/Pong validation; an idle response proves bounded session
liveness, not a real Telegram client exchange. Legacy 3.5.12 still requires uplink
sequence/ack without conveyor. Generated TOML and the base unit are unchanged.
Full isolated state rehearsal and post-activation checks decide compatibility,
including synthetic compatible/incompatible 4.0.0; version numbers never substitute
for these checks. Owner live acceptance of 0.2.0 is complete, including automatic 3.5.12 → 3.5.14,
real Telegram and final Check OK. New 1.0.0 cover/UI acceptance remains pending.

## Reviewed 3.5.11 -> 3.5.12 compatibility

The [exact immutable diff](https://github.com/telemt/telemt/compare/94f4f7d5401a28afb6e6f4a7d66d6f56259c6c5d...c4555e25f39dd5be200ccf6353f7d82bfcf89131)
contains nine commits and 49 changed files, including configurable WEB carrier
method, autonomous ME recovery after Direct fallback, ME NAT discovery cancellation
and conntrack startup/admission changes.

| Upstream change | Existing manager contract |
| --- | --- |
| `inline_conntrack_control` defaults to false; FirewallAuthority starts only when explicitly enabled with CAP_NET_ADMIN | Generated TOML already sets `inline_conntrack_control = true`, `mode = "tracked"`; the new default does not change it. The existing capability/helper and reconciliation/shutdown checks remain required. |
| New `web.carrier_method`, default `Post` / HTTP POST | The manager leaves the field absent; POST preserves the previous WEB behavior. No new option is needed. |
| Generated upstream unit adds AF_NETLINK | The manager unit already allows AF_INET, AF_INET6, AF_UNIX and AF_NETLINK with CAP_NET_ADMIN only. No unit change is needed. |
| ME recovery and NAT cancellation | Managed `use_middle_proxy = false` remains unchanged; direct and SOCKS5 configuration healthchecks still apply. |

In the historical manager 0.1.3 pin review, production changes were limited to
manager version and reviewed release constants.
Generated TOML/unit, candidate compatibility, runtime paths, WEB profile, direct/
SOCKS upstream and severity classification are unchanged. Real 3.5.12 config and
staging healthchecks and the isolated runtime smoke exercise these contracts.
Those Update fixtures accepted a managed 3.5.11 source, preserved TOML bytes, restored the
old binary after candidate/runtime rejection, handle equal versions and refuse
newer or same-precedence non-exact builds. An additional Update fixture uses the
real digest-verified 3.5.12 candidate against existing TOML; its 3.5.11 source
binary and service lifecycle were synthetic. Current Universal Update coverage
uses full-generation filesystem crash fixtures and actual Ubuntu boot tests instead.

The historical live acceptance below covers 0.1.1/0.1.2 with Telemt 3.5.11.
Separate owner-run live acceptance used exact PR #6 manager 0.1.3 files from
`ef66c09e5a9ddda5c1aa448db909940cfff3e766` on Ubuntu 26.04.1 LTS x86_64.
Normal `telemt-web-manager --update` successfully upgraded managed 3.5.11 to 3.5.12;
TOML/WEB link remained byte-identical, and unit, manifest, managed Nginx, Certbot
renewal config and certificate serial/fingerprint/public key were unchanged.
The service remained active/running with `NRestarts=0`; final `--check` returned
OK and the same WEB link worked from a real Telegram client. Current-invocation
logs contained the single known `config reload: censorship settings changed; restart required` WARN with `errors=0, warnings=1` and passing objective checks,
not a new regression or release blocker. This owner-provided evidence is separate
from CI, which does not establish a real Telegram connection or all deployments.

## Historical 3.5.11 conntrack recovery and retained severity policy

The immutable [firewall model](https://github.com/telemt/telemt/blob/94f4f7d5401a28afb6e6f4a7d66d6f56259c6c5d/src/conntrack_control/firewall/model.rs)
maps tracked/disabled policy to Empty. The [actor](https://github.com/telemt/telemt/blob/94f4f7d5401a28afb6e6f4a7d66d6f56259c6c5d/src/conntrack_control/firewall/actor.rs)
starts from Unknown. [Transaction recovery](https://github.com/telemt/telemt/blob/94f4f7d5401a28afb6e6f4a7d66d6f56259c6c5d/src/conntrack_control/firewall/transaction.rs)
cleans nft and iptables state even for Empty policy. Setting inline control false
does not reliably avoid cleanup in 3.5.11; 3.5.12 changes admission as described
above. The [3.5.11 command parser](https://github.com/telemt/telemt/blob/94f4f7d5401a28afb6e6f4a7d66d6f56259c6c5d/src/conntrack_control/firewall/command.rs)
classifies the exact missing-owned-chain diagnostic as NotFound for bounded
raw-table cleanup/check commands. [PR #939](https://github.com/telemt/telemt/pull/939)
fixes the observed `Chain 'TELEMT_NOTRACK' does not exist` recovery failure.

The exact 3.5.10 -> 3.5.11 diff changes only Cargo version/lock metadata, firewall
command error classification and its regression tests (five files, three commits).
Owned raw-table PREROUTING jump -C/-D and owned-chain -F/-X accept absence; install
commands, foreign targets, mixed diagnostics, permissions, lock and timeout errors
remain failures. Actor/transaction logic is unchanged: previously Unknown recovery
failed, marked apply_ok=false and retried at 1/2/4/8/16/30 seconds, capped at 30.
A serving listener was insufficient evidence of settled background reconciliation.
The old green 3.5.10 smoke ran after 3.5.11 was already published at 23:11 Moscow
on 1 October 2026. Its missing-chain WARN/retries are historical degraded evidence.
The historical annotated 3.5.11 tag is GitHub verified=true, reason=valid and resolves to
`94f4f7d5401a28afb6e6f4a7d66d6f56259c6c5d`. This reports GitHub verification, not independent signing
key verification.

Generated policy stays inline enabled, tracked. `nft`, `iptables`, `ip6tables`,
`conntrack`, default systemd PATH checks, CAP_NET_ADMIN and actual service-process
capability validation are retained. The manager creates no permanent firewall rules.
CAP_NET_ADMIN grants broad network authority; tracked mode does not remove that risk.

The old version/Ubuntu/backend/message-specific exception and `known_nonfatal`
accounting are removed. Severity is parsed from each record's anchored prefix;
all WARNs count as diagnostics even with `error=`, permission errors or conntrack
text. ERROR/FATAL and genuine Rust panic prefixes fail regardless of WARN words
in their payload. Embedded structured fatal lines cannot hide in a multiline WARN.
Only ANSI SGR colors are stripped; other unsafe controls and malformed journal JSON
fail closed. Trusted PID1/systemd lifecycle records are separated by journald
metadata. The unlevelled `MAESTRO: ` startup banner is recognized by its framing,
never by link/user payload and never printed. No version/OS/backend inputs exist.

Upstream [logging](https://github.com/telemt/telemt/blob/c4555e25f39dd5be200ccf6353f7d82bfcf89131/src/logging.rs)
uses the tracing fmt default stdout writer for the destination named stderr;
the MAESTRO banner actually uses stderr. The runtime smoke captures both streams,
as journald does, and unsets inherited Cloud RUST_LOG so generated normal logging
is exercised. Raw logs and generated private WEB links stay in private temporary
files. Only counts and explicitly safe fragments enter CI logs.

The historical sanitized seven-WARN 3.5.10 live fixture must produce `errors=0, warnings=7` for raw
and journal JSON transport. Appending actual ERROR/FATAL/panic produces failure.
WARN alone never overrides process, PID/listener, UID/capabilities, HTTP/TLS, decoy,
SOCKS, strict configuration or hash failures.

## What the evidence proves

Earlier green checks combined real config healthcheck with mocked service/readiness,
path health and journal transport. The old conntrack bridge used a synthetic WARN
and 3.5.9 classifier input while fresh download selection moved. Neither ran the
new downloaded release. These labels and future-version acceptance fixtures have
been corrected. Healthcheck with API disabled loads config; it does not prove a
running listener. [Complete CI truth table](CI-COVERAGE.md).

The smoke runs the verified 3.5.12 process in a new Linux network namespace with
real helpers and CAP_NET_ADMIN; verifies PID-owned socket and actual HTTP 200/index,
proves owned chains absent before startup and rechecks listener/HTTP after a
measured >=10-second readiness dwell (covering the old 1/2/4-second retries).
Captured output must contain no failed conntrack reconciliation, initial failure,
background retry, shutdown-clear or cleanup-incomplete fragments. These strings
are pinned-upstream runtime assertions only; production WARN remains generic.
It classifies actual logs, injects fatal classifier negatives, requires clean
shutdown and inspects nft/IPv4/IPv6 state for Telemt-owned names.
Namespace destruction isolates all firewall effects. No skip or mocked fallback
is permitted. It does not cover systemd sandbox execution, public DNS/ACME, external
TLS, Telegram clients, real SOCKS egress or a VPS host's firewall coexistence.

## Pin freshness during maintenance

Query the official `telemt/telemt/releases/latest` at task start and immediately
before the final report. If it changes, stop and inspect release notes/diff for
pin, known live failure, security and compatibility impact; do not silently chase
it or finalize a pin superseded by a release fixing a known blocker. This is a
maintenance process check, never a moving production download dependency.

## Historical source inventory and retained recovery safeguards

The following path/security inventory records the earlier 3.5.9 source review.
It is historical source evidence, not the current download policy or a promise of
future release compatibility. Current 3.5.12 healthcheck and runtime smoke add
release-specific evidence. Successful 0.1.2 VPS acceptance under systemd on Ubuntu
26.04.1 LTS x86_64 is recorded in the [English README](../README.en.md#vps-validation);
the historical source review and CI do not establish other deployment combinations.

## Runtime paths and systemd audit, full second review

Historical review: rechecked official stable/main and both 3x-ui-pro scripts before
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

The current reviewed xPROMSx/3x-ui-auto-nginx Fresh Install script emits `sites-available/80.conf`: one IPv4
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
are used. Free port 80 retains standalone mode. Real ACME issuance, renewal dry-run
and Telemt restart were verified in the recorded 0.1.2 live acceptance, not by CI.
That evidence does not establish power-loss/reboot persistence or every renewal mode.

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
  runtime compatibility is now checked directly and enforced by the systemd sandbox.

Existing safeguards retained: HTTPS-only release/redirect protocols, exact official
asset URL and unambiguous digest, no candidate execution before verification,
root-only config/backups/staging, suppressed candidate diagnostics and raw journals,
signal rollback, managed manifest/hash checks and required public HTTPS probe.
No production VPS or secrets were used. See both READMEs for intentional boundaries.

## Current 3x-ui topology and quota compatibility review

The mandatory topology fixture uses `xPROMSx/3x-ui-auto-nginx` `x-ui-latest.sh`,
commit `59ff07f3bfeaf4b33bc5d803dfe9a3334ab8c1fd`, Git blob
`c19f7c2116adf41dcc7509fd47ecf2c64f5c1c81`. Only inert Nginx heredocs are rendered;
the installer is not executed. Supported order is 3x-ui Fresh Install followed
by manager Install. A deliberate 3x-ui full rebuild removes existing routes and
requires Telemt installation/integration again. `x-ui-patch.sh` is not mandatory.
Historical reviews above remain records of their original revisions.

Official `src/quota_state.rs` is byte-identical between 3.5.12 and 3.5.13
(SHA256 `ea39da751a742ba2df59fc2ef364c0bc04c1e305b214070c776b23fefcafd26e`).
Telemt derives the top-level reset timestamp from user records on save. Rehearsal
uses actual cloned stopped DATA; quota preservation compares existing per-user
used_bytes/reset semantics, not derived top-level metadata. Synthetic non-empty
quota belongs only to separate CI fixtures. Owner live acceptance of this quota
follow-up remains pending; the previous refusal rolled back safely to 3.5.12.


## Static cover behavior (1.0.0)

Reviewed baseline 3.5.12 source at
`c4555e25f39dd5be200ccf6353f7d82bfcf89131`: `src/config/load/runtime_web.rs`
loads bounded no-follow static files into `WebStaticAsset.body` at config load;
`src/web/http/decoy.rs` serves cached bytes. Therefore atomic index replacement
requires a verified Telemt restart, rather than assuming per-request disk reads.
The existing real namespace runtime smoke verifies both cached-before-restart and
new-cover-after-restart behavior. TOML/static_directory and Nginx remain unchanged.

Three HTML/CSS covers were copied from read-only companion
`xPROMSx/3x-ui-auto-nginx` commit `59ff07f3bfeaf4b33bc5d803dfe9a3334ab8c1fd`,
site-02/site-03/site-04. Their source copies, size/SHA256 manifest and embedded
helper bundle are manager-owned and mechanically matched. No runtime dependency,
remote content, third-party script or new bootstrap component is introduced.
