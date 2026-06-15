#!/usr/bin/env python3
"""
Dropbox の Camera Uploads をローカルに同期する。

月単位で rclone copy を実行し、同期先を YYYY/MM/ サブディレクトリにする。
これにより：
- 旧来の全写真（2026-06 以前）を誤ってダウンロードしない
- 再実行時に既存ファイルを再ダウンロードしない（rclone が宛先で判断）
- rclone copy（sync ではない）なのでローカルファイルの削除は起きない
"""
import logging
import subprocess
import sys
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

REMOTE_SRC = "dropbox:カメラアップロード"
LOCAL_DST = Path(__file__).parent / "images" / "camera_uploads"

START_YEAR = 2026
START_MONTH = 6


def _target_months() -> list[tuple[int, int]]:
    # 2026-06 から当月までの (year, month) を列挙
    today = date.today()
    result = []
    for year in range(START_YEAR, today.year + 1):
        start_m = START_MONTH if year == START_YEAR else 1
        end_m = today.month if year == today.year else 12
        for month in range(start_m, end_m + 1):
            result.append((year, month))
    return result


def sync(dry_run: bool = False) -> int:
    months = _target_months()
    errors = 0

    for year, month in months:
        pattern = f"{year}-{month:02d}-*"
        subdir = LOCAL_DST / f"{year}" / f"{month:02d}"
        subdir.mkdir(parents=True, exist_ok=True)

        cmd = [
            "rclone", "copy", REMOTE_SRC, str(subdir),
            "--include", pattern,
            "--verbose", "--stats-one-line",
        ]
        if dry_run:
            cmd.append("--dry-run")

        logger.info("同期: %s → %s/%04d/%02d/", REMOTE_SRC, LOCAL_DST.name, year, month)
        result = subprocess.run(cmd, capture_output=True, text=True)

        for line in (result.stdout + result.stderr).splitlines():
            if line.strip():
                logger.info("[rclone %04d/%02d] %s", year, month, line)

        if result.returncode != 0:
            logger.error("rclone 失敗 (%04d/%02d): 終了コード %d", year, month, result.returncode)
            errors += 1

    if errors:
        logger.error("%d 件のエラーが発生しました", errors)
        return 1

    logger.info("全月の同期完了")
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dropbox Camera Uploads をローカルに同期")
    parser.add_argument("--dry-run", action="store_true", help="実際にはコピーせず確認のみ")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    sys.exit(sync(dry_run=args.dry_run))
