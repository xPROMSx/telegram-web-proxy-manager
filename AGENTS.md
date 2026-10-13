# Repository privacy and Git metadata

- Treat personal data as private by default. Do not add private names, email addresses, phone numbers, contact details, home addresses, account/payment details, IPs tied to individuals, or other private identifiers to commits, PR titles/descriptions, code, documentation, tests, fixtures, or CI logs. Use invented examples (e.g. `example.invalid`) and redact diagnostics; ask before any necessary disclosure.
- Before committing or publishing, review the diff and Git author **and** committer metadata. Avoid echoing discovered personal information into logs or review comments.
- For Codex-created commits, configure the repository-local Git identity (not the global configuration):
  ```sh
  git config --local user.name "xPROMSx"
  git config --local user.email "102687702+xPROMSx@users.noreply.github.com"
  ```
  Use the same public identity for author and committer; verify with `git log -1 --format='%an <%ae> | %cn <%ce>'` privately before pushing.
- The PR CI checks only commits introduced by the PR. Official GitHub web/bot identities and public GitHub noreply aliases are accepted; historic upstream commits are not rechecked. This is a privacy lint, not proof of GitHub account ownership.
- Never rewrite published Git history to remediate a metadata finding without explicit approval. Fix new/unpublished commits before sharing; if private data has already been published, discuss containment first.

## Project and authoritative references

Telegram Web Proxy Manager installs and manages a Telegram HTTPS WEB proxy on an
Ubuntu VPS. Telemt is the proxy engine; existing Nginx supplies public SNI/TLS
routing and Let's Encrypt certificates. Direct Telegram connectivity or optional
SOCKS5 is supported. Local cover pages use a manager-owned stylesheet and strict
upstream CSP. 3x-ui Auto Nginx is an optional, independently managed neighbor:
prepare it first, then install this manager. Do not modify its repository or state
as an incidental part of work here.

Read [CONTRIBUTING.md](CONTRIBUTING.md) and the relevant parts of
[OPERATIONS.md](docs/OPERATIONS.md), [CI-COVERAGE.md](docs/CI-COVERAGE.md) and
[UPSTREAM.md](docs/UPSTREAM.md) before changing a contract. [CLAUDE.md](CLAUDE.md)
is the matching orientation guide; maintain both agent guides with equal care
and consistent rules. User-authorized scope takes precedence over these defaults.
Source and current workflow establish behavior; historical acceptance records
prove only their recorded revisions, not every future environment.

At this baseline, manager `SCRIPT_VERSION` and `UPDATE_MANAGER_VERSION` are
`1.1.2`. Fresh Install pins Telemt `3.5.12`; Universal Update verifies the newest
official stable compatible version across SemVer series. Do not mass-replace
historical versions or change pins as part of unrelated work.
The production preflight requires root, active systemd, Ubuntu 24.04 or 26.04,
Bash 5+ and Python 3.11+. It accepts x86_64 and aarch64/arm64. Ubuntu 26.04 is the
primary system test; 24.04 is compatibility. ARM CI runs official ARM binaries
under qemu-user, not a native ARM VPS/systemd acceptance.

## Repository responsibilities

- `install.sh`: installs the manager Bash/Python pair and canonical
  `telegram-web-proxy-manager` plus legacy `telemt-web-manager` launchers.
  Ordinary installation resolves verified official `main` to one frozen SHA;
  `--version` resolves only the requested published release/tag. Content versions
  are parsed without executing candidates and must agree between Bash/Python.
  Manager installation is distinct from updating the Telemt engine.
- `telemt-web-manager.sh`: public menu/CLI, dependency and platform preflight,
  lifecycle orchestration, Nginx/TLS integration and safe diagnostics.
- `lib/safety.py`: strict parsers, staged plans, ownership/provenance validation,
  cover assets, Universal Update transaction, isolation and recovery APIs.
- `assets/fake-sites/`: bounded local cover sources/manifest matching the embedded
  helper assets; no external resources or weakening of CSP.
- `tests/`: unittest modules, shell suites, real dependency tests and controlled
  fault-injection fixtures. `tests/suites.json` records execution paths.
