#!/usr/bin/env python
"""
One-time setup script for IMC Prosperity 4 backtester.
Run this once: python setup_backtester.py

This will:
1. Copy your data files to the backtester resources
2. Install the backtester in editable mode
3. Verify everything works

After this, just run: python -m prosperity3bt algorithm.py 0
"""

import shutil
import subprocess
import sys
from pathlib import Path

def setup_backtester():
    project_root = Path(__file__).parent
    data_dir = project_root / "data" / "raw"
    backtester_dir = project_root / "backtests" / "imc-prosperity-3-backtester"
    resources_dir = backtester_dir / "prosperity3bt" / "resources" / "round0"
    
    print("🚀 Setting up IMC Prosperity 4 Backtester...\n")
    
    # Step 1: Verify data exists
    if not data_dir.exists():
        print(f"❌ Error: {data_dir} not found!")
        sys.exit(1)
    
    csv_files = list(data_dir.glob("*.csv"))
    if not csv_files:
        print(f"❌ Error: No CSV files found in {data_dir}")
        sys.exit(1)
    
    print(f"✓ Found {len(csv_files)} CSV files:")
    for f in csv_files:
        print(f"  - {f.name}")
    
    # Step 2: Copy CSV files to backtester resources
    print(f"\n📋 Copying files to {resources_dir}...")
    resources_dir.mkdir(parents=True, exist_ok=True)
    for csv_file in csv_files:
        dest = resources_dir / csv_file.name
        shutil.copy2(csv_file, dest)
        print(f"  ✓ {csv_file.name}")
    
    # Step 3: Install backtester in editable mode
    print(f"\n📦 Installing backtester...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", str(backtester_dir)],
        cwd=project_root,
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        print("  ✓ Backtester installed successfully")
    else:
        print(f"  ❌ Installation failed:")
        print(result.stderr)
        sys.exit(1)
    
    # Step 4: Verify setup
    print(f"\n✅ Setup complete!\n")
    print("=" * 60)
    print("You can now run backtest with:")
    print("  python -m prosperity3bt algorithm.py 0")
    print("")
    print("Backtest commands:")
    print("  python -m prosperity3bt algorithm.py 0           # All days")
    print("  python -m prosperity3bt algorithm.py 0-0         # Specific day")
    print("  python -m prosperity3bt algorithm.py 0 --merge-pnl  # Merge PnL")
    print("=" * 60)

if __name__ == "__main__":
    setup_backtester()
