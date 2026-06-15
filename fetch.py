import logging
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from PIL import Image

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

logger = logging.getLogger(__name__)

CAMERA_UPLOADS = Path(__file__).parent / "images" / "camera_uploads"

EXIF_DATE_TIME_ORIGINAL = 36867
EXIF_MAKE = 271
EXIF_MODEL = 272

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}

TIME_SLOTS = [
    ("早朝",  5,  9),
    ("朝",    9, 12),
    ("昼",   12, 15),
    ("午後", 15, 18),
    ("夕方", 18, 20),
    ("夜",   20,  5),  # 20:00〜翌4:59（折り返し）
]


def _read_exif(path: Path) -> dict[int, Any]:
    try:
        with Image.open(path) as img:
            return dict(img.getexif())
    except Exception:
        return {}


def _taken_at(path: Path, exif: dict) -> datetime:
    raw = exif.get(EXIF_DATE_TIME_ORIGINAL, "")
    if raw:
        try:
            return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
        except ValueError:
            pass
    # EXIF が読めない場合はファイルの mtime で代替
    return datetime.fromtimestamp(path.stat().st_mtime)


def _is_camera_shot(exif: dict) -> bool:
    return bool(exif.get(EXIF_MAKE) or exif.get(EXIF_MODEL))


def _in_slot(hour: int, start: int, end: int) -> bool:
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # 折り返し（夜）


def _load_day(target_date: date) -> list[dict]:
    subdir = CAMERA_UPLOADS / f"{target_date.year:04d}" / f"{target_date.month:02d}"
    if not subdir.exists():
        logger.debug("%s: ディレクトリなし (%s)", target_date, subdir)
        return []

    results = []
    for path in sorted(subdir.iterdir()):
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        exif = _read_exif(path)
        taken = _taken_at(path, exif)
        if taken.date() != target_date:
            continue
        if not _is_camera_shot(exif):
            continue
        results.append({
            "filename": path.name,
            "path": path,
            "taken_at": taken,
            "camera_make": exif.get(EXIF_MAKE, ""),
            "camera_model": exif.get(EXIF_MODEL, ""),
        })

    logger.debug("%s: %d枚", target_date, len(results))
    return results


def _sample_by_slot(items: list[dict]) -> list[dict]:
    slots: dict[str, list] = {name: [] for name, _, _ in TIME_SLOTS}
    for item in items:
        hour = item["taken_at"].hour
        for name, start, end in TIME_SLOTS:
            if _in_slot(hour, start, end):
                slots[name].append(item)
                break

    result = []
    for name, slot_items in slots.items():
        if slot_items:
            result.append(random.choice(slot_items))
    return result


def get_candidates(
    target_date: date,
    used_filenames: set[str] | None = None,
) -> list[dict]:
    """
    指定日の候補写真リストを返す。
    0枚なら直近7日からフォールバック。それも0枚なら空リスト。
    """
    items = _load_day(target_date)
    candidates = _sample_by_slot(items)
    logger.info("%s: カメラ撮影 %d枚 → 候補 %d枚", target_date, len(items), len(candidates))

    if candidates:
        return candidates

    logger.info("候補0枚のためフォールバック開始（直近7日）")
    if used_filenames is None:
        used_filenames = set()

    pool = []
    for days_ago in range(1, 8):
        past_date = target_date - timedelta(days=days_ago)
        pool.extend(_load_day(past_date))

    unused = [i for i in pool if i["filename"] not in used_filenames]
    if unused:
        chosen = random.choice(unused)
        logger.info("フォールバック採用: %s", chosen["filename"])
        return [chosen]

    logger.info("フォールバックも0枚。処理をスキップします")
    return []


if __name__ == "__main__":
    import argparse
    import sys

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
        print("候補なし（フォールバックも0枚）")
        sys.exit(0)

    print(f"\n候補 {len(candidates)}枚:")
    for i, item in enumerate(candidates, 1):
        print(f"  [{i}] {item['filename']}")
        print(f"       撮影時刻: {item['taken_at']}")
        print(f"       カメラ: {item['camera_make']} {item['camera_model']}")
        print(f"       パス: {item['path']}")