- `docs/`: operational/security contracts, evidence and upstream attribution.
  READMEs are user-facing entry points; avoid duplicating internals there.

## Lifecycle and security boundaries

- Mutate only proven manager-owned installations. Preserve exact TOML, service,
  Nginx, certificate, WEB-link and recovery contracts; unknown/changed state
  requires manual review. Check does not repair or migrate state. Repair only
  restarts/reloads verified services; it is not adoption or reconfiguration.
- Keep common locking, safe ancestors, regular/single-link file checks,
  root ownership/modes, staged writes, required fsync and atomic publication.
  Bootstrap pair/launcher failures must preserve or restore the previous pair;
  use actual candidate SemVer for the automatic downgrade guard.
- Preserve receipt/journal/generation schemas, the systemd start gate, recovery
  barrier, full-DATA stopped snapshots, LKG and rollback authority. Universal
  Update isolates candidate execution, proves provenance before execution and
  retains the 150-second stability plus 45-second restarted acceptance.
  Do not delete state to bypass a refusal or mix generations manually.
- Nginx recognizes bounded profiles, not arbitrary routing. Preserve existing
  SNI routes and TLS verification; never use insecure probes to obtain PASS.
  Telemt keeps its own ACME root and canonical deploy hook, does not take over
  3x-ui's webroot and does not create/control a global renewal scheduler.
- Uninstall removes only proven owned Telemt state and requires confirmation;
  it preserves the manager/backups and certificates by default. Certificate
  deletion is separate, explicit and ownership-checked. Preserve its rollback.
- Legacy internal paths, locks, markers, hook and recovery-unit names are
  compatibility ABI. Do not rename them for branding or infer ownership from
  matching filenames/domain names. Keep upstream Telemt attribution and GPL-3.0
  licensing; verify local contracts before importing external material.
- Treat WEB links, raw journals, keys, SOCKS credentials and backups as sensitive.
  Use fixed safe failure categories; do not print untrusted exception payloads
  or raw configurations. Retain meaningful failure/rollback evidence privately.
- Do not run live VPS operations, mutate production state, merge, publish tags or
  releases, change repository settings or send announcements unless explicitly
  authorized. Existing release-announcement automation is not a test command.

## Validation and delivery

Use the existing infrastructure; do not introduce another framework or weaken
assertions to make CI green. Follow CONTRIBUTING's failing-regression-first rule.
Root-dependent fixtures must run on a disposable authorized test runner, never
an existing production VPS. See CI-COVERAGE for REAL/MOCK boundaries: local HTTP
success is not real ACME issuance or Telegram client acceptance.

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

Full root discovery runs through `sudo env PYTHONDONTWRITEBYTECODE=1 bash tests/run.sh`
in CI. Choose additional relevant suites from `tests/suites.json` and the workflow;
do not treat mocks as substitutes for required real integration/system tests.
Use the existing pinned actionlint version/integrity check, not a floating download.
The release-preparation check is `bash tests/bootstrap_versions.sh --release-tag v1.1.2`
for that target version; it must precede publication, not stand in for release approval.

`.github/workflows/checks.yml` runs for PRs and main pushes with exact checkout,
pinned actions, read-only permissions and no persisted checkout credentials.
Only `README.md`, `README.en.md`, `README.ru.md` and `docs/**` select DOCS_ONLY;
all other/mixed/uncertain diffs select FULL. Agent/contributor guides and other
README translations therefore select FULL under the current policy.
Plan, Static and Commit identity are required in both modes. FULL also requires
Regression, Telemt/Lifecycle/Nginx integration, both parallel Ubuntu QEMU suites
and ARM64. `CI / Required` rejects failed/cancelled/missing or unexpectedly skipped
jobs. Do not change protected names, scope, permissions or checkout to bypass it.

Fetch and record the exact base, use a focused branch/PR, review the actual diff
and new commit metadata, and report tests accurately for the exact HEAD. Register
new standalone tests/helpers so the manifest proves a real CI execution path;
`test_*.py` modules use existing discovery. Keep public PR descriptions concise
and free of private findings. Do not rewrite published history or claim pending
CI/live checks passed. Stop at the requested review boundary; no implicit merge.
