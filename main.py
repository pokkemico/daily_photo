#!/usr/bin/env python3
import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

LOG_PATH = Path(__file__).parent / "logs" / "main.log"

from fetch import get_candidates
from notion import save
from selector import SELECTIONS_JSON, select

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def _used_filenames() -> set[str]:
    if not SELECTIONS_JSON.exists():
        return set()
    data = json.loads(SELECTIONS_JSON.read_text())
    return {entry["filename"] for entry in data.values()}


def run(target_date: date) -> None:
    logger.info("===== %s 処理開始 =====", target_date)

    candidates = get_candidates(target_date, _used_filenames())
    if not candidates:
        logger.info("%s: 候補なし。スキップ", target_date)
        return

    result = select(candidates, target_date)
    save(result, target_date)
    logger.info("===== %s 処理完了 =====", target_date)


def main() -> None:
    parser = argparse.ArgumentParser(description="今日の一枚を選定してNotionに登録")
    parser.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD", help="開始日")
    parser.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD", help="終了日")
    args = parser.parse_args()

    _setup_logging()

    if args.date_from and args.date_to:
        start = date.fromisoformat(args.date_from)
        end = date.fromisoformat(args.date_to)
        if start > end:
            print("--from は --to 以前の日付を指定してください", file=sys.stderr)
            sys.exit(1)
        current = start
        while current <= end:
            run(current)
            current += timedelta(days=1)
    elif args.date_from or args.date_to:
        print("--from と --to は両方指定してください", file=sys.stderr)
        sys.exit(1)
    else:
        run(date.today() - timedelta(days=1))


if __name__ == "__main__":
    main()
