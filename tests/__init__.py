"""Product unit tests for Buggcraft Launcher."""
from pathlib import Path
import sys

# Some QML fixtures are shared by both module and discovery invocations.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
