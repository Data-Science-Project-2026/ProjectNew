import sys
from pathlib import Path

# Ensure the package root (this `src` folder) is on sys.path so tests
# can import top-level packages like `models` and `pipeline`.
root = Path(__file__).resolve().parent
root_str = str(root)
if root_str not in sys.path:
    sys.path.insert(0, root_str)
