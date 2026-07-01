#!/usr/bin/env python3
"""
先月分の今日の一枚を L版（89mm×127mm / 300DPI）に 3×4 グリッドで配置する。
1ページ 12枚、月全体を複数ページに分割して Discord に送信する。
画像は Notion DAILY_IMG DB から取得する。該当日がなければ noimage.png を使用。
"""
import io
import logging
import shutil
import sys
import tempfile
from calendar import monthrange
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "common"))
from notify import send_discord_file

from notion import get_month_images

load_dotenv()

logger = logging.getLogger(__name__)

CAMERA_UPLOADS_DIR = Path(__file__).parent / "images" / "camera_uploads"
OUTPUT_DIR = Path(__file__).parent / "images" / "output"
GRID_DIR = Path(__file__).parent / "images" / "grid"
NOIMAGE_PATH = Path(__file__).parent / "images" / "noimage.png"

DPI = 300
L_WIDTH_PX = int(89 * DPI / 25.4)   # 1051px
L_HEIGHT_PX = int(127 * DPI / 25.4)  # 1500px

COLS = 3
ROWS = 4
PER_PAGE = COLS * ROWS  # 12

CELL_PX = int(27 * DPI / 25.4)  # 319px

MARGIN_X = (L_WIDTH_PX - CELL_PX * COLS) // 2
MARGIN_Y = (L_HEIGHT_PX - CELL_PX * ROWS) // 2


def _last_month(ref: date | None = None) -> tuple[int, int]:
    ref = ref or date.today()
    return (ref.year - 1, 12) if ref.month == 1 else (ref.year, ref.month - 1)


def _build_page(image_paths: list[Path], page_num: int, year: int, month: int) -> Path:
    canvas = Image.new("RGB", (L_WIDTH_PX, L_HEIGHT_PX), (255, 255, 255))

    for i, img_path in enumerate(image_paths):
        row, col = divmod(i, COLS)
        x = MARGIN_X + col * CELL_PX
        y = MARGIN_Y + row * CELL_PX

        try:
            with Image.open(img_path) as img:
                cell = img.convert("RGB").resize((CELL_PX, CELL_PX), Image.LANCZOS)
        except Exception:
            with Image.open(NOIMAGE_PATH) as img:
                cell = img.convert("RGB").resize((CELL_PX, CELL_PX), Image.LANCZOS)

        canvas.paste(cell, (x, y))

    GRID_DIR.mkdir(parents=True, exist_ok=True)
    out = GRID_DIR / f"{year:04d}-{month:02d}_p{page_num}.jpg"
    canvas.save(out, "JPEG", quality=95, dpi=(DPI, DPI))
    logger.info("ページ%d 生成: %s", page_num, out)
    return out


def build_grid(year: int, month: int) -> list[Path]:
    days = monthrange(year, month)[1]
    notion_images = get_month_images(year, month)
    logger.info("Notionから%d件の画像URLを取得", len(notion_images))

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        all_paths = []
        for day in range(1, days + 1):
            date_str = f"{year:04d}-{month:02d}-{day:02d}"
            if date_str in notion_images:
                try:
                    resp = requests.get(notion_images[date_str], timeout=30)
                    resp.raise_for_status()
                    tmp_path = tmp_dir / f"{date_str}.jpg"
                    tmp_path.write_bytes(resp.content)
                    all_paths.append(tmp_path)
                except Exception as e:
                    logger.warning("画像ダウンロード失敗 %s: %s", date_str, e)
                    all_paths.append(NOIMAGE_PATH)
            else:
                all_paths.append(NOIMAGE_PATH)

        pages = []
        for i in range(0, len(all_paths), PER_PAGE):
            page_paths = all_paths[i:i + PER_PAGE]
            page_num = i // PER_PAGE + 1
            pages.append(_build_page(page_paths, page_num, year, month))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return pages


def _cleanup_month(year: int, month: int) -> None:
    """指定月のローカル画像を削除する"""
    targets = [
        CAMERA_UPLOADS_DIR / f"{year:04d}" / f"{month:02d}",
        OUTPUT_DIR / f"{year:04d}" / f"{month:02d}",
    ]
    for target in targets:
        if target.exists():
            shutil.rmtree(target)
            logger.info("削除完了: %s", target)


def run(year: int, month: int) -> None:
    pages = build_grid(year, month)
    for i, page in enumerate(pages, 1):
        send_discord_file(
            str(page),
            message=f"{year}年{month}月 振り返りグリッド（{i}/{len(pages)}）",
        )
    _cleanup_month(year, month)
    logger.info("前月ローカル画像を削除しました: %04d-%02d", year, month)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="月次グリッド画像を生成してDiscordに送信")
    parser.add_argument("--month", metavar="YYYY-MM", help="対象月。省略時は先月")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.month:
        y, m = map(int, args.month.split("-"))
    else:
        y, m = _last_month()

    run(y, m)
