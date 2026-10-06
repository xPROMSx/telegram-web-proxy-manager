# Manager-owned cover bundle

Three self-contained HTML/CSS pages, copied unchanged from
`xPROMSx/3x-ui-auto-nginx` commit
`59ff07f3bfeaf4b33bc5d803dfe9a3334ab8c1fd`,
`assets/fake-sites/site-02`, `site-03`, and `site-04` (`index.html`).
The companion repository is a read-only source reference, never a runtime source.

`manifest.json` is bounded schema 1: each stable ID has a byte size and SHA256.
The identical manifest and HTML bytes are embedded as `COVER_BUNDLE` in the canonical
`lib/safety.py` helper. The existing atomic manager-pair bootstrap therefore ships
the collection from the same exact manager commit, without additional downloads
or a third installed component. A mechanical test verifies source/bundle parity.

Only local HTML/CSS is accepted; there are no scripts, forms, trackers or external
resources. The built-in Service Status page is the default/fallback. Covers are
ordinary decoy pages, not a claim of traffic invisibility or DPI bypass.
