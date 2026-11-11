# Regression policy

A bug found manually, on a VPS or during independent review is closed only
after a regression test reproduces the violated contract.

Expected sequence:

`BUG → failing regression → fix → regression PASS → relevant suite PASS`

Test observable behavior, not an incidental implementation detail. Register new
standalone tests in `tests/suites.json`; keep helpers explicitly classified.

Before contributing, read [AGENTS.md](AGENTS.md) for project contracts, CI scope,
privacy and public Git identity requirements ([CLAUDE.md](CLAUDE.md) only points
to it). Follow [OPERATIONS.md](docs/OPERATIONS.md) for lifecycle/security changes.
