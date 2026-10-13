# Claude Code orientation

Read [AGENTS.md](AGENTS.md), [CONTRIBUTING.md](CONTRIBUTING.md) and the relevant
[operations/security contracts](docs/OPERATIONS.md) before making changes.
AGENTS.md and this guide express the same project policy and receive equal
maintenance attention. Keep them consistent; user-authorized task scope takes
precedence. Do not infer current behavior from historical acceptance records.

## What this project does

Telegram Web Proxy Manager manages a Telegram HTTPS WEB proxy on an Ubuntu VPS.
It installs/configures Telemt as the engine, integrates with an existing supported
Nginx SNI router, obtains or reuses validated Let's Encrypt certificates, provides
a secret `tg://webproxy?...` connection link and serves a local cover page.
Connectivity can be direct or through supported SOCKS5. It does not install
Nginx, Xray or 3x-ui, change their databases or configure host firewall policy. Telemt itself uses CAP_NET_ADMIN for its
owned conntrack/firewall state; this is not a promise of no kernel-level effects.
3x-ui Auto Nginx is optional: install that project first, then this manager.
A destructive rebuild of the neighboring project is not an automatic cross-project
recovery workflow.

Current source versions are manager `1.1.2` and Fresh Install Telemt `3.5.12`.
Check the shell/helper constants before updating guidance: they must agree, and
historical records/pins must not be changed by blanket replacement.
Production requires root, active systemd, Ubuntu 24.04/26.04, Bash 5+ and Python
3.11+. Preflight accepts x86_64 and aarch64/arm64. Ubuntu 26.04 is the primary
system test and 24.04 the compatibility test. ARM CI verifies official executables
under qemu-user; it does not establish native ARM VPS/systemd acceptance.

## Code and state map

| Path | Responsibility |
| --- | --- |
| `install.sh` | Official manager source resolution, static pair validation, locked atomic installation and both launchers |
| `telemt-web-manager.sh` | Public menu/CLI, preflight and Install/Update/Check/Repair/Uninstall orchestration |
| `lib/safety.py` | Strict config/Nginx/renewal parsers, ownership, cover bytes, provenance, transaction/isolation/recovery APIs |
| `assets/fake-sites/` | Local HTML/CSS/manifest sources matching the embedded helper collection |
| `tests/`, `tests/suites.json` | Existing discovery, standalone suites, fixtures and mechanically checked CI reachability |
| `.github/workflows/checks.yml` | Exact-revision plan, identity/static/regression/integration/system jobs and final required gate |
| `.github/workflows/telegram-release.yml` | Release announcements/manual notification; never invoke it as validation |
| `docs/` | Detailed operations, evidence, upstream sources and support information |

The canonical CLI is `telegram-web-proxy-manager`; `telemt-web-manager` remains a
compatibility command. Both execute the same pair in `/opt/telemt-web-manager`.
Internal names are intentionally retained: state `/var/lib/telemt-web-manager`,
lock `/run/lock/telemt-web-manager.lock`, ACME root
`/var/lib/telemt-web-manager-acme`, Nginx filenames, deploy hook and systemd
recovery/drop-in identities. Do not rename them without a separately authorized,
backward-compatible migration. Telemt itself remains the upstream service/binary.

Telemt uses `/etc/telemt/telemt.toml`, `/usr/local/bin/telemt`, `telemt.service`
and DATA under `/var/lib/telemt`. Only its `state` subtree is service-writable;
cover files remain root-owned. Private backups under `/root/telemt-backups` may
contain credentials. Receipts, manifests, journal and generation records establish
ownership; matching names alone do not. The existing public :443 stream router sends the Telegram domain to the managed
loopback HTTPS frontend on :7444, which proxies to Telemt on :18080. Keep that
trusted loopback boundary. Follow OPERATIONS for exact permissions.

## Contracts that must survive changes

- Ordinary bootstrap verifies official repository/owner identity, resolves `main`
  once and downloads both files from the same immutable SHA. `--version` resolves
  only an explicitly requested published release/tag. Versions are read as data,
  never by executing candidates; Bash/Python must agree. Completion and automatic
  downgrade protection use the actual content version, not a historical tag name.
  Preserve safe paths/modes, shared lock, recovery/schema barrier and atomic
  pair/launcher rollback; unrelated existing files must never be overwritten.
- Fresh Install uses the exact verified Telemt baseline artifacts. Universal
  Update discovers the newest official stable compatible release across SemVer
  series, checks provenance and isolated compatibility before activation, and
  preserves configuration/deployment controls. No arbitrary engine downloads,
  unchecked latest URL, automatic TOML migration or unmanaged adoption.
- Update preserves full stopped DATA snapshots, journal/receipt/generation
  contracts, start gate, LKG, 150+45-second acceptance and rollback/recovery.
  Unknown or critical state needs manual review; never delete a journal or mix
  old/new files to force success. Fresh Install/Uninstall/manager bootstrap do not
  inherit all Universal Update power-loss guarantees; consult the documented bounds.
