"""
Gmail OAuth helper.
Manages loading/storing credentials and refreshing tokens.

Usage:
  mgr = GmailCredentialsManager(token_path='token.json', client_secrets_path='credentials.json')
  creds = mgr.get_credentials()

Notes:
- For production, store `token.json` securely (secrets manager, encrypted store).
- If no token exists, this helper raises FileNotFoundError; run an OAuth flow locally to obtain tokens.
"""
import os
import json
from typing import Optional
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request


class GmailCredentialsManager:
    """
    Lightweight credentials manager for Gmail API.
    - Loads credentials from a token file or environment variables
    - Refreshes tokens if expired using `google-auth`'s Request
    - Writes refreshed token back to `token_path` if available
    """

    def __init__(
        self,
        token_path: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        scopes: Optional[list] = None,
    ):
        self.token_path = token_path or os.getenv('GMAIL_TOKEN_PATH', 'token.json')
        self.client_id = client_id or os.getenv('GMAIL_CLIENT_ID')
        self.client_secret = client_secret or os.getenv('GMAIL_CLIENT_SECRET')
        self.scopes = scopes or [
            'https://www.googleapis.com/auth/gmail.readonly',
            'https://www.googleapis.com/auth/gmail.modify',
        ]

    def _load_token_file(self) -> Optional[dict]:
        if os.path.exists(self.token_path):
            with open(self.token_path, 'r') as f:
                return json.load(f)
        return None

    def _save_token_file(self, token: dict):
        dirpath = os.path.dirname(self.token_path)
        if dirpath and not os.path.exists(dirpath):
            os.makedirs(dirpath, exist_ok=True)
        with open(self.token_path, 'w') as f:
            json.dump(token, f)

    def get_credentials(self) -> Credentials:
        """
        Return valid `google.oauth2.credentials.Credentials`.
        If a token file exists it is used; otherwise environment variables are checked.
        If credentials are expired and refresh token is available, it will be refreshed and persisted.
        """
        token_data = self._load_token_file()

        creds = None
        if token_data:
            creds = Credentials(
                token=token_data.get('token'),
                refresh_token=token_data.get('refresh_token'),
                token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
                client_id=token_data.get('client_id') or self.client_id,
                client_secret=token_data.get('client_secret') or self.client_secret,
                scopes=token_data.get('scopes') or self.scopes,
            )
        else:
            # Try to load from environment variables (not recommended for long-lived use)
            env_token = os.getenv('GMAIL_ACCESS_TOKEN')
            env_refresh = os.getenv('GMAIL_REFRESH_TOKEN')
            if env_token and env_refresh and self.client_id and self.client_secret:
                creds = Credentials(
                    token=env_token,
                    refresh_token=env_refresh,
                    token_uri='https://oauth2.googleapis.com/token',
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    scopes=self.scopes,
                )

        if not creds:
            raise FileNotFoundError(
                f"No token found at {self.token_path} and required env vars missing. "
                "Run an OAuth flow to generate token.json and place it at this path."
            )

        # Refresh if needed
        if creds.expired and creds.refresh_token:
            request = Request()
            creds.refresh(request)
            # Persist refreshed token
            try:
                persistent = {
                    'token': creds.token,
                    'refresh_token': creds.refresh_token,
                    'token_uri': creds.token_uri,
                    'client_id': creds.client_id,
                    'client_secret': creds.client_secret,
                    'scopes': creds.scopes,
                }
                self._save_token_file(persistent)
            except Exception:
                # Fail silently on save; credentials still usable
                pass

        return creds
