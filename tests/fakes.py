"""GoogleAdsClient that can build mutate protos without a live OAuth refresh."""

from google.ads.googleads.client import GoogleAdsClient
from google.oauth2.credentials import Credentials


def fake_ads_client() -> GoogleAdsClient:
    return GoogleAdsClient(
        credentials=Credentials(token="test-token"),
        developer_token="test-developer-token",
        use_proto_plus=True,
    )
