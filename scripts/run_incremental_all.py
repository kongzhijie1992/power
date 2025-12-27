"""Run incremental updates for a list of areas (reads `src/config.yaml` for default area list).

This script can be scheduled (Windows Task Scheduler) or called from the batch file `scripts\schedule_incremental.bat`.
"""

import sys
from pathlib import Path

# Add parent directory to path so 'src' can be imported
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
import logging

from src.ingest.incremental_ingest import incremental_update

logging.basicConfig(level=logging.INFO)


def load_config():
    cfg_path = Path(__file__).parents[1] / "src" / "config.yaml"
    if not cfg_path.exists():
        cfg_path = Path(__file__).parents[1] / "src" / "config.yaml.example"
    return yaml.safe_load(open(cfg_path))


def main():
    cfg = load_config()
    api_key = (cfg.get("entsoe") or {}).get("api_key")
    areas = cfg.get("entsoe", {}).get("areas") or ["DE"]
    for a in areas:
        try:
            incremental_update(a, api_key=api_key, lookback_hours=6)
        except Exception as e:
            logging.exception("Failed incremental update for %s: %s", a, e)


if __name__ == "__main__":
    main()