- Check performs verification without repairing deployment state. Repair only
  restarts/reloads already verified services. Uninstall needs confirmation and
  proven ownership, retains manager/backups/certificates by default, and preserves
  rollback. Optional certificate deletion is separately ownership-checked.
- Nginx supports exact recognized SNI/HTTP profiles and preserves existing routes.
  The Telegram domain must be unused. Keep verified loopback/PROXY boundaries and
  local/public TLS checks; no `--insecure`, arbitrary routing or permissive parser.
  Fresh HTTPS readiness waiting is bounded, not a global retry policy.
- TLS validates trust, hostname, certificate/key pairing, safe Certbot paths,
  ownership and renewal contracts. Telemt keeps its own ACME webroot and canonical
  deploy hook; it does not adopt 3x-ui's `/var/www/acme` or manage global renewal
  timers. Unknown renewal/hook state is not silently rewritten.
- Cover pages use bounded verified manager-owned bytes and local `/cover.css`;
  no external resources or weakened CSP. Cover changes atomically replace only
  known HTML after stylesheet/ownership checks. Telemt caches static assets, so
  the existing verified restart/restoration path is necessary. Update preserves
  both HTML and CSS through the full DATA contract.

## Tests and CI

Read [CI-COVERAGE.md](docs/CI-COVERAGE.md) for what each REAL/MOCK test proves.
A bug needs a failing contract regression before the fix, then the same regression
and relevant suite PASS. Keep the existing framework, negative/fault-injection
coverage and root-only fixtures; do not replace real tests with mocks.

Useful checks are listed in AGENTS.md. `tests/run.sh` runs
`python3 -m unittest discover -s tests -p 'test_*.py' -v` plus shell contracts;
CI runs it as root. Standalone shell/Python tests, helpers and fixtures must be
classified in `tests/suites.json`, and `tests/ci_manifest.py` verifies execution
edges. Root/runtime suites belong on authorized disposable runners, not a live VPS.
Bash syntax, ShellCheck, Python syntax, pinned actionlint, documentation/pin checks
and `test_ci*.py` regressions form Static. Use the current workflow as the command
source for provenance, lifecycle, Nginx, QEMU and ARM integration prerequisites.

Only the three whitelisted READMEs and `docs/**` select DOCS_ONLY. AGENTS.md,
CLAUDE.md, CONTRIBUTING.md, other translations and unknown/mixed paths select FULL.
Plan, Commit identity and Static are mandatory in both modes. FULL also runs
Regression, Telemt/Lifecycle/Nginx integration, parallel Ubuntu 26.04/24.04 QEMU
and ARM64; `CI / Required` rejects failures, cancellations, missing jobs and
unexpected skips. Preserve exact checkout, pinned actions, read-only permissions,
protected job names and scope policy. No live ACME or real Telegram client result
is implied by local HTTP/Nginx or mocked Certbot tests.

## Privacy, Git and release boundaries

Treat private identities, keys, WEB links, SOCKS credentials, raw logs and backup
contents as private. Use invented examples, sanitized diagnostics and fixed safe
errors. Review tracked/diff content and both author and committer metadata before
publication. Report possible existing disclosures privately by file/category and
severity; never repeat their values in a public PR, fixture or CI output. Preserve
intentionally public contact/funding links and required upstream attribution.

For agent-created commits set repository-local, never global, identity:

```sh
git config --local user.name "xPROMSx"
git config --local user.email "102687702+xPROMSx@users.noreply.github.com"
```

Both author and committer must use that public identity. Reuse
`tests/ci_git_identity.py`: PR-only `base..head` validation checks both identities,
allows approved GitHub noreply/web/bot formats and emits non-disclosing errors.
The identity job fetches full history and is a required dependency. This privacy
lint does not prove GitHub account ownership or recheck historic upstream commits.
Do not replace it or rewrite published history without explicit authorization.

Fetch/record an exact base, use a focused branch and PR, review actual changed
files, verify new commit metadata before push and after publication, and report
only executed tests and actual exact-HEAD results. Preserve GPL-3.0 licensing and
upstream attribution; verify local contracts before copying external material.
READMEs explain the product; OPERATIONS defines lifecycle/security, CI-COVERAGE
records evidence/limitations, UPSTREAM records provenance and historical review.
Keep public descriptions short and free of private audit findings.

Before a proposed release, check the explicitly intended tag against actual source
versions with `bash tests/bootstrap_versions.sh --release-tag v1.1.2` (for that
version). The check does not publish anything or replace maintainer approval.
Do not merge, publish tags/releases, change settings, trigger announcements or
operate on live VPS/certificates/secrets unless explicitly requested. Stop at the
requested PR/audit boundary; do not claim unfinished hosted CI or live acceptance
passed. No unrequested production-state mutation.
