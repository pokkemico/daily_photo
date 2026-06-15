import json
import logging
import os
import re
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageOps

load_dotenv()

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent / "images" / "output"

PROMPT = """\
以下の写真の中から1枚を選んでください。

選定基準：
- 写真としてのクオリティ（構図・明るさ・ピント）が高い
- 今日一番思い出に残りそうな瞬間が写っている

回答はJSON形式のみで返してください（前後の説明文は不要）：
{
  "selected": <候補番号（1始まり）>,
  "crop_center": {"x": <0〜1の正規化値>, "y": <0〜1の正規化値>},
  "reason": "<選定理由（日本語、1〜2文）>"
}

crop_center は正方形トリミングの中心座標です（画像の左上が0,0、右下が1,1）。
"""


SELECTIONS_JSON = OUTPUT_DIR / "selections.json"


def _output_path(target_date: date) -> Path:
    return OUTPUT_DIR / f"{target_date.year:04d}" / f"{target_date.month:02d}" / f"{target_date}.jpg"


def _load_selections() -> dict:
    if SELECTIONS_JSON.exists():
        return json.loads(SELECTIONS_JSON.read_text())
    return {}


def _save_selection(target_date: date, entry: dict) -> None:
    data = _load_selections()
    data[str(target_date)] = entry
    SELECTIONS_JSON.parent.mkdir(parents=True, exist_ok=True)
    SELECTIONS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _open_rgb(path: Path) -> Image.Image:
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        return img.convert("RGB")


def _call_gemini(candidates: list[dict]) -> dict:
    import io

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    contents = []
    for i, item in enumerate(candidates, 1):
        contents.append(f"候補 {i}:")
        img = _open_rgb(item["path"])
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95)
        img.close()
        contents.append(types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"))
    contents.append(PROMPT)

    response = client.models.generate_content(
        model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash"),
        contents=contents,
    )

    text = response.text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"JSONが見つかりません: {text}")
    return json.loads(m.group())


def _crop_square(path: Path, cx: float, cy: float, output_path: Path) -> None:
    img = _open_rgb(path)
    w, h = img.size
    size = min(w, h)
    left = max(0, min(int(cx * w) - size // 2, w - size))
    top = max(0, min(int(cy * h) - size // 2, h - size))
    cropped = img.crop((left, top, left + size, top + size))
    img.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(output_path, "JPEG", quality=95)
    cropped.close()


def select(candidates: list[dict], target_date: date) -> dict:
    """
    Gemini で候補から1枚選定し、正方形トリミングして保存する。
    既に出力ファイルがある場合はGeminiをスキップして selections.json から復元する。
    """
    out = _output_path(target_date)
    selections = _load_selections()

    if str(target_date) in selections and out.exists():
        logger.info("出力済みのためGeminiをスキップ: %s", out)
        saved = selections[str(target_date)]
        return {**saved, "output_path": out, "path": Path(saved["path"]), "taken_at": saved["taken_at"]}

    if out.exists() and not selections.get(str(target_date)):
        # 出力画像はあるが selections.json にエントリがない（初回移行時など）
        # candidates から最初の1枚を仮のエントリとして登録し Gemini をスキップ
        logger.info("出力済みだが選定記録なし。candidatesの先頭で補完: %s", out)
        fallback = candidates[0]
        _save_selection(target_date, {
            "filename": fallback["filename"],
            "path": str(fallback["path"]),
            "taken_at": str(fallback["taken_at"]),
            "camera_make": fallback.get("camera_make", ""),
            "camera_model": fallback.get("camera_model", ""),
            "reason": "（記録なし・補完）",
        })
        return {**fallback, "reason": "（記録なし・補完）", "output_path": out}

    if len(candidates) == 1:
        result = {"selected": 1, "crop_center": {"x": 0.5, "y": 0.5}, "reason": "候補が1枚のため自動選定"}
        logger.info("候補1枚のためGeminiをスキップ")
    else:
        logger.info("Gemini に %d枚を送信", len(candidates))
        result = _call_gemini(candidates)
        logger.info("選定: %d番 / 理由: %s", result["selected"], result.get("reason", ""))

    idx = result["selected"] - 1
    if not (0 <= idx < len(candidates)):
        raise ValueError(f"選定番号が範囲外: {result['selected']}")

    selected = candidates[idx]
    _crop_square(selected["path"], float(result["crop_center"]["x"]), float(result["crop_center"]["y"]), out)
    logger.info("トリミング完了: %s", out)

    ret = {
        **selected,
        "reason": result.get("reason", ""),
        "output_path": out,
    }
    _save_selection(target_date, {
        "filename": ret["filename"],
        "path": str(ret["path"]),
        "taken_at": str(ret["taken_at"]),
        "camera_make": ret.get("camera_make", ""),
        "camera_model": ret.get("camera_model", ""),
        "reason": ret["reason"],
    })

    return ret


if __name__ == "__main__":
    import argparse
    import sys
    from datetime import timedelta

    from fetch import get_candidates

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

    candidates = get_candidates(target)
    if not candidates:
        print("候補なし")
        sys.exit(0)

    result = select(candidates, target)
    print(f"\n選定結果:")
    print(f"  ファイル  : {result['filename']}")
    print(f"  撮影時刻  : {result['taken_at']}")
    print(f"  選定理由  : {result['reason']}")
    print(f"  出力パス  : {result['output_path']}")
