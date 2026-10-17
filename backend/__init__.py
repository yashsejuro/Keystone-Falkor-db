import sys
from pathlib import Path

# Add backend directory to sys.path so modules can import each other seamlessly
_backend_dir = str(Path(__file__).resolve().parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
