r"""Run incremental updates for a list of areas (reads `src/config.yaml` for default area list).

This script can be scheduled (Windows Task Scheduler) or called from the batch file `scripts\schedule_incremental.bat`.
"""

import sys
from pathlib import Path

# Add parent directory to path so 'src' can be imported
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import concurrent.futures
import yaml
import logging

from src.ingest.incremental_ingest import incremental_update

logging.basicConfig(level=logging.INFO)


def load_config():
    cfg_path = Path(__file__).parents[1] / "src" / "config.yaml"
    if not cfg_path.exists():
        cfg_path = Path(__file__).parents[1] / "src" / "config.yaml.example"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _run_one(area: str, api_key: str, lookback_hours: int):
    incremental_update(area, api_key=api_key, lookback_hours=lookback_hours)
    return area


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--workers", type=int, default=0, help="0 uses a small auto pool"
    )
    p.add_argument(
        "--executor", choices=["thread", "process"], default="thread"
    )
    p.add_argument("--lookback-hours", type=int, default=6)
    args = p.parse_args()

    cfg = load_config()
    api_key = (cfg.get("entsoe") or {}).get("api_key")
    areas = cfg.get("entsoe", {}).get("areas") or ["DE_LU"]
    if not areas:
        return

    workers = args.workers or min(4, len(areas))
    if workers <= 1 or len(areas) == 1:
        for a in areas:
            try:
                incremental_update(
                    a, api_key=api_key, lookback_hours=args.lookback_hours
                )
            except Exception as e:
                logging.exception("Failed incremental update for %s: %s", a, e)
        return

    executor_cls = (
        concurrent.futures.ThreadPoolExecutor
        if args.executor == "thread"
        else concurrent.futures.ProcessPoolExecutor
    )
    logging.info(
        "Running incremental updates with %s pool (%d workers)",
        args.executor,
        workers,
    )
    with executor_cls(max_workers=workers) as executor:
        futures = {
            executor.submit(_run_one, area, api_key, args.lookback_hours): area
            for area in areas
        }
        for fut in concurrent.futures.as_completed(futures):
            area = futures[fut]
            try:
                fut.result()
            except Exception as e:
                logging.exception(
                    "Failed incremental update for %s: %s", area, e
                )


if __name__ == "__main__":
    main()
