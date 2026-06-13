import os
import sys

if __package__ in (None, ""):
    # Allow ``python vdai/__main__.py`` (direct file run) in addition to
    # ``python -m vdai`` by making the package importable first.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from vdai.cli import main
else:
    from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
