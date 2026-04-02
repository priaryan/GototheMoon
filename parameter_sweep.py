"""
Parameter Sweep Generator for bestfornow_v6
Generates all parameter combinations for Rust backtesting.
"""

import json
import itertools
from pathlib import Path


class ParameterSweeper:
    """Generate parameter combinations for EMERALDS and TOMATOES strategies."""
    
    # EMERALDS parameters
    EMERALDS_FAIR = [10000]  # Fixed baseline
    EMERALDS_INV_PENALTY = [0.02, 0.04, 0.05, 0.08, 0.10]
    
    # TOMATOES parameters
    TOMATOES_EMA_ALPHA = [0.05, 0.10, 0.15, 0.20]
    TOMATOES_INV_PENALTY = [0.01, 0.02, 0.05, 0.08]
    TOMATOES_TAKE_MARGIN = [0.10, 0.25, 0.50, 1.00]
    TOMATOES_FLATTEN_THRESH = [1, 2, 3, 5]
    
    def __init__(self, output_dir: str = "./parameter_configs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.configs = []
    
    def generate(self) -> int:
        """Generate all parameter combinations and save to JSON files."""
        config_id = 0
        
        emeralds_combos = itertools.product(
            self.EMERALDS_FAIR,
            self.EMERALDS_INV_PENALTY
        )
        
        tomatoes_combos = itertools.product(
            self.TOMATOES_EMA_ALPHA,
            self.TOMATOES_INV_PENALTY,
            self.TOMATOES_TAKE_MARGIN,
            self.TOMATOES_FLATTEN_THRESH
        )
        
        for e_fair, e_inv in emeralds_combos:
            for t_ema, t_inv, t_margin, t_thresh in tomatoes_combos:
                config = {
                    "id": config_id,
                    "emeralds": {
                        "FAIR": e_fair,
                        "INV_PENALTY": e_inv,
                    },
                    "tomatoes": {
                        "EMA_ALPHA": t_ema,
                        "INV_PENALTY": t_inv,
                        "TAKE_MARGIN": t_margin,
                        "FLATTEN_THRESH": t_thresh,
                    }
                }
                
                config_path = self.output_dir / f"config_{config_id:04d}.json"
                with open(config_path, "w") as f:
                    json.dump(config, f, indent=2)
                
                self.configs.append(config)
                config_id += 1
        
        return config_id
    
    def get_summary(self) -> dict:
        """Return summary of parameter sweep."""
        e_combos = len(self.EMERALDS_FAIR) * len(self.EMERALDS_INV_PENALTY)
        t_combos = (len(self.TOMATOES_EMA_ALPHA) * len(self.TOMATOES_INV_PENALTY) * 
                   len(self.TOMATOES_TAKE_MARGIN) * len(self.TOMATOES_FLATTEN_THRESH))
        total = e_combos * t_combos
        
        return {
            "total_configs": total,
            "emeralds_combinations": e_combos,
            "tomatoes_combinations": t_combos,
            "output_directory": str(self.output_dir),
            "parameter_ranges": {
                "emeralds": {
                    "FAIR": self.EMERALDS_FAIR,
                    "INV_PENALTY": self.EMERALDS_INV_PENALTY,
                },
                "tomatoes": {
                    "EMA_ALPHA": self.TOMATOES_EMA_ALPHA,
                    "INV_PENALTY": self.TOMATOES_INV_PENALTY,
                    "TAKE_MARGIN": self.TOMATOES_TAKE_MARGIN,
                    "FLATTEN_THRESH": self.TOMATOES_FLATTEN_THRESH,
                }
            }
        }


if __name__ == "__main__":
    sweeper = ParameterSweeper()
    total = sweeper.generate()
    
    summary = sweeper.get_summary()
    print(f"✓ Generated {total} parameter configurations")
    print(f"  Emeralds: {summary['emeralds_combinations']} combos")
    print(f"  Tomatoes: {summary['tomatoes_combinations']} combos")
    print(f"  Location: {summary['output_directory']}")
    
    # Save summary
    summary_path = sweeper.output_dir / "sweep_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  Summary: {summary_path}")
