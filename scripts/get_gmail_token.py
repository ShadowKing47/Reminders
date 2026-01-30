"""
Utility to run OAuth flow and write token.json for Gmail access.

Usage:
  python scripts/get_gmail_token.py --client-secrets credentials.json --scopes "https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.modify" --out token.json

This uses the local server flow to obtain user consent and writes the token file.
"""
import argparse
import json
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow


def main():
    parser = argparse.ArgumentParser(description='Run OAuth flow to create Gmail token.json')
    parser.add_argument('--client-secrets', required=True, help='Path to client_secrets JSON (from Google Cloud)')
    parser.add_argument('--scopes', required=False, default='https://www.googleapis.com/auth/gmail.readonly',
                        help='Comma-separated scopes')
    parser.add_argument('--out', required=False, default='token.json', help='Output token file path')
    args = parser.parse_args()

    scopes = [s.strip() for s in args.scopes.split(',') if s.strip()]

    flow = InstalledAppFlow.from_client_secrets_file(args.client_secrets, scopes=scopes)
    creds = flow.run_local_server(port=0)

    token = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': creds.scopes,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(token, f)

    print(f"Wrote token to {out_path}")


if __name__ == '__main__':
    main()
