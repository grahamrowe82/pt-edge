"""One-time OAuth2 flow to get a refresh token for Google Search Console API."""

import json
from google_auth_oauthlib.flow import InstalledAppFlow

CLIENT_SECRET = "secrets/client_secret_850211743243-npd4demn19br5q7n8d5biq3g023vg8mj.apps.googleusercontent.com.json"
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
TOKEN_OUT = "secrets/gsc_token.json"


def main():
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, scopes=SCOPES)
    creds = flow.run_local_server(port=0)

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }

    with open(TOKEN_OUT, "w") as f:
        json.dump(token_data, f, indent=2)

    print(f"Refresh token saved to {TOKEN_OUT}")
    print(f"Set this as GSC_REFRESH_TOKEN on Render: {creds.refresh_token}")


if __name__ == "__main__":
    main()
