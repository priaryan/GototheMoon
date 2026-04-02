"""
Backtesting Harness for Parameter Optimization
Runs multiple parameter configurations and aggregates results.
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, List
import csv


class BacktestRunner:
    """Execute backtests with different parameter configurations."""
    
    def __init__(self, rust_binary: str = "./target/release/imc_backtester"):
        """
        Args:
            rust_binary: Path to compiled Rust backtester binary
        """
        self.rust_binary = Path(rust_binary)
        self.results = []
    
    def run_config(self, config_id: int, config_path: str, data_path: str = "./data/raw") -> dict:
        """
        Run a single backtest configuration.
        
        Args:
            config_id: Config ID for reference
            config_path: Path to config JSON file
            data_path: Path to raw data directory
        
        Returns:
            Result dictionary with final P&L
        """
        result = {
            "config_id": config_id,
            "config_file": config_path,
            "status": "pending",
            "final_pnl": 0,
            "max_drawdown": 0,
            "sharpe_ratio": 0,
        }
        
        if not self.rust_binary.exists():
            result["status"] = "error"
            result["error"] = f"Rust binary not found: {self.rust_binary}"
            return result
        
        try:
            cmd = [
                str(self.rust_binary),
                "--config", config_path,
                "--data", data_path,
                "--log", f"results/backtest_{config_id:04d}.log",
            ]
            
            output = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if output.returncode == 0:
                result["status"] = "success"
                result["stdout"] = output.stdout
                
                # Parse output for results (adjust based on your Rust output format)
                lines = output.stdout.split('\n')
                for line in lines:
                    if 'final_pnl' in line.lower():
                        try:
                            result["final_pnl"] = int(''.join(c for c in line if c.isdigit() or c == '-'))
                        except:
                            pass
            else:
                result["status"] = "failed"
                result["error"] = output.stderr
        
        except subprocess.TimeoutExpired:
            result["status"] = "timeout"
            result["error"] = "Backtest exceeded 5 minute timeout"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
        
        self.results.append(result)
        return result
    
    def run_all_configs(self, config_dir: str = "./parameter_configs") -> List[dict]:
        """
        Run all configurations in a directory.
        
        Args:
            config_dir: Directory containing config JSONs
        
        Returns:
            List of all results
        """
        config_path = Path(config_dir)
        config_files = sorted(config_path.glob("config_*.json"))
        
        print(f"Found {len(config_files)} configurations to backtest")
        
        for i, config_file in enumerate(config_files):
            config_id = int(config_file.stem.split('_')[1])
            print(f"\n[{i+1}/{len(config_files)}] Running config {config_id}...", end=" ", flush=True)
            
            result = self.run_config(config_id, str(config_file))
            print(f"{result['status']}")
        
        return self.results
    
    def rank_results(self, metric: str = "final_pnl") -> List[dict]:
        """
        Rank results by a specific metric.
        
        Args:
            metric: Metric to sort by (final_pnl, sharpe_ratio, etc.)
        
        Returns:
            Sorted results (best first)
        """
        successful = [r for r in self.results if r["status"] == "success"]
        ranked = sorted(successful, key=lambda x: x.get(metric, 0), reverse=True)
        return ranked
    
    def export_results(self, output_file: str = "backtest_results.csv"):
        """
        Export all results to CSV.
        
        Args:
            output_file: Output CSV path
        """
        if not self.results:
            print("No results to export")
            return
        
        with open(output_file, 'w', newline='') as f:
            fieldnames = ['config_id', 'status', 'final_pnl', 'max_drawdown', 'sharpe_ratio']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for result in self.results:
                row = {k: result.get(k, '') for k in fieldnames}
                writer.writerow(row)
        
        print(f"✓ Exported results to {output_file}")
    
    def print_summary(self):
        """Print summary of backtest results."""
        successful = [r for r in self.results if r["status"] == "success"]
        failed = len(self.results) - len(successful)
        
        print(f"\n=== BACKTEST SUMMARY ===")
        print(f"Total runs: {len(self.results)}")
        print(f"Successful: {len(successful)}")
        print(f"Failed: {failed}")
        
        if successful:
            best = max(successful, key=lambda x: x.get("final_pnl", 0))
            worst = min(successful, key=lambda x: x.get("final_pnl", 0))
            avg_pnl = sum(r.get("final_pnl", 0) for r in successful) / len(successful)
            
            print(f"\nP&L Statistics:")
            print(f"  Best:    {best['final_pnl']} (config {best['config_id']})")
            print(f"  Worst:   {worst['final_pnl']} (config {worst['config_id']})")
            print(f"  Average: {avg_pnl:.0f}")
            
            # Show top 5
            ranked = self.rank_results()
            print(f"\nTop 5 Configurations:")
            for i, result in enumerate(ranked[:5], 1):
                print(f"  {i}. Config {result['config_id']}: {result['final_pnl']}")


if __name__ == "__main__":
    import sys
    
    rust_binary = sys.argv[1] if len(sys.argv) > 1 else "./target/release/imc_backtester"
    config_dir = sys.argv[2] if len(sys.argv) > 2 else "./parameter_configs"
    
    runner = BacktestRunner(rust_binary)
    runner.run_all_configs(config_dir)
    runner.export_results()
    runner.print_summary()
