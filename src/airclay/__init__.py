"""AirClay. Camera/ML code runs outside Blender."""
import os
from pathlib import Path

# Keep Matplotlib's cache inside the project, including sandboxed tests.
os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[2] / ".cache/matplotlib"))
__version__ = "0.1.0"
