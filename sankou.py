#!/usr/bin/env python3
"""
Notion DAILY_IMG DBから画像をダウンロードし、
L版サイズ（89mm×127mm）に3×4グリッドで配置するスクリプト

使用方法:
python notion_daily_img\main.py --month 2025-01
python notion_daily_img\main.py --month 2025-01 --force  # 強制再ダウンロード
"""

import argparse
import calendar
import os
import requests
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw
from dotenv import load_dotenv

load_dotenv()

# ============================================
# 設定
# ============================================
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "2e3be5a7-991a-8006-b6d3-d928f087e0e2")

# ディレクトリ設定
BASE_DIR = Path(__file__).parent
IMAGES_DIR = BASE_DIR / "images"
OUTPUT_DIR = IMAGES_DIR / "output"
NOIMAGE_PATH = IMAGES_DIR / "noimage.png"

# L版サイズ設定（縦置き）
DPI = 300
L_WIDTH_MM = 89
L_HEIGHT_MM = 127
L_WIDTH_PX = int(L_WIDTH_MM * DPI / 25.4)   # 1051px
L_HEIGHT_PX = int(L_HEIGHT_MM * DPI / 25.4)  # 1500px

# セルサイズ
CELL_SIZE_MM = 27
CELL_SIZE_PX = int(CELL_SIZE_MM * DPI / 25.4)  # 319px

# グリッド設定
COLS = 3
ROWS = 4
IMAGES_PER_PAGE = COLS * ROWS  # 12

# 余白計算
MARGIN_X = (L_WIDTH_PX - CELL_SIZE_PX * COLS) // 2
MARGIN_Y = (L_HEIGHT_PX - CELL_SIZE_PX * ROWS) // 2


# ============================================
# Notion API
# ============================================
def get_notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }


def query_database(year: int, month: int) -> list:
    """指定月のデータをNotionから取得"""
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    
    # 月の開始日と終了日
    start_date = f"{year:04d}-{month:02d}-01"
    last_day = calendar.monthrange(year, month)[1]
    end_date = f"{year:04d}-{month:02d}-{last_day:02d}"
    
    payload = {
        "filter": {
            "and": [
                {
                    "property": "日付",
                    "date": {
                        "on_or_after": start_date
                    }
                },
                {
                    "property": "日付",
                    "date": {
                        "on_or_before": end_date
                    }
                }
            ]
        },
        "sorts": [
            {
                "property": "日付",
                "direction": "ascending"
            }
        ],
        "page_size": 100
    }
    
    response = requests.post(url, headers=get_notion_headers(), json=payload)
    response.raise_for_status()
    return response.json().get("results", [])


def extract_image_info(results: list) -> dict:
    """Notionの結果から日付→画像URLのマッピングを作成"""
    date_to_image = {}
    
    for page in results:
        props = page.get("properties", {})
        
        # 日付を取得
        date_prop = props.get("日付", {})
        date_data = date_prop.get("date")
        if not date_data or not date_data.get("start"):
            continue
        date_str = date_data["start"]  # "2025-01-15" 形式
        
        # 画像を取得
        files_prop = props.get("画像", {})
        files = files_prop.get("files", [])
        if not files:
            continue
        
        # 最初の画像を使用
        file_obj = files[0]
        if file_obj.get("type") == "file":
            image_url = file_obj["file"]["url"]
        elif file_obj.get("type") == "external":
            image_url = file_obj["external"]["url"]
        else:
            continue
        
        date_to_image[date_str] = image_url
    
    return date_to_image


# ============================================
# 画像ダウンロード
# ============================================
def download_image(url: str, save_path: Path) -> bool:
    """画像をダウンロードして保存"""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(response.content)
        
        print(f"  ✓ ダウンロード完了: {save_path.name}")
        return True
    except Exception as e:
        print(f"  ✗ ダウンロード失敗: {e}")
        return False


def download_monthly_images(year: int, month: int, date_to_image: dict, force: bool = False) -> dict:
    """月の画像をダウンロードし、日付→ローカルパスのマッピングを返す"""
    month_dir = IMAGES_DIR / f"{year:04d}" / f"{month:02d}"
    month_dir.mkdir(parents=True, exist_ok=True)
    
    date_to_path = {}
    
    for date_str, image_url in date_to_image.items():
        # ファイル名: yyyy_mm_dd.jpg
        filename = date_str.replace("-", "_") + ".jpg"
        save_path = month_dir / filename
        
        # 既にダウンロード済みならスキップ（--force時は再ダウンロード）
        if save_path.exists() and not force:
            print(f"  - スキップ（既存）: {save_path.name}")
            date_to_path[date_str] = save_path
            continue
        
        if download_image(image_url, save_path):
            date_to_path[date_str] = save_path
    
    return date_to_path


# ============================================
# noimage.png 生成
# ============================================
def create_noimage():
    """noimage.png がなければ生成"""
    if NOIMAGE_PATH.exists():
        return
    
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    
    # グレーの背景に「NO IMAGE」テキスト
    img = Image.new("RGB", (CELL_SIZE_PX, CELL_SIZE_PX), color=(200, 200, 200))
    draw = ImageDraw.Draw(img)
    
    text = "NO IMAGE"
    # テキストを中央に配置（簡易版）
    bbox = draw.textbbox((0, 0), text)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (CELL_SIZE_PX - text_width) // 2
    y = (CELL_SIZE_PX - text_height) // 2
    draw.text((x, y), text, fill=(100, 100, 100))
    
    img.save(NOIMAGE_PATH)
    print(f"✓ noimage.png を生成しました")


