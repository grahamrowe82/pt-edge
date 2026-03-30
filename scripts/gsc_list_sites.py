"""List all GSC properties accessible to the authenticated account."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

with open("secrets/gsc_token.json") as f:
    data = json.load(f)

creds = Credentials(
    token=data.get("token"),
    refresh_token=data["refresh_token"],
    token_uri=data["token_uri"],
    client_id=data["client_id"],
    client_secret=data["client_secret"],
)

service = build("searchconsole", "v1", credentials=creds)
sites = service.sites().list().execute()

for site in sites.get("siteEntry", []):
    print(f"  {site['permissionLevel']:15s}  {site['siteUrl']}")
