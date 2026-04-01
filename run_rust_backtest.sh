#!/bin/bash
# Convenience wrapper – runs the Rust backtester with correct Python linkage
# Usage:
#   ./run_rust_backtest.sh                                  # auto-detect trader
#   ./run_rust_backtest.sh bestfornow.py                    # specific trader
#   ./run_rust_backtest.sh submission_edit.py --persist      # with extra flags

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUST_BT_DIR="$SCRIPT_DIR/../prosperity_rust_backtester"
TRADERS_DIR="$RUST_BT_DIR/traders"

# Resolve trader file
if [[ $# -ge 1 && ! "$1" == --* ]]; then
    TRADER_FILE="$1"
    shift
    # If not an absolute path, look in our repo first, then Rust backtester traders/
    if [[ ! -f "$TRADER_FILE" ]]; then
        if [[ -f "$SCRIPT_DIR/$TRADER_FILE" ]]; then
            TRADER_FILE="$SCRIPT_DIR/$TRADER_FILE"
        fi
    fi
    # Copy to Rust backtester traders/ dir
    cp "$TRADER_FILE" "$TRADERS_DIR/$(basename "$TRADER_FILE")"
    TRADER_ARG="traders/$(basename "$TRADER_FILE")"
else
    TRADER_ARG=""
fi

cd "$RUST_BT_DIR"
source "$HOME/.cargo/env" 2>/dev/null || true

export DYLD_FRAMEWORK_PATH="/Library/Developer/CommandLineTools/Library/Frameworks"
export DYLD_LIBRARY_PATH="/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib"
export RUSTFLAGS="-L /Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib"
export PYO3_PYTHON="/usr/bin/python3"

if [[ -n "$TRADER_ARG" ]]; then
    cargo run --release -- --trader "$TRADER_ARG" --dataset tutorial "$@"
else
    cargo run --release -- --dataset tutorial "$@"
fi
