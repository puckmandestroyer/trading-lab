"""Thin explicit operator entrypoint; importing it never starts a runtime."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trading_lab.operator.demo_runtime import runtime_main

if __name__ == "__main__":
    raise SystemExit(runtime_main())
