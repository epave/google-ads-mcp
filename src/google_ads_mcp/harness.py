"""Build review harness: lint/test + checklist review until findings stabilize."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

MARKER = "<!-- google-ads-mcp-harness -->"
SECRET_RE = re.compile(
    r"(?i)(refresh_token|client_secret|developer_token)\s*[:=]\s*['\"]?(ya29\.|[A-Za-z0-9_-]{20,})"
)
WRITE_TOOL_RE = re.compile(r"^def (create_|set_|update_|add_|upload_)")


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    path: str | None = None

    def key(self) -> str:
        return f"{self.severity}|{self.rule}|{self.path or ''}|{self.message}"


@dataclass
class ReviewReport:
    target: str
    rounds: int
    converged: bool
    clean: bool
    fingerprint: str
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "rounds": self.rounds,
            "converged": self.converged,
            "clean": self.clean,
            "fingerprint": self.fingerprint,
            "findings": [asdict(item) for item in self.findings],
        }

    def markdown(self) -> str:
        status = "clean" if self.clean else ("stable" if self.converged else "open")
        lines = [
            MARKER,
            f"## Review harness ({self.target})",
            f"Rounds: {self.rounds} · converged: {self.converged} · status: **{status}** · `{self.fingerprint}`",
            "",
        ]
        if not self.findings:
            lines.append("No findings.")
            return "\n".join(lines)
        lines.append("| Severity | Rule | Path | Message |")
        lines.append("|---|---|---|---|")
        for item in self.findings:
            lines.append(f"| {item.severity} | {item.rule} | {item.path or '—'} | {item.message} |")
        return "\n".join(lines)


def fingerprint(findings: list[Finding]) -> str:
    payload = "\n".join(sorted(item.key() for item in findings))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)


def collect_ci_findings(root: Path, *, fix: bool) -> list[Finding]:
    findings: list[Finding] = []
    ruff_cmd = ["uv", "run", "ruff", "check", "src", "tests"]
    if fix:
        ruff_cmd.append("--fix")
    ruff = _run(ruff_cmd, root)
    if ruff.returncode != 0:
        findings.append(
            Finding("high", "ruff", (ruff.stdout or ruff.stderr).strip().splitlines()[-1], "src")
        )
    pytest = _run(["uv", "run", "pytest", "-q"], root)
    if pytest.returncode != 0:
        tail = (pytest.stdout or pytest.stderr).strip().splitlines()
        findings.append(Finding("high", "pytest", tail[-1] if tail else "pytest failed", "tests"))
    return findings


def review_diff(diff: str) -> list[Finding]:
    findings: list[Finding] = []
    current_path: str | None = None
    added_by_file: dict[str, list[str]] = {}
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_path = line[6:]
            added_by_file.setdefault(current_path, [])
            continue
        if current_path and line.startswith("+") and not line.startswith("+++"):
            added_by_file[current_path].append(line[1:])

    for path, lines in added_by_file.items():
        text = "\n".join(lines)
        if SECRET_RE.search(text) and "example" not in path and not path.endswith(".md"):
            findings.append(Finding("high", "secrets", "Possible live credential in the diff", path))
        if path.endswith(".yaml") and "refresh_token:" in text and "YOUR_" not in text:
            findings.append(Finding("high", "secrets", "google-ads yaml with a refresh token", path))
        if "urlopen(" in text and "https" not in text and path.endswith(".py"):
            findings.append(Finding("medium", "ssrf", "urlopen without an https-only guard", path))
        if WRITE_TOOL_RE.search(text) and "SafetyGate" not in text and path.startswith("src/google_ads_mcp/tools/"):
            if any(name in text for name in ("create_", "set_", "update_", "add_", "upload_")):
                if "authorize_write" not in text and "SafetyGate" not in "\n".join(added_by_file.get(path, [])):
                    # only flag if the file additions include a write def without authorize_write nearby
                    if "def create_" in text or "def set_" in text or "def update_" in text:
                        if "authorize_write" not in text:
                            findings.append(
                                Finding("high", "safety-gate", "Write tool added without authorize_write", path)
                            )
        if "builders/" in path and "CampaignStatusEnum.ENABLED" in text and "PAUSED" not in text:
            findings.append(Finding("high", "paused-create", "Campaign create sets ENABLED", path))
    return findings


def review_tree(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    diff = _run(["git", "diff", "--", "main...HEAD"], root)
    payload = diff.stdout or _run(["git", "diff"], root).stdout
    if payload:
        findings.extend(review_diff(payload))
    return findings


def review_until_convergence(
    root: Path,
    *,
    target: str = "HEAD",
    max_rounds: int = 3,
    fix: bool = False,
    extra: list[Finding] | None = None,
) -> ReviewReport:
    previous: str | None = None
    last: list[Finding] = []
    rounds = 0
    for rounds in range(1, max_rounds + 1):
        last = collect_ci_findings(root, fix=fix)
        last.extend(review_tree(root))
        if extra:
            last.extend(extra)
        last = _dedupe(last)
        current = fingerprint(last)
        if not last or current == previous:
            return ReviewReport(
                target=target,
                rounds=rounds,
                converged=True,
                clean=not last,
                fingerprint=current,
                findings=last,
            )
        previous = current
        if not fix:
            break
    return ReviewReport(
        target=target,
        rounds=rounds,
        converged=False,
        clean=not last,
        fingerprint=fingerprint(last),
        findings=last,
    )


def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen: set[str] = set()
    unique: list[Finding] = []
    for item in findings:
        if item.key() in seen:
            continue
        seen.add(item.key())
        unique.append(item)
    return unique


def list_open_prs() -> list[dict[str, Any]]:
    result = subprocess.run(
        ["gh", "pr", "list", "--state", "open", "--json", "number,title,url,headRefName,isDraft"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh pr list failed")
    return json.loads(result.stdout)


def review_open_prs(root: Path, *, max_rounds: int, current_ref: str | None = None) -> list[ReviewReport]:
    reports: list[ReviewReport] = []
    for pr in list_open_prs():
        diff = subprocess.run(
            ["gh", "pr", "diff", str(pr["number"])],
            text=True,
            capture_output=True,
            check=False,
        )
        extra = review_diff(diff.stdout or "")
        if current_ref and pr.get("headRefName") == current_ref:
            reports.append(
                review_until_convergence(
                    root,
                    target=f"PR #{pr['number']}",
                    max_rounds=max_rounds,
                    extra=extra,
                )
            )
        else:
            findings = _dedupe(extra)
            reports.append(
                ReviewReport(
                    target=f"PR #{pr['number']} {pr['title']}",
                    rounds=1,
                    converged=True,
                    clean=not findings,
                    fingerprint=fingerprint(findings),
                    findings=findings,
                )
            )
    return reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review harness for google-ads-mcp")
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--fix", action="store_true", help="Auto-apply ruff fixes between rounds")
    parser.add_argument("--all-open", action="store_true", help="Review every open GitHub PR")
    parser.add_argument("--output", type=Path, help="Write JSON report")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if args.all_open:
        ref = _run(["git", "branch", "--show-current"], root).stdout.strip()
        reports = review_open_prs(root, max_rounds=args.max_rounds, current_ref=ref)
    else:
        reports = [review_until_convergence(root, max_rounds=args.max_rounds, fix=args.fix)]

    payload = [report.to_dict() for report in reports]
    text = "\n\n".join(report.markdown() for report in reports)
    print(text)
    if args.output:
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0 if all(report.clean or report.converged for report in reports) and all(
        all(item.severity != "high" for item in report.findings) for report in reports
    ) else 1


if __name__ == "__main__":
    sys.exit(main())
