#!/usr/bin/env python3
"""
Google Photos OAuth 初回認証スクリプト
初回のみ実行: python auth.py
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/photoslibrary.readonly"]
TOKEN_PATH = Path.home() / ".config" / "daily_photo" / "token.json"


def main():
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError(".env に GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET が設定されていません")

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)

    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json())
    print(f"認証完了。トークンを保存しました: {TOKEN_PATH}")


if __name__ == "__main__":
    main()