# ============================================
# グリッド画像生成
# ============================================
def resize_and_center(img: Image.Image, cell_size: int) -> Image.Image:
    """画像をセルサイズに収めてセンタリング"""
    # アスペクト比を維持してリサイズ
    img_ratio = img.width / img.height
    cell_ratio = 1.0  # 正方形セル
    
    if img_ratio > cell_ratio:
        # 横長 → 幅に合わせる
        new_width = cell_size
        new_height = int(cell_size / img_ratio)
    else:
        # 縦長 → 高さに合わせる
        new_height = cell_size
        new_width = int(cell_size * img_ratio)
    
    img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    # セルサイズの白背景に中央配置
    cell_img = Image.new("RGB", (cell_size, cell_size), color=(255, 255, 255))
    x = (cell_size - new_width) // 2
    y = (cell_size - new_height) // 2
    cell_img.paste(img_resized, (x, y))
    
    return cell_img


def create_grid_page(image_paths: list, page_num: int, year: int, month: int) -> Path:
    """1ページ分のグリッド画像を生成"""
    # L版サイズの白背景
    canvas = Image.new("RGB", (L_WIDTH_PX, L_HEIGHT_PX), color=(255, 255, 255))
    
    for i, img_path in enumerate(image_paths):
        row = i // COLS
        col = i % COLS
        
        x = MARGIN_X + col * CELL_SIZE_PX
        y = MARGIN_Y + row * CELL_SIZE_PX
        
        # 画像を読み込んでリサイズ
        try:
            img = Image.open(img_path)
            if img.mode != "RGB":
                img = img.convert("RGB")
        except Exception as e:
            print(f"  ✗ 画像読み込みエラー: {img_path} - {e}")
            img = Image.open(NOIMAGE_PATH)
        
        cell_img = resize_and_center(img, CELL_SIZE_PX)
        canvas.paste(cell_img, (x, y))
    
    # 保存
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{year:04d}_{month:02d}_page{page_num}.png"
    canvas.save(output_path, dpi=(DPI, DPI))
    
    return output_path


def generate_grid_images(year: int, month: int, date_to_path: dict) -> list:
    """月のグリッド画像を生成"""
    # 月の日数
    days_in_month = calendar.monthrange(year, month)[1]
    
    # 1日〜末日の画像パスリストを作成（ない日はnoimage）
    all_paths = []
    for day in range(1, days_in_month + 1):
        date_str = f"{year:04d}-{month:02d}-{day:02d}"
        if date_str in date_to_path:
            all_paths.append(date_to_path[date_str])
        else:
            all_paths.append(NOIMAGE_PATH)
    
    # 12枚ずつページに分割
    output_paths = []
    page_num = 1
    
    for i in range(0, len(all_paths), IMAGES_PER_PAGE):
        page_paths = all_paths[i:i + IMAGES_PER_PAGE]
        output_path = create_grid_page(page_paths, page_num, year, month)
        output_paths.append(output_path)
        print(f"  ✓ ページ {page_num} 生成: {output_path.name}")
        page_num += 1
    
    return output_paths


# ============================================
# メイン処理
# ============================================
def main():
    parser = argparse.ArgumentParser(
        description="Notion DAILY_IMG DBから画像をダウンロードしてL版グリッド画像を生成"
    )
    parser.add_argument(
        "--month",
        required=True,
        help="対象月（例: 2025-01）"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="既存の画像を強制的に再ダウンロード"
    )
    args = parser.parse_args()
    
    # 月をパース
    try:
        target_date = datetime.strptime(args.month, "%Y-%m")
        year = target_date.year
        month = target_date.month
    except ValueError:
        print("エラー: --month は YYYY-MM 形式で指定してください（例: 2025-01）")
        return
    
    print(f"\n{'='*50}")
    print(f"対象: {year}年{month}月")
    if args.force:
        print("モード: 強制再ダウンロード")
    print(f"{'='*50}\n")
    
    # noimage.png を準備
    create_noimage()
    
    # Notionからデータ取得
    print("1. Notionからデータを取得中...")
    try:
        results = query_database(year, month)
        print(f"   取得件数: {len(results)}件")
    except Exception as e:
        print(f"   エラー: {e}")
        return
    
    # 日付→画像URLマッピング
    date_to_image = extract_image_info(results)
    print(f"   画像あり: {len(date_to_image)}日分\n")
    
    # 画像ダウンロード
    print("2. 画像をダウンロード中...")
    date_to_path = download_monthly_images(year, month, date_to_image, force=args.force)
    print()
    
    # グリッド画像生成
    print("3. グリッド画像を生成中...")
    output_paths = generate_grid_images(year, month, date_to_path)
    print()
    
    # 完了
    print(f"{'='*50}")
    print("完了！")
    print(f"出力先: {OUTPUT_DIR}")
    for p in output_paths:
        print(f"  - {p.name}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()