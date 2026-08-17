"""Make ``src/`` importable — the pipeline modules import each other flatly
(``import settings``) because GitHub Actions runs them from inside ``src/``."""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
