# google-ads-mcp

## Build

```bash
uv sync --extra dev --prerelease=allow
uv run ruff check src tests
uv run pytest
uv run google-ads-mcp-harness --max-rounds 3 --fix
```

## Review harness

The harness is part of CI. It runs ruff, pytest, and a diff checklist, then repeats until findings are gone or the fingerprint stops changing (max 3 rounds).

```bash
# Current checkout
uv run google-ads-mcp-harness --max-rounds 3 --fix

# Every open GitHub PR
uv run google-ads-mcp-harness --all-open --max-rounds 3
```

High-severity leftover findings fail the build. After changing a PR, re-run the harness and treat review comments until it reports clean or a stable non-high fingerprint.

## Writes

Do not add mutate tools that skip `SafetyGate`. New campaigns, ad groups, and keywords stay paused. Image fetches stay https/public and rooted under `GOOGLE_ADS_ASSET_ROOT`. `REMOVED` requires `force=true`.

## GitHub CLI

Use the personal account, not the default `gh` login. In this repo (and other `~/personal` work) run `gh-personal` (alias: `GH_CONFIG_DIR=~/.config/gh-personal command gh`). Cursor shells often skip zsh aliases, so prefer the `GH_CONFIG_DIR=... command gh` form for issues, PRs, and pushes.
