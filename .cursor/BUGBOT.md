# Bugbot rules for google-ads-mcp

- Every write tool must go through `SafetyGate.authorize_write`.
- `confirm_token` must bind tool, customer, and the full argument payload. Reject mismatches without consuming the token.
- Applying a write requires `dry_run=false`. `dry_run=true` plus a token is an error.
- Campaign creates must stay `PAUSED`. Enabling spend is a separate status call.
- Image `source` URLs must be https, public-IP only, no redirects. Local files must stay under `GOOGLE_ADS_ASSET_ROOT`.
- Do not commit `google-ads.yaml`, refresh tokens, or DuckDB state files.
- Prefer DuckDB 2.0 (`duckdb>=2.0.0.dev0` with `prerelease = "allow"`) for local audit/snapshots.
