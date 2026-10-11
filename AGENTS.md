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
