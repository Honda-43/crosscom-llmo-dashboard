"""Make ``src/`` and ``app/`` importable — the pipeline modules import each
other flatly (``import settings``) because GitHub Actions runs them from
inside ``src/``, and the dashboard pages do the same from inside ``app/``."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for directory in (ROOT / "src", ROOT / "app"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
