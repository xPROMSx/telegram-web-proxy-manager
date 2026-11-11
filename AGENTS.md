# AGENTS.md: single source of project rules

This file is the single source of rules for any coding agent. [CLAUDE.md](CLAUDE.md)
only points here. User-authorized task scope takes precedence over these defaults.
Source and current workflow establish behavior; historical acceptance records
prove only their recorded revisions, not every future environment, and must not
be used to infer current behavior.

## Threat model and simplicity

- One administrator, one own Ubuntu VPS. Not a multi-user service.
- The goal is: it works, and it is easy to maintain. Stability and reliability come from simplicity, not from layers of checks. Fewer lines beat more checks.
- OWN data (created by this manager: state, receipts, journal, generations, and the Telemt configs and files the manager wrote) is validated strictly. Update and rollback depend on it. Do not weaken these checks.
- FOREIGN data (3x-ui, other Nginx routes and vhosts, the administrator's certificates and hooks) must never block an operation. Recognize it by name or marker, then skip or exclude it.
- A new check, guard or refusal is allowed only for a defect reproduced by a failing test (RED test) that is cited in the PR. "It could theoretically happen" is not a reason.
- One failure = one specific message: which check, which file, which value. No generic text covering several checks.
- If two PRs in a row changed the same function, STOP. Do not write a third patch. Report that the mechanism itself should be simplified and propose deleting it.
- A diff that adds more lines than it removes needs an explanation in the report.
- Before adding code, ask whether deleting or simplifying would do. Do not add a check on top of a check to fix a failure: look for a simpler mechanism. A PR that only removes redundant code is valid; removing an existing protection still needs the separate analysis described in the last bullet.
- One source of truth. Do not create a second copy of a contract (rules, version lists, expected config text). If a second copy already exists, prefer removing it.
- This section guides new and changed code. It does not authorize removing or relaxing any existing protection or refusal (for example the bounded Nginx profiles or the refusal on a modified generated site); those stay until a separate task that first explains what the check protected.

## Repository privacy and Git metadata

- Treat personal data as private by default. Do not add private names, email addresses, phone numbers, contact details, home addresses, account/payment details, IPs tied to individuals, or other private identifiers to commits, PR titles/descriptions, code, documentation, tests, fixtures, or CI logs. Use invented examples (e.g. `example.invalid`) and redact diagnostics; ask before any necessary disclosure.
- Treat private identities, keys, WEB links, SOCKS credentials, raw logs and backup contents as private. Use sanitized diagnostics and fixed safe errors.
- Before committing or publishing, review the tracked/diff content and Git author **and** committer metadata. Avoid echoing discovered personal information into logs or review comments.
- Report possible existing disclosures privately by file/category and severity; never repeat their values in a public PR, fixture or CI output. Preserve intentionally public contact/funding links and required upstream attribution.
- For agent-created commits, configure the repository-local Git identity (never the global configuration):
  ```sh
  git config --local user.name "xPROMSx"
  git config --local user.email "102687702+xPROMSx@users.noreply.github.com"
  ```
  Use the same public identity for author and committer; verify with `git log -1 --format='%an <%ae> | %cn <%ce>'` privately before pushing, and again after publication.
- Commits and PR text must not contain Co-Authored-By, Claude-Session or "Generated with" lines. If the platform or tool adds them by default, remove them before pushing, and re-read the PR description after creating the PR because the platform may add a signature there.
- The PR CI checks only commits introduced by the PR (`base..head`, both identities) through `tests/ci_git_identity.py`; reuse it, do not replace it. Official GitHub web/bot and public GitHub noreply formats are accepted, errors do not disclose values, and historic upstream commits are not rechecked. The identity job fetches full history and is a required dependency. This is a privacy lint, not proof of GitHub account ownership.
- Never rewrite published Git history to remediate a metadata finding without explicit approval. Fix new/unpublished commits before sharing; if private data has already been published, discuss containment first.

## Project and authoritative references

Telegram Web Proxy Manager installs and manages a Telegram HTTPS WEB proxy on an
Ubuntu VPS. It installs/configures Telemt as the engine, integrates with an existing
supported Nginx SNI router, obtains or reuses validated Let's Encrypt certificates,
provides a secret `tg://webproxy?...` connection link and serves a local cover page.
Connectivity is direct or through supported SOCKS5. Fresh installs use an original
eleven-file static site through Telemt `http_upstream` and an owned loopback Nginx
origin; existing `static_directory` sites remain supported without migration.
It does not install Nginx, Xray or 3x-ui, change their databases or configure host
firewall policy. Telemt itself uses CAP_NET_ADMIN for its owned conntrack/firewall
state; this is not a promise of no kernel-level effects.
3x-ui Auto Nginx is an optional, independently managed neighbor: install that
project first, then this manager. Do not modify its repository or state as an
incidental part of work here. A destructive rebuild of the neighboring project is
not an automatic cross-project recovery workflow.

Read [CONTRIBUTING.md](CONTRIBUTING.md) and the relevant parts of
[OPERATIONS.md](docs/OPERATIONS.md), [CI-COVERAGE.md](docs/CI-COVERAGE.md) and
[UPSTREAM.md](docs/UPSTREAM.md) before changing a contract. READMEs explain the
product; OPERATIONS defines lifecycle/security and exact permissions, CI-COVERAGE
records what each REAL/MOCK test proves and its limitations, UPSTREAM records
provenance and historical review.

The manager version is defined by `SCRIPT_VERSION` in the shell and
`UPDATE_MANAGER_VERSION` in the helper; these values must agree. Fresh Install
pins Telemt through the separate shell/helper baseline constants; Universal
Update verifies the newest official stable compatible version across SemVer series.
Check these sources before updating guidance. Do not mass-replace historical
versions/records or change pins as part of unrelated work.
The production preflight requires root, active systemd, Ubuntu 24.04 or 26.04,
Bash 5+ and Python 3.11+. It accepts x86_64 and aarch64/arm64. Ubuntu 26.04 is the
primary system test; 24.04 is compatibility. ARM CI runs official ARM binaries
under qemu-user, not a native ARM VPS/systemd acceptance.

## Repository responsibilities

- `install.sh`: official manager source resolution, static pair validation, locked
  atomic installation of the manager Bash/Python pair and the canonical
  `telegram-web-proxy-manager` plus legacy `telemt-web-manager` launchers.
  Ordinary installation resolves verified official `main` to one frozen SHA;
  `--version` resolves only the requested published release/tag. Content versions
  are parsed without executing candidates and must agree between Bash/Python.
  Manager installation is distinct from updating the Telemt engine.
- `telemt-web-manager.sh`: public menu/CLI, dependency and platform preflight,
  Install/Update/Check/Repair/Uninstall orchestration, Nginx/TLS integration and
  safe diagnostics.
- `lib/safety.py`: strict config/Nginx/renewal parsers, staged plans,
  ownership/provenance validation, cover bytes/assets, Universal Update
  transaction, isolation and recovery APIs.
- `assets/cover-sites-v0.3/`: verbatim approved generator, validator and CSS sources;
  integrity-checked resources are embedded in the helper to preserve the two-file
  bootstrap. Only eleven generated files are public.
- `assets/fake-sites/`: historical static_directory test fixtures only, not
  production generation; never generate or rotate old covers.
- `tests/`: unittest modules, shell suites, real dependency tests, fixtures and
  controlled fault-injection. `tests/suites.json` records execution paths.
- `.github/workflows/checks.yml`: exact-revision plan, identity/static/regression/
  integration/system jobs and the final required gate.
- `.github/workflows/telegram-release.yml`: release announcements and manual
  notification; never invoke it as validation.
- `docs/`: operational/security contracts, evidence, upstream sources and support
  information. READMEs are user-facing entry points; avoid duplicating internals there.

The canonical CLI is `telegram-web-proxy-manager`; `telemt-web-manager` remains a
compatibility command. Both execute the same pair in `/opt/telemt-web-manager`.
Internal names are intentionally retained as compatibility ABI: state
`/var/lib/telemt-web-manager`, lock `/run/lock/telemt-web-manager.lock`, ACME root
`/var/lib/telemt-web-manager-acme`, Nginx filenames, deploy hook, markers and
systemd recovery/drop-in identities. Do not rename them for branding without a
separately authorized, backward-compatible migration. Telemt itself remains the
upstream service/binary.

Telemt uses `/etc/telemt/telemt.toml`, `/usr/local/bin/telemt`, `telemt.service`
and DATA under `/var/lib/telemt`. Only its `state` subtree is service-writable;
cover files remain root-owned. Private backups under `/root/telemt-backups` may
contain credentials. Receipts, manifests, journal and generation records establish
ownership; matching names alone do not, so never infer ownership from matching
filenames/domain names. The existing public :443 stream router sends the Telegram
domain to the managed loopback HTTPS frontend on :7444, which proxies to Telemt on
:18080. Keep that trusted loopback boundary.

## Lifecycle and security boundaries

The no-argument TTY menu selects English or Russian once per invocation, without
persisting a preference. Explicit CLI flags remain English. Keep translations at
human-facing call sites; structured helper responses, state and generated configs
are language-independent. WEB link display requires terminal stdin/stdout/stderr.

- Bootstrap verifies official repository/owner identity, resolves `main` once and
  downloads both files from the same immutable SHA. `--version` resolves only an
  explicitly requested published release/tag. Versions are read as data, never by
  executing candidates; Bash/Python must agree. Completion and automatic downgrade
  protection use the actual content version (actual candidate SemVer), not a
  historical tag name. Preserve safe paths/modes, shared lock, recovery/schema
  barrier and atomic pair/launcher rollback; unrelated existing files must never
  be overwritten. Bootstrap pair/launcher failures must preserve or restore the
  previous pair.
- Fresh Install uses the exact verified Telemt baseline artifacts. Universal Update
  discovers the newest official stable compatible release across SemVer series,
  checks provenance and isolated compatibility before activation, and preserves
  configuration/deployment controls. No arbitrary engine downloads, unchecked
  latest URL, automatic TOML migration or unmanaged adoption.
- Mutate only proven manager-owned installations. Preserve exact TOML, service,
  Nginx, certificate, WEB-link and recovery contracts; unknown or changed state
  requires manual review. Check performs verification without repairing or
  migrating deployment state. Repair only restarts/reloads already verified
  services; it is not adoption or reconfiguration.
- Keep common locking, safe ancestors, regular/single-link file checks,
  root ownership/modes, staged writes, required fsync and atomic publication.
- Update preserves receipt/journal/generation schemas, the systemd start gate,
  recovery barrier, full stopped DATA snapshots, LKG and rollback authority.
  Universal Update isolates candidate execution, proves provenance before execution
  and retains the 150-second stability plus 45-second restarted acceptance.
  Unknown or critical state needs manual review. Never delete a journal or state to
  bypass a refusal, and never mix old/new files or generations to force success.
  Fresh Install, Uninstall and manager bootstrap do not inherit all Universal Update
  power-loss guarantees; consult the documented bounds.
- Nginx recognizes exact bounded SNI/HTTP profiles, not arbitrary routing or a
  permissive parser. Preserve existing SNI routes; the Telegram domain must be
  unused. Keep verified loopback/PROXY boundaries and local/public TLS checks;
  never use `--insecure` or insecure probes to obtain PASS. Fresh HTTPS readiness
  waiting is bounded, not a global retry policy.
- TLS validates trust, hostname, certificate/key pairing, safe Certbot paths,
  ownership and renewal contracts. Telemt keeps its own ACME webroot and canonical
  deploy hook, does not adopt 3x-ui's `/var/www/acme` and does not create/control
  a global renewal scheduler. Unknown renewal/hook state is not silently rewritten.
- Uninstall removes only proven owned Telemt state and requires confirmation;
  it retains the manager, backups and certificates by default and preserves
  rollback. Certificate deletion is separate, explicit and ownership-checked.
- Fresh sites use the approved v0.3 generator once, through native Telemt
  `http_upstream` and an owned loopback Nginx origin on a bounded port chosen at
  fresh install (see OPERATIONS). Publish only the eleven generated files under
  `/var/www/telemt-web-manager`; never change approved content/design/randomization
  casually. Existing `static_directory` sites stay byte-identical, with no
  migration. There is no Change cover site operation. Preserve site ownership and
  strict CSP.
- Treat WEB links, raw journals, keys, SOCKS credentials and backups as sensitive.
  Use fixed safe failure categories; do not print untrusted exception payloads
  or raw configurations. Retain meaningful failure/rollback evidence privately.
- Keep upstream Telemt attribution and GPL-3.0 licensing; verify local contracts
  before importing or copying external material.
- Do not run live VPS operations, mutate production state (VPS, certificates,
  secrets), merge, publish tags or releases, change repository settings or send
  announcements unless explicitly requested. Existing release-announcement
  automation (`telegram-release.yml`) is not a test command.

The generated site is fixed for the installation's lifetime. Its eleven-file digest
is bound by a comment in the exact owned Nginx vhost and the existing manifest hash;
do not change manifest/state schemas. Check, Update and Uninstall refuse modified
or foreign site contents. Bootstrap never generates or changes a site. Update
uses a copy and a temporary, distinct unprivileged Nginx process inside its existing
private namespace/chroot; preserve candidate isolation and all recovery controls.
3X-UI Backup v3 recognition is not compatible with cached/new vhosts yet; a separate
neighbor PR and verification are required before recommending a new TWPM release.
HTTP/WEB test success does not establish DPI resistance or IP-blocking protection.

## Validation and delivery

Use the existing infrastructure; do not introduce another framework or weaken
assertions to make CI green. A bug needs a failing contract regression before the
fix, then the same regression and the relevant suite PASS (see CONTRIBUTING).
Keep negative/fault-injection coverage and root-only fixtures; do not replace real
tests with mocks. Root/runtime suites run only on a disposable authorized test
runner, never an existing production VPS. See CI-COVERAGE for REAL/MOCK
boundaries: local HTTP/Nginx success or mocked Certbot is not real ACME issuance or
Telegram client acceptance.

Useful repository checks:

```sh
for file in install.sh telemt-web-manager.sh tests/*.sh; do bash -n "$file"; done
shellcheck -x install.sh telemt-web-manager.sh tests/*.sh
python3 -m unittest discover -s tests -p 'test_ci*.py' -v
python3 tests/ci_manifest.py
python3 tests/ci_docs.py
bash tests/pinned.sh --docs
git diff --check
```

These, plus Python syntax and the pinned actionlint, form Static. Full root
discovery (`python3 -m unittest discover -s tests -p 'test_*.py' -v` plus shell
contracts) runs through `sudo env PYTHONDONTWRITEBYTECODE=1 bash tests/run.sh` in CI.
Choose additional relevant suites from `tests/suites.json` and the workflow, which
is the command source for provenance, lifecycle, Nginx, QEMU and ARM integration
prerequisites; do not treat mocks as substitutes for required real integration/system
tests. Use the existing pinned actionlint version/integrity check, not a floating
download. Register new standalone shell/Python tests, helpers and fixtures in
`tests/suites.json` so `tests/ci_manifest.py` proves a real CI execution path;
`test_*.py` modules use existing discovery.
The release-preparation check is `bash tests/bootstrap_versions.sh --release-tag vX.Y.Z`
with the agreed target version; it must precede publication, not stand in for release
approval or publish anything.

### Manager release versioning

- The owner agrees the target manager version before preparing a release PR task.
- Change the version in the release PR before merge and publication. Always
  synchronize `SCRIPT_VERSION` and `UPDATE_MANAGER_VERSION`, and update affected
  tests and current documentation together.
- Before publication, run `bash tests/bootstrap_versions.sh --release-tag vX.Y.Z`
  with that target tag. A tag/source mismatch must fail.
- Ordinary functional PRs do not bump the manager version without separately
  agreed release preparation. Manager SemVer, the Fresh Install Telemt baseline
  and the installed Telemt version are independent.
- Never rewrite published tags, historical versions or existing state records
  to make them match the current manager version.

### CI scope

`.github/workflows/checks.yml` runs for PRs and main pushes with exact checkout,
pinned actions, read-only permissions and no persisted checkout credentials.
Only the eight existing READMEs (`README.md`, `README.en.md`, `README.ru.md`,
`README_AR.md`, `README_ES.md`, `README_FA.md`, `README_TR.md`, `README_ZH_CN.md`)
and `docs/**` select DOCS_ONLY. AGENTS.md, CLAUDE.md, CONTRIBUTING.md and
unknown/mixed/uncertain paths select FULL. New commits cancel unfinished runs of
the same PR; unique main-push groups preserve both running and pending main checks.
Plan, Commit identity and Static are mandatory in both modes. FULL also runs
Regression, Telemt/Nginx integration, Lifecycle plus independent standard/includes
Uninstall jobs, parallel Ubuntu 26.04/24.04 QEMU and ARM64. `CI / Required` rejects
failures, cancellations, missing jobs and unexpected skips. Do not change protected
job names, scope policy, permissions or checkout to bypass it.

### Delivery

Fetch and record the exact base, use a focused branch and PR, review the actual
changed files and new commit metadata, and report only executed tests and actual
exact-HEAD results. Keep public PR descriptions concise and free of private
findings. Do not rewrite published history or claim unfinished hosted CI or live
acceptance passed. Stop at the requested PR/audit boundary; no implicit merge.

Every PR states its verification level: 0 CI only; 1 one command on a ready test server; 2 full test on a clean VPS (required before a release and for changes to Update, rollback, TLS or Nginx integration).

## Independent integration management

Telegram Manager remains an independent project. The 3X-UI menu entry
`4. Telegram Web Proxy Manager` downloads the official root `install.sh` from
current TWPM `main` over HTTPS on each invocation. First installation requires
confirmation; an existing manager receives a pair update without repeating that
confirmation. Bootstrap resolves current `main` to one exact SHA and verifies
both components before installation, then opens the menu with terminal streams
preserved. Equal manager versions may reinstall. Download/validation/installation
failure preserves the previous pair and does not automatically launch it;
manual `telegram-web-proxy-manager` remains available. Preserve this accepted
HTTPS/current-main trust model without a fixed bootstrap pin, cache or fallback.
Source is never copied into the 3X-UI repository. Install, Check, Update, Repair, Uninstall and Telemt updates
remain Telegram Manager functions. Routine manager fixes need no companion 3X-UI
PR: each project owns its services, certificates, configuration and data.
No new CLI flags, bootstrap auto-update or synchronized releases are required.
