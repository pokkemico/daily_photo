import calendar
import logging
import os
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _query_all(api_key: str, database_id: str, filter_body: dict | None = None) -> list[dict]:
    headers = _headers(api_key)
    results = []
    cursor = None
    while True:
        body: dict = {}
        if filter_body:
            body["filter"] = filter_body
        if cursor:
            body["start_cursor"] = cursor
        resp = requests.post(
            f"{NOTION_API}/databases/{database_id}/query",
            headers=headers,
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return results


def _is_registered(api_key: str, database_id: str, target_date: date) -> bool:
    resp = requests.post(
        f"{NOTION_API}/databases/{database_id}/query",
        headers=_headers(api_key),
        json={"filter": {"property": "日付", "date": {"equals": str(target_date)}}},
        timeout=30,
    )
    resp.raise_for_status()
    return len(resp.json().get("results", [])) > 0


def is_registered(target_date: date) -> bool:
    api_key = os.environ["NOTION_API_KEY"]
    database_id = os.environ["NOTION_DATABASE_ID"]
    return _is_registered(api_key, database_id, target_date)


def get_used_filenames() -> set[str]:
    """全登録済みエントリのsource_filenameを返す（フォールバック重複防止用）"""
    api_key = os.environ["NOTION_API_KEY"]
    database_id = os.environ["NOTION_DATABASE_ID"]
    results = _query_all(api_key, database_id)
    filenames = set()
    for page in results:
        source = page.get("properties", {}).get("source_filename", {}).get("rich_text", [])
        if source:
            filenames.add(source[0]["text"]["content"])
    return filenames


def get_month_images(year: int, month: int) -> dict[str, str]:
    """{YYYY-MM-DD: image_url} を返す（グリッド生成用）"""
    api_key = os.environ["NOTION_API_KEY"]
    database_id = os.environ["NOTION_DATABASE_ID"]
    start = f"{year:04d}-{month:02d}-01"
    end = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
    results = _query_all(api_key, database_id, filter_body={
        "and": [
            {"property": "日付", "date": {"on_or_after": start}},
            {"property": "日付", "date": {"on_or_before": end}},
        ]
    })
    images = {}
    for page in results:
        props = page.get("properties", {})
        date_prop = props.get("日付", {}).get("date")
        if not date_prop:
            continue
        date_str = date_prop.get("start", "")[:10]
        files = props.get("画像", {}).get("files", [])
        if files and files[0].get("type") == "file":
            images[date_str] = files[0]["file"]["url"]
    return images


def _upload_file(api_key: str, file_path: Path) -> str:
    auth_headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
    }

    # Step 1: アップロードセッション作成
    resp = requests.post(
        f"{NOTION_API}/file_uploads",
        headers={**auth_headers, "Content-Type": "application/json"},
        json={"filename": file_path.name, "content_type": "image/jpeg"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    upload_id = data["id"]
    upload_url = data["upload_url"]  # = /v1/file_uploads/{id}/send
    logger.debug("アップロードセッション作成: %s", upload_id)

    # Step 2: multipart/form-data で送信（Content-Type は requests が自動付与）
    with open(file_path, "rb") as f:
        resp = requests.post(
            upload_url,
            headers=auth_headers,
            files={"file": (file_path.name, f, "image/jpeg")},
            timeout=60,
        )
    resp.raise_for_status()
    logger.info("ファイルアップロード完了: %s", upload_id)
    return upload_id


def save(selected: dict, target_date: date) -> bool:
    """
    選定済み画像を Notion DAILY_IMG DB に保存する。
    既に登録済みの場合はスキップして False を返す。
    """
    api_key = os.environ["NOTION_API_KEY"]
    database_id = os.environ["NOTION_DATABASE_ID"]

    if _is_registered(api_key, database_id, target_date):
        logger.info("%s は登録済みのためスキップ", target_date)
        return False

    upload_id = _upload_file(api_key, selected["output_path"])

    resp = requests.post(
        f"{NOTION_API}/pages",
        headers=_headers(api_key),
        json={
            "parent": {"database_id": database_id},
            "properties": {
                "名前": {"title": [{"text": {"content": str(target_date)}}]},
                "日付": {"date": {"start": str(target_date)}},
                "画像": {
                    "files": [{
                        "type": "file_upload",
                        "file_upload": {"id": upload_id},
                    }]
                },
                "source_filename": {"rich_text": [{"text": {"content": selected["filename"]}}]},
                "選定理由": {"rich_text": [{"text": {"content": selected.get("reason", "")}}]},
            },
        },
        timeout=30,
    )
    resp.raise_for_status()
    logger.info("Notion 登録完了: %s", target_date)
    return True


if __name__ == "__main__":
    import argparse
    import json
    import sys
    from datetime import timedelta

    from selector import SELECTIONS_JSON, _output_path

    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="動作確認モード")
    parser.add_argument("--date", help="対象日（YYYY-MM-DD）。省略時は前日")
    args = parser.parse_args()

    if not args.test:
        parser.print_help()
        sys.exit(0)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    target = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
    print(f"\n対象日: {target}\n")

    out = _output_path(target)
    if not out.exists() or not SELECTIONS_JSON.exists():
        print(f"出力ファイルが見つかりません。先に selector.py --test --date {target} を実行してください")
        sys.exit(1)

    selections = json.loads(SELECTIONS_JSON.read_text())
    if str(target) not in selections:
        print(f"{target} の選定記録がありません。先に selector.py --test --date {target} を実行してください")
        sys.exit(1)

    saved = selections[str(target)]
    selected = {**saved, "output_path": out}

    result = save(selected, target)
    if result:
        print(f"\nNotion 登録完了: {target}")
        print(f"  ファイル  : {saved['filename']}")
        print(f"  選定理由  : {saved['reason']}")
    else:
        print(f"\n登録済みのためスキップ: {target}")
