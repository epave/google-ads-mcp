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

Do not add mutate tools that skip `SafetyGate`. New campaigns stay paused. Image fetches stay https/public and rooted under `GOOGLE_ADS_ASSET_ROOT`.
