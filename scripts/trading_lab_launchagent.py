"""Thin local LaunchAgent CLI; management always requires an explicit command."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trading_lab.operator.launchd import launchagent_main

if __name__ == "__main__":
    raise SystemExit(launchagent_main())
