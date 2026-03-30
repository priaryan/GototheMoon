"""
IMC Prosperity 3 - Emerald Market Maker Algorithm

This is the main entry point for the backtester.
Run with: prosperity3bt algorithm.py 0
"""

import sys
from pathlib import Path

# Add src directory to path so we can import our modules
src_path = Path(__file__).parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Import and export the Trader class
from trader import Trader

__all__ = ["Trader"]
