"""Structured Google Ads API error mapping."""

from __future__ import annotations

from typing import Any

from google.ads.googleads.errors import GoogleAdsException


class AdsError(Exception):
    """Raised when a Google Ads API call fails."""

    def __init__(self, message: str, *, request_id: str | None = None, details: list[str] | None = None):
        super().__init__(message)
        self.request_id = request_id
        self.details = details or []

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"error": str(self)}
        if self.request_id:
            payload["request_id"] = self.request_id
        if self.details:
            payload["details"] = self.details
        return payload


def format_google_ads_exception(exc: GoogleAdsException) -> AdsError:
    details: list[str] = []
    for error in exc.failure.errors:
        piece = error.message
        if error.location:
            fields = ", ".join(
                element.field_name for element in error.location.field_path_elements
            )
            if fields:
                piece = f"{piece} (fields: {fields})"
        details.append(piece)
    joined = "; ".join(details) if details else str(exc)
    return AdsError(
        f"Google Ads API error: {joined}",
        request_id=getattr(exc, "request_id", None),
        details=details,
    )
