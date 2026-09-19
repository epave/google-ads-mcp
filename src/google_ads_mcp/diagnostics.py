"""Campaign diagnostics and shared findings engine."""

from __future__ import annotations

from typing import Any

from google_ads_mcp.gaql import search
from google_ads_mcp.ids import clean_customer_id
from google_ads_mcp.money import from_micros

ORIGIN_GOOGLE = "GOOGLE_API"
ORIGIN_LOCAL = "LOCAL_DIAGNOSTIC"
SEVERITIES = ("critical", "warning", "opportunity", "informational")


def finding(
    *,
    severity: str,
    code: str,
    origin: str,
    message: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if severity not in SEVERITIES:
        raise ValueError(f"Unknown severity {severity!r}")
    if origin not in {ORIGIN_GOOGLE, ORIGIN_LOCAL}:
        raise ValueError(f"Unknown origin {origin!r}")
    return {
        "severity": severity,
        "code": code,
        "origin": origin,
        "message": message,
        "evidence": evidence or {},
    }


def _metric_window(row: dict[str, Any] | None) -> dict[str, Any]:
    row = row or {}
    spend = from_micros(row.get("metrics.cost_micros"))
    clicks = float(row.get("metrics.clicks") or 0)
    impressions = float(row.get("metrics.impressions") or 0)
    conversions = float(row.get("metrics.conversions") or 0)
    all_conversions = float(row.get("metrics.all_conversions") or 0)
    ctr = (clicks / impressions) if impressions else None
    cpc = (spend / clicks) if clicks else None
    return {
        "spend": round(spend, 2),
        "clicks": clicks,
        "impressions": impressions,
        "conversions": conversions,
        "all_conversions": all_conversions,
        "ctr": round(ctr, 4) if ctr is not None else None,
        "cpc": round(cpc, 2) if cpc is not None else None,
    }


def _first(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return rows[0] if rows else None


def _is_future_start(start_date_time: Any) -> bool:
    """True when campaign.start_date_time is in the future (scheduled)."""
    if not start_date_time:
        return False
    from datetime import datetime

    raw = str(start_date_time).strip()
    for fmt, width in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            start = datetime.strptime(raw[:width], fmt)
            return start > datetime.now()
        except ValueError:
            continue
    return False


def _primary_status_severity(
    primary: str,
    *,
    campaign: dict[str, Any],
    reasons: list[Any],
) -> str:
    """PENDING is expected for scheduled (future start) campaigns — not critical."""
    if primary == "NOT_ELIGIBLE":
        return "critical"
    if primary == "PENDING":
        reason_blob = " ".join(str(r).upper() for r in reasons)
        scheduled = _is_future_start(campaign.get("campaign.start_date_time")) or any(
            token in reason_blob for token in ("SCHEDULE", "NOT_STARTED")
        )
        return "informational" if scheduled else "critical"
    return "warning"


def collect_local_findings(
    *,
    campaign: dict[str, Any],
    performance: dict[str, Any],
    impression_share: dict[str, Any] | None,
    ads: list[dict[str, Any]],
    keywords: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    conversion_actions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build LOCAL_DIAGNOSTIC findings from observed campaign state."""
    findings: list[dict[str, Any]] = []
    primary = str(campaign.get("campaign.primary_status") or "")
    reasons = campaign.get("campaign.primary_status_reasons") or []
    if isinstance(reasons, str):
        reasons = [reasons]
    status = str(campaign.get("campaign.status") or "")

    if primary and primary not in {"ELIGIBLE", "ELIGIBLE_LIMITED", "UNSPECIFIED", "UNKNOWN", ""}:
        severity = _primary_status_severity(primary, campaign=campaign, reasons=reasons)
        findings.append(
            finding(
                severity=severity,
                code="PRIMARY_STATUS",
                origin=ORIGIN_LOCAL,
                message=f"Campaign primary status is {primary}",
                evidence={"primary_status": primary, "reasons": reasons},
            )
        )
    if any("LEARNING" in str(r).upper() for r in reasons) or "LEARNING" in primary.upper():
        findings.append(
            finding(
                severity="informational",
                code="LEARNING",
                origin=ORIGIN_LOCAL,
                message="Campaign bidding strategy is in learning",
                evidence={"reasons": reasons, "primary_status": primary},
            )
        )
    week = performance.get("last_7_days") or {}
    if status == "ENABLED" and primary in {"ELIGIBLE", "ELIGIBLE_LIMITED", ""} and not (
        week.get("impressions") or 0
    ):
        findings.append(
            finding(
                severity="critical",
                code="NO_DELIVERY",
                origin=ORIGIN_LOCAL,
                message="Campaign is eligible but has no impressions in the last 7 days",
                evidence={"status": status, "primary_status": primary},
            )
        )

    if impression_share:
        lost_budget = float(
            impression_share.get("metrics.search_budget_lost_impression_share") or 0
        )
        lost_rank = float(
            impression_share.get("metrics.search_rank_lost_impression_share") or 0
        )
        if lost_budget >= 0.2:
            findings.append(
                finding(
                    severity="warning",
                    code="IS_LOST_BUDGET",
                    origin=ORIGIN_LOCAL,
                    message=f"Lost {lost_budget:.0%} search impression share to budget",
                    evidence={"lost_to_budget": lost_budget},
                )
            )
        if lost_rank >= 0.3:
            findings.append(
                finding(
                    severity="opportunity",
                    code="IS_LOST_RANK",
                    origin=ORIGIN_LOCAL,
                    message=f"Lost {lost_rank:.0%} search impression share to rank",
                    evidence={"lost_to_rank": lost_rank},
                )
            )

    rarely = [
        kw
        for kw in keywords
        if str(kw.get("ad_group_criterion.system_serving_status") or "")
        in {"RARELY_SERVED", "PENDING"}
        or (
            kw.get("metrics.historical_quality_score") is not None
            and float(kw.get("metrics.historical_quality_score") or 10) <= 4
        )
    ]
    if rarely:
        findings.append(
            finding(
                severity="warning",
                code="KEYWORD_SERVING",
                origin=ORIGIN_LOCAL,
                message=f"{len(rarely)} keyword(s) rarely served or low quality score",
                evidence={
                    "sample": [
                        {
                            "text": r.get("ad_group_criterion.keyword.text"),
                            "serving": r.get("ad_group_criterion.system_serving_status"),
                            "quality": r.get("metrics.historical_quality_score"),
                        }
                        for r in rarely[:5]
                    ]
                },
            )
        )

    field_types = {str(a.get("campaign_asset.field_type") or "") for a in assets}
    for missing, code, label in (
        ("CALLOUT", "MISSING_CALLOUTS", "callouts"),
        ("STRUCTURED_SNIPPET", "MISSING_STRUCTURED_SNIPPETS", "structured snippets"),
        ("SITELINK", "MISSING_SITELINKS", "sitelinks"),
    ):
        if missing not in field_types:
            findings.append(
                finding(
                    severity="opportunity",
                    code=code,
                    origin=ORIGIN_LOCAL,
                    message=f"Campaign has no attached {label}",
                    evidence={"field_type": missing},
                )
            )

    policy_ads = [
        ad
        for ad in ads
        if str(ad.get("ad_group_ad.policy_summary.approval_status") or "")
        in {"DISAPPROVED", "AREA_OF_INTEREST_ONLY"}
        or str(ad.get("ad_group_ad.policy_summary.review_status") or "") == "REVIEW_IN_PROGRESS"
    ]
    if policy_ads:
        findings.append(
            finding(
                severity="warning",
                code="AD_POLICY_REVIEW",
                origin=ORIGIN_LOCAL,
                message=f"{len(policy_ads)} ad(s) under policy review or disapproved",
                evidence={
                    "sample": [
                        {
                            "ad": a.get("ad_group_ad.ad.id"),
                            "approval": a.get("ad_group_ad.policy_summary.approval_status"),
                            "review": a.get("ad_group_ad.policy_summary.review_status"),
                        }
                        for a in policy_ads[:5]
                    ]
                },
            )
        )

    policy_assets = [
        a
        for a in assets
        if str(a.get("asset.policy_summary.approval_status") or "") == "DISAPPROVED"
        or str(a.get("asset.policy_summary.review_status") or "")
        in {"REVIEW_IN_PROGRESS", "UNDER_REVIEW"}
    ]
    if policy_assets:
        findings.append(
            finding(
                severity="warning",
                code="ASSET_POLICY_REVIEW",
                origin=ORIGIN_LOCAL,
                message=f"{len(policy_assets)} asset(s) under policy review or disapproved",
                evidence={"count": len(policy_assets)},
            )
        )

    if conversion_actions is not None and not conversion_actions:
        findings.append(
            finding(
                severity="warning",
                code="MISSING_PRIMARY_CONVERSIONS",
                origin=ORIGIN_LOCAL,
                message="No primary conversion actions configured for this campaign",
                evidence={},
            )
        )

    return findings


def count_findings_by_severity(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts = {s: 0 for s in SEVERITIES}
    for item in findings:
        sev = item.get("severity")
        if sev in counts:
            counts[sev] += 1
    return counts


def asset_type_counts(assets: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"CALLOUT": 0, "STRUCTURED_SNIPPET": 0, "SITELINK": 0, "OTHER": 0}
    for row in assets:
        ft = str(row.get("campaign_asset.field_type") or "OTHER")
        if ft in counts:
            counts[ft] += 1
        else:
            counts["OTHER"] += 1
    return counts


def build_campaign_diagnostics(
    customer_id: str,
    campaign_id: str,
    *,
    login_customer_id: str | None = None,
    search_fn=search,
) -> dict[str, Any]:
    """Assemble a one-call diagnostic payload for a campaign."""
    cid = clean_customer_id(customer_id)
    camp_id = str(int(str(campaign_id).replace("-", "")))

    campaign_rows = search_fn(
        cid,
        "SELECT campaign.id, campaign.name, campaign.status, campaign.primary_status, "
        "campaign.primary_status_reasons, campaign.advertising_channel_type, "
        "campaign.bidding_strategy_type, campaign.optimization_score, "
        "campaign.start_date_time, campaign.end_date_time, "
        "campaign_budget.amount_micros, campaign_budget.delivery_method "
        f"FROM campaign WHERE campaign.id = {camp_id}",
        login_customer_id=login_customer_id,
    )
    campaign = _first(campaign_rows)
    if campaign is None:
        return {
            "customer_id": cid,
            "campaign_id": camp_id,
            "error": f"Campaign {camp_id} not found",
            "findings": [],
        }

    def metrics_query(period: str) -> dict[str, Any] | None:
        return _first(
            search_fn(
                cid,
                "SELECT campaign.id, metrics.cost_micros, metrics.clicks, metrics.impressions, "
                "metrics.conversions, metrics.all_conversions, metrics.ctr, "
                "metrics.average_cpc FROM campaign "
                f"WHERE campaign.id = {camp_id} AND segments.date DURING {period}",
                login_customer_id=login_customer_id,
            )
        )

    performance = {
        "today": _metric_window(metrics_query("TODAY")),
        "last_7_days": _metric_window(metrics_query("LAST_7_DAYS")),
        "last_30_days": _metric_window(metrics_query("LAST_30_DAYS")),
    }

    impression_share = _first(
        search_fn(
            cid,
            "SELECT campaign.id, metrics.search_impression_share, "
            "metrics.search_budget_lost_impression_share, "
            "metrics.search_rank_lost_impression_share "
            f"FROM campaign WHERE campaign.id = {camp_id} "
            "AND segments.date DURING LAST_7_DAYS",
            login_customer_id=login_customer_id,
        )
    )

    ads = search_fn(
        cid,
        "SELECT campaign.id, ad_group.id, ad_group_ad.ad.id, ad_group_ad.status, "
        "ad_group_ad.policy_summary.approval_status, "
        "ad_group_ad.policy_summary.review_status, "
        "ad_group_ad.ad_strength "
        f"FROM ad_group_ad WHERE campaign.id = {camp_id} "
        "AND ad_group_ad.status != 'REMOVED' LIMIT 200",
        login_customer_id=login_customer_id,
    )

    keywords = search_fn(
        cid,
        "SELECT campaign.id, ad_group.id, ad_group_criterion.criterion_id, "
        "ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type, "
        "ad_group_criterion.status, ad_group_criterion.system_serving_status, "
        "ad_group_criterion.quality_info.quality_score, "
        "metrics.historical_quality_score "
        f"FROM keyword_view WHERE campaign.id = {camp_id} "
        "AND ad_group_criterion.status != 'REMOVED' "
        "AND segments.date DURING LAST_30_DAYS LIMIT 500",
        login_customer_id=login_customer_id,
    )

    assets = search_fn(
        cid,
        "SELECT campaign.id, campaign_asset.resource_name, campaign_asset.asset, "
        "campaign_asset.field_type, campaign_asset.status, "
        "asset.id, asset.type, asset.callout_asset.callout_text, "
        "asset.structured_snippet_asset.header, "
        "asset.policy_summary.approval_status, asset.policy_summary.review_status "
        f"FROM campaign_asset WHERE campaign.id = {camp_id} "
        "AND campaign_asset.status != 'REMOVED'",
        login_customer_id=login_customer_id,
    )

    recommendations = search_fn(
        cid,
        "SELECT recommendation.resource_name, recommendation.type, recommendation.campaign, "
        "recommendation.campaigns "
        "FROM recommendation WHERE recommendation.dismissed = FALSE "
        "AND ("
        f"recommendation.campaign = 'customers/{cid}/campaigns/{camp_id}' "
        f"OR recommendation.campaigns CONTAINS ANY ('customers/{cid}/campaigns/{camp_id}')"
        ") "
        "LIMIT 50",
        login_customer_id=login_customer_id,
    )

    conversion_actions = search_fn(
        cid,
        "SELECT campaign_conversion_goal.campaign, campaign_conversion_goal.category, "
        "campaign_conversion_goal.origin, campaign_conversion_goal.biddable "
        "FROM campaign_conversion_goal WHERE "
        f"campaign_conversion_goal.campaign = 'customers/{cid}/campaigns/{camp_id}' "
        "AND campaign_conversion_goal.biddable = TRUE",
        login_customer_id=login_customer_id,
    )

    local_findings = collect_local_findings(
        campaign=campaign,
        performance=performance,
        impression_share=impression_share,
        ads=ads,
        keywords=keywords,
        assets=assets,
        conversion_actions=conversion_actions,
    )

    google_findings = [
        finding(
            severity="opportunity",
            code=f"GOOGLE_REC_{str(r.get('recommendation.type') or 'UNKNOWN')}",
            origin=ORIGIN_GOOGLE,
            message=f"Pending Google recommendation: {r.get('recommendation.type')}",
            evidence={
                "resource_name": r.get("recommendation.resource_name"),
                "type": r.get("recommendation.type"),
            },
        )
        for r in recommendations
    ]

    findings = local_findings + google_findings
    severity_order = {s: i for i, s in enumerate(SEVERITIES)}
    findings.sort(key=lambda f: severity_order.get(f["severity"], 99))

    return {
        "customer_id": cid,
        "campaign_id": camp_id,
        "campaign": {
            "name": campaign.get("campaign.name"),
            "status": campaign.get("campaign.status"),
            "primary_status": campaign.get("campaign.primary_status"),
            "primary_status_reasons": reasons_list(campaign),
            "channel": campaign.get("campaign.advertising_channel_type"),
            "bidding_strategy": campaign.get("campaign.bidding_strategy_type"),
            "optimization_score": campaign.get("campaign.optimization_score"),
            "start_date_time": campaign.get("campaign.start_date_time"),
            "end_date_time": campaign.get("campaign.end_date_time"),
            "daily_budget": from_micros(campaign.get("campaign_budget.amount_micros")),
        },
        "performance": performance,
        "impression_share": {
            "search_impression_share": (impression_share or {}).get(
                "metrics.search_impression_share"
            ),
            "lost_to_budget": (impression_share or {}).get(
                "metrics.search_budget_lost_impression_share"
            ),
            "lost_to_rank": (impression_share or {}).get(
                "metrics.search_rank_lost_impression_share"
            ),
        },
        "ads": {
            "count": len(ads),
            "sample": ads[:20],
        },
        "keywords": {
            "count": len(keywords),
            "serving_problems": [
                k
                for k in keywords
                if str(k.get("ad_group_criterion.system_serving_status") or "")
                in {"RARELY_SERVED", "PENDING"}
            ][:20],
        },
        "assets": {
            "count": len(assets),
            "by_type": asset_type_counts(assets),
            "items": assets,
        },
        "recommendations": {
            "count": len(recommendations),
            "types": [r.get("recommendation.type") for r in recommendations],
        },
        "findings": findings,
        "finding_counts": count_findings_by_severity(findings),
    }


def reasons_list(campaign: dict[str, Any]) -> list[str]:
    reasons = campaign.get("campaign.primary_status_reasons") or []
    if isinstance(reasons, str):
        return [reasons]
    return [str(r) for r in reasons]


def compact_diagnostic_summary(diag: dict[str, Any]) -> dict[str, Any]:
    """Subset suitable for embedding in the campaign dashboard."""
    camp = diag.get("campaign") or {}
    perf = (diag.get("performance") or {}).get("last_7_days") or {}
    ishare = diag.get("impression_share") or {}
    assets = (diag.get("assets") or {}).get("by_type") or {}
    return {
        "primary_status": camp.get("primary_status"),
        "ctr_7d": perf.get("ctr"),
        "cpc_7d": perf.get("cpc"),
        "lost_to_budget": ishare.get("lost_to_budget"),
        "lost_to_rank": ishare.get("lost_to_rank"),
        "asset_counts": {
            "callouts": assets.get("CALLOUT", 0),
            "structured_snippets": assets.get("STRUCTURED_SNIPPET", 0),
            "sitelinks": assets.get("SITELINK", 0),
        },
        "pending_recommendations": (diag.get("recommendations") or {}).get("count", 0),
        "finding_counts": diag.get("finding_counts") or {},
    }
