from google_ads_mcp.harness import Finding, fingerprint, review_diff


def test_fingerprint_stable() -> None:
    findings = [
        Finding("high", "ruff", "boom", "src/a.py"),
        Finding("medium", "ssrf", "url", "src/b.py"),
    ]
    assert fingerprint(findings) == fingerprint(list(reversed(findings)))


def test_review_diff_flags_secret_and_ssrf() -> None:
    diff = """
+++ b/src/google_ads_mcp/leaky.py
+refresh_token: ya29.very-secret-token-value
+from urllib.request import urlopen
+urlopen('http://169.254.169.254/')
"""
    rules = {item.rule for item in review_diff(diff)}
    assert "secrets" in rules
    assert "ssrf" in rules


def test_review_diff_allows_hardened_https_fetch() -> None:
    diff = """
+++ b/src/google_ads_mcp/tools/assets.py
+if parsed.scheme != "https":
+    raise ValueError("Only https URLs are allowed")
"""
    assert review_diff(diff) == []
