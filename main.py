# pyright: reportMissingImports=false
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _entry() -> None:
    from yusuga.surfaces.cli.app import main

    main()


if __name__ == "__main__":
    _entry()
