"""
Log Visualizer for Trading Backtest Results
Parses logs and creates interactive visualizations of trade decisions.
"""

import json
import csv
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime


@dataclass
class Trade:
    """Represents a single trade execution."""
    timestamp: str
    product: str
    action: str  # BUY or SELL
    price: int
    quantity: int
    position_before: int
    position_after: int
    pnl: int
    market_mid: Optional[float] = None
    reason: Optional[str] = None  # Why this trade was made


@dataclass
class MarketSnapshot:
    """Market state at a point in time."""
    timestamp: str
    product: str
    bid_wall: Optional[int] = None
    ask_wall: Optional[int] = None
    mid_price: Optional[float] = None
    bid_volume: Optional[int] = None
    ask_volume: Optional[int] = None
    position: int = 0
    pnl: int = 0


class LogParser:
    """Parse trading logs and extract trade/market data."""
    
    def __init__(self, log_file: str):
        self.log_file = Path(log_file)
        self.trades: List[Trade] = []
        self.market_snapshots: Dict[str, List[MarketSnapshot]] = {}
        
        if not self.log_file.exists():
            raise FileNotFoundError(f"Log file not found: {log_file}")
    
    def parse_csv_log(self) -> Tuple[List[Trade], Dict[str, List[MarketSnapshot]]]:
        """
        Parse CSV log format from IMC backtester.
        Expected format: timestamp,product,trade_type,price,qty,position,pnl,bid1,bid_vol1,ask1,ask_vol1,...
        """
        trades = []
        snapshots = {}
        
        try:
            # Increase field size limit for large fields
            import csv
            csv.field_size_limit(int(1e7))
            
            with open(self.log_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    timestamp = row.get('timestamp', '')
                    product = row.get('product', '')
                    
                    # Initialize product snapshots if needed
                    if product not in snapshots:
                        snapshots[product] = []
                    
                    # Extract market data
                    try:
                        bid_wall = int(row.get('bid_price_1')) if row.get('bid_price_1') else None
                        ask_wall = int(row.get('ask_price_1')) if row.get('ask_price_1') else None
                        mid_price = float(row.get('mid_price')) if row.get('mid_price') else None
                        position = int(row.get('position', 0))
                        pnl = int(row.get('pnl', 0))
                        
                        snap = MarketSnapshot(
                            timestamp=timestamp,
                            product=product,
                            bid_wall=bid_wall,
                            ask_wall=ask_wall,
                            mid_price=mid_price,
                            position=position,
                            pnl=pnl
                        )
                        snapshots[product].append(snap)
                    except (ValueError, TypeError):
                        pass
                    
                    # Extract trade if present
                    if row.get('trade_type'):
                        try:
                            trade = Trade(
                                timestamp=timestamp,
                                product=product,
                                action=row.get('trade_type', ''),
                                price=int(row.get('trade_price', 0)),
                                quantity=int(row.get('trade_qty', 0)),
                                position_before=int(row.get('position_before', 0)),
                                position_after=int(row.get('position_after', 0)),
                                pnl=int(row.get('pnl', 0)),
                                market_mid=mid_price,
                                reason=row.get('reason', '')
                            )
                            trades.append(trade)
                        except (ValueError, TypeError):
                            pass
        
        except Exception as e:
            print(f"Error parsing CSV log: {e}")
        
        self.trades = trades
        self.market_snapshots = snapshots
        return trades, snapshots
    
    def parse_json_log(self) -> Tuple[List[Trade], Dict[str, List[MarketSnapshot]]]:
        """Parse JSON-formatted log from IMC backtester (with CSV activitiesLog)."""
        try:
            with open(self.log_file, 'r') as f:
                data = json.load(f)
            
            trades = []
            snapshots = {}
            
            # Check for activitiesLog (CSV format with semicolon delimiter)
            if 'activitiesLog' in data and isinstance(data['activitiesLog'], str):
                activities_csv = data['activitiesLog']
                lines = activities_csv.strip().split('\n')
                
                if lines:
                    # Parse header
                    header = lines[0].split(';')
                    header_lower = [h.lower().replace('_', '').replace(' ', '') for h in header]
                    
                    # Parse data rows
                    for line in lines[1:]:
                        if not line.strip():
                            continue
                        
                        parts = line.split(';')
                        if len(parts) < len(header):
                            continue
                        
                        try:
                            row_dict = dict(zip(header_lower, parts))
                            
                            product = row_dict.get('product', '').strip()
                            timestamp = row_dict.get('timestamp', '0').strip()
                            
                            if not product:
                                continue
                            
                            if product not in snapshots:
                                snapshots[product] = []
                            
                            # Parse market data
                            bid_price_1 = row_dict.get('bidprice1', '').strip()
                            ask_price_1 = row_dict.get('askprice1', '').strip()
                            mid_price = row_dict.get('midprice', '').strip()
                            pnl = row_dict.get('profitandloss', '0').strip()
                            
                            try:
                                bid_wall = int(float(bid_price_1)) if bid_price_1 else None
                                ask_wall = int(float(ask_price_1)) if ask_price_1 else None
                                mid = float(mid_price) if mid_price else None
                                pnl_val = int(float(pnl)) if pnl else 0
                            except (ValueError, TypeError):
                                bid_wall = ask_wall = mid = None
                                pnl_val = 0
                            
                            snap = MarketSnapshot(
                                timestamp=timestamp,
                                product=product,
                                bid_wall=bid_wall,
                                ask_wall=ask_wall,
                                mid_price=mid,
                                position=0,
                                pnl=pnl_val
                            )
                            snapshots[product].append(snap)
                        except Exception:
                            continue
            
            # Also check for tradeHistory if present
            if 'tradeHistory' in data and isinstance(data['tradeHistory'], list):
                for t in data['tradeHistory']:
                    symbol = t.get('symbol', '').strip() if t.get('symbol') else ''
                    timestamp = str(t.get('timestamp', '')).strip()
                    
                    buyer = str(t.get('buyer', '')).strip() if t.get('buyer') else ''
                    seller = str(t.get('seller', '')).strip() if t.get('seller') else ''
                    
                    # Include trades where SUBMISSION is buyer or seller
                    if buyer == 'SUBMISSION' or seller == 'SUBMISSION':
                        action = 'BUY' if buyer == 'SUBMISSION' else 'SELL'
                        
                        try:
                            trade = Trade(
                                timestamp=timestamp,
                                product=symbol,
                                action=action,
                                price=int(float(t.get('price', 0))),
                                quantity=int(t.get('quantity', 0)),
                                position_before=0,
                                position_after=0,
                                pnl=0,
                                market_mid=float(t.get('price', 0))
                            )
                            trades.append(trade)
                        except (ValueError, TypeError):
                            pass
            
            self.trades = trades
            self.market_snapshots = snapshots
            return trades, snapshots
        
        except Exception as e:
            print(f"Error parsing JSON log: {e}")
            import traceback
            traceback.print_exc()
            return [], {}


class LogVisualizer:
    """Create visualizations from parsed log data."""
    
    def __init__(self, log_file: str):
        self.parser = LogParser(log_file)
        self.trades, self.snapshots = self._parse_log()
    
    def _parse_log(self) -> Tuple[List[Trade], Dict[str, List[MarketSnapshot]]]:
        """Try to parse log, attempting both formats."""
        # Check if it's JSON by content
        try:
            with open(self.parser.log_file, 'r') as f:
                first_char = f.read(1)
                if first_char == '{':
                    # It's JSON
                    return self.parser.parse_json_log()
        except Exception:
            pass
        
        # Try CSV format
        try:
            return self.parser.parse_csv_log()
        except Exception:
            pass
        
        # Fall back to JSON
        try:
            return self.parser.parse_json_log()
        except Exception as e:
            print(f"Could not parse log file: {e}")
            import traceback
            traceback.print_exc()
            return [], {}
    
    def generate_summary(self) -> dict:
        """Generate summary statistics from parsed data."""
        summary = {
            "total_trades": len(self.trades),
            "by_product": {},
            "by_action": {"BUY": 0, "SELL": 0},
        }
        
        for trade in self.trades:
            # By product
            if trade.product not in summary["by_product"]:
                summary["by_product"][trade.product] = {
                    "count": 0,
                    "buys": 0,
                    "sells": 0,
                    "total_volume": 0,
                }
            summary["by_product"][trade.product]["count"] += 1
            summary["by_product"][trade.product]["total_volume"] += trade.quantity
            
            # By action
            if trade.action.upper() == "BUY":
                summary["by_product"][trade.product]["buys"] += 1
                summary["by_action"]["BUY"] += 1
            elif trade.action.upper() == "SELL":
                summary["by_product"][trade.product]["sells"] += 1
                summary["by_action"]["SELL"] += 1
        
        return summary
    
    def export_trade_timeline(self, output_file: str = "trade_timeline.csv"):
        """Export trades to CSV for inspection."""
        import csv
        
        with open(output_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp', 'product', 'action', 'price', 'quantity',
                'position_before', 'position_after', 'pnl', 'market_mid', 'reason'
            ])
            for trade in self.trades:
                writer.writerow([
                    trade.timestamp,
                    trade.product,
                    trade.action,
                    trade.price,
                    trade.quantity,
                    trade.position_before,
                    trade.position_after,
                    trade.pnl,
                    trade.market_mid or '',
                    trade.reason or ''
                ])
        
        print(f"✓ Exported {len(self.trades)} trades to {output_file}")
    
    def create_matplotlib_chart(self, product: str, output_file: str = None):
        """Create matplotlib visualization of position, P&L, and trades with better trade visibility."""
        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            from matplotlib.patches import Rectangle
            import numpy as np
        except ImportError:
            print("matplotlib not installed. Install with: pip install matplotlib")
            return
        
        if product not in self.snapshots or not self.snapshots[product]:
            print(f"No data for product {product}")
            return
        
        snaps = self.snapshots[product]
        trades_for_product = [t for t in self.trades if t.product == product]
        
        # Extract data and create timestamp mapping
        snapshots_ts = [int(s.timestamp) for s in snaps]
        positions = [s.position for s in snaps]
        pnls = [s.pnl for s in snaps]

        # Compute spread (ask - bid) per snapshot and normalize for plotting
        spreads = []
        for s in snaps:
            try:
                if s.ask_wall is not None and s.bid_wall is not None:
                    spreads.append(max(0, s.ask_wall - s.bid_wall))
                else:
                    spreads.append(0)
            except Exception:
                spreads.append(0)

        max_spread = max(spreads) if spreads else 1
        if max_spread == 0:
            max_spread = 1
        norm_spread = [(float(x) / max_spread) * 0.4 for x in spreads]
        
        # Create timestamp->index mapping for trades
        ts_to_idx = {ts: i for i, ts in enumerate(snapshots_ts)}
        
        # Map each trade to its snapshot index
        trade_indices = []
        for t in trades_for_product:
            try:
                trade_ts = int(t.timestamp)
                # Find closest snapshot to this trade
                if trade_ts in ts_to_idx:
                    idx = ts_to_idx[trade_ts]
                else:
                    # Find nearest timestamp
                    idx = min(range(len(snapshots_ts)), key=lambda i: abs(snapshots_ts[i] - trade_ts))
                trade_indices.append(idx)
            except (ValueError, TypeError):
                trade_indices.append(0)
        
        # Use snapshot indices for x-axis
        timestamps = list(range(len(snaps)))
        
        # Create figure with subplots
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(16, 10), sharex=True)
        fig.suptitle(f'{product} Trading Analysis - Detailed View', fontsize=16, fontweight='bold')
        
        # Plot 1: Position over time with LARGE trade markers
        ax1.plot(timestamps, positions, marker='o', linestyle='-', color='blue', linewidth=1.5, label='Position', markersize=2, alpha=0.7)
        ax1.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
        ax1.set_ylabel('Position', fontweight='bold')
        ax1.grid(True, alpha=0.3)
        
        # Draw a faint spread band behind trades so spread is visible
        try:
            ax1.fill_between(timestamps, [-v for v in norm_spread], norm_spread, color='gray', alpha=0.12)
            ax1.plot(timestamps, norm_spread, color='gray', linewidth=0.6, alpha=0.5)
        except Exception:
            pass

        # Overlay trades with MUCH LARGER markers at correct positions
        for idx, trade in enumerate(trades_for_product):
            trade_snapshot_idx = trade_indices[idx]
            color = 'green' if trade.action.upper() == 'BUY' else 'red'
            marker = '^' if trade.action.upper() == 'BUY' else 'v'
            size = 200  # Much larger!
            ax1.scatter([trade_snapshot_idx], [0.8 if trade.action.upper() == 'BUY' else -0.8], 
                       color=color, marker=marker, s=size, zorder=5, 
                       edgecolors='black', linewidth=1.5,
                       label=f'{trade.action} ({trade.quantity} @ {trade.price})')
        
        # Add legend with all unique trades
        handles, labels = ax1.get_legend_handles_labels()
        ax1.legend(handles[:1], labels[:1], loc='upper left', fontsize=8)  # Just position legend
        ax1.set_ylim(-1.2, 1.2)
        
        # Plot 2: P&L over time
        ax2.plot(timestamps, pnls, marker='o', linestyle='-', color='purple', linewidth=2, label='P&L', markersize=3)
        ax2.fill_between(timestamps, 0, pnls, alpha=0.3, color='purple')
        ax2.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
        ax2.set_ylabel('P&L', fontweight='bold')
        ax2.grid(True, alpha=0.3)
        ax2.legend()
        
        # Plot 3: Trade details - show every trade with price and volume at correct timeline positions
        if trades_for_product:
            trade_volumes = [t.quantity for t in trades_for_product]
            trade_prices = [t.price for t in trades_for_product]
            colors = ['green' if t.action.upper() == 'BUY' else 'red' for t in trades_for_product]
            
            # Bar chart for volume using CORRECT timeline positions
            bars = ax3.bar(trade_indices, trade_volumes, width=15, color=colors, alpha=0.6, edgecolor='black', linewidth=0.5)
            ax3.set_ylabel('Trade Volume', fontweight='bold')
            ax3.set_xlabel('Timeline Position', fontweight='bold')
            ax3.grid(True, alpha=0.3, axis='y')
            ax3.set_xlim(0, len(timestamps))  # Match position and P&L axes
            
            # Add price labels on top of bars
            for i, (bar, price) in enumerate(zip(bars, trade_prices)):
                height = bar.get_height()
                ax3.text(bar.get_x() + bar.get_width()/2., height,
                        f'{int(price)}',
                        ha='center', va='bottom', fontsize=6, rotation=0)
        
        plt.tight_layout()
        
        if output_file:
            plt.savefig(output_file, dpi=150, bbox_inches='tight')
            print(f"✓ Saved detailed chart to {output_file}")
        else:
            plt.show()
    
    def create_interactive_html(self, output_file: str = "trading_dashboard.html"):
        """Create interactive HTML dashboard using Plotly with correct trade timeline positioning."""
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
        except ImportError:
            print("plotly not installed. Install with: pip install plotly")
            return
        
        # Create subplots for position, P&L, and trades table
        fig = make_subplots(
            rows=3, cols=1,
            subplot_titles=("Position & Trades (Large Markers)", "P&L Over Time", "Trade Execution Log"),
            specs=[[{"secondary_y": True}], [{"secondary_y": False}], [{"type": "table"}]],
            row_heights=[0.45, 0.35, 0.2],
            vertical_spacing=0.08
        )
        
        # Color mapping
        buy_color = 'green'
        sell_color = 'red'
        
        # Plot data for each product and include spread traces/bands
        product_colors = {'EMERALDS': 'blue', 'TOMATOES': 'orange'}

        for product_idx, (product, snaps) in enumerate(self.snapshots.items()):
            if not snaps:
                continue

            # Create timestamp mapping for this product
            snapshots_ts = [int(s.timestamp) for s in snaps]
            ts_to_idx = {ts: i for i, ts in enumerate(snapshots_ts)}

            timestamps = [str(i) for i in range(len(snaps))]
            positions = [s.position for s in snaps]
            pnls = [s.pnl for s in snaps]

            # Compute spreads and mids
            spreads = []
            mids = []
            prices = []
            for s in snaps:
                bid = s.bid_wall if s.bid_wall is not None else None
                ask = s.ask_wall if s.ask_wall is not None else None
                mid = s.mid_price if s.mid_price is not None else None
                if mid is None and bid is not None and ask is not None:
                    mid = (bid + ask) / 2.0
                mids.append(mid if mid is not None else 0)
                if bid is not None and ask is not None:
                    spreads.append(max(0, ask - bid))
                else:
                    spreads.append(0)
                if mid is not None:
                    prices.append(mid)

            max_spread = max(spreads) if spreads else 1
            if max_spread == 0:
                max_spread = 1
            max_price = max(prices) if prices else 1
            min_price = min(prices) if prices else 0

            product_color = product_colors.get(product, 'blue')

            # Add position trace
            fig.add_trace(
                go.Scatter(
                    x=timestamps, y=positions,
                    mode='lines+markers',
                    name=f'{product} Position',
                    line=dict(color=product_color, width=2),
                    marker=dict(size=3),
                    hovertemplate=f'{product} Position: %{{y}}<extra></extra>'
                ),
                row=1, col=1
            )

            # Add P&L trace
            fig.add_trace(
                go.Scatter(
                    x=timestamps, y=pnls,
                    mode='lines+markers',
                    name=f'{product} P&L',
                    line=dict(color=product_color, width=2, dash='dash'),
                    marker=dict(size=2),
                    hovertemplate=f'{product} P&L: %{{y}}<extra></extra>'
                ),
                row=2, col=1
            )

            # Add spread as a secondary-y trace (price units)
            if any(spreads):
                fig.add_trace(
                    go.Scatter(
                        x=timestamps, y=spreads,
                        mode='lines',
                        name=f'{product} Spread',
                        line=dict(color='gray', width=2, dash='dot'),
                        hovertemplate=f'{product} Spread: %{{y}}<extra></extra>'
                    ),
                    row=1, col=1,
                    secondary_y=True
                )

                # Add a light filled band around spread for emphasis
                band_upper = [m + (s / 2.0) for m, s in zip(mids, spreads)]
                band_lower = [m - (s / 2.0) for m, s in zip(mids, spreads)]
                fig.add_trace(go.Scatter(x=timestamps, y=band_upper, fill=None, mode='lines', line=dict(color='lightgray', width=0), showlegend=False), row=1, col=1, secondary_y=False)
                fig.add_trace(go.Scatter(x=timestamps, y=band_lower, fill='tonexty', mode='lines', line=dict(color='lightgray', width=0), name=f'{product} Spread Band', opacity=0.3), row=1, col=1, secondary_y=False)

            # Add trades as LARGE scatter points at CORRECT timeline positions
            product_trades = [t for t in self.trades if t.product == product]
            if product_trades:
                for i, trade in enumerate(product_trades):
                    # Find correct position on timeline for this trade
                    try:
                        trade_ts = int(trade.timestamp)
                        if trade_ts in ts_to_idx:
                            trade_pos_idx = ts_to_idx[trade_ts]
                        else:
                            # Find nearest timestamp
                            trade_pos_idx = min(range(len(snapshots_ts)), key=lambda i: abs(snapshots_ts[i] - trade_ts))
                    except (ValueError, TypeError):
                        trade_pos_idx = 0

                    marker_color = buy_color if trade.action == 'BUY' else sell_color
                    marker_symbol = 'triangle-up' if trade.action == 'BUY' else 'triangle-down'

                    # Add large trade marker at CORRECT timeline position
                    fig.add_trace(
                        go.Scatter(
                            x=[str(trade_pos_idx)],  # Use timeline position, not trade index!
                            y=[0],  # Center on 0 for visibility
                            mode='markers',
                            marker=dict(
                                size=15,  # Large!
                                color=marker_color,
                                symbol=marker_symbol,
                                line=dict(color='black', width=2)
                            ),
                            name=f'{product} {trade.action}',
                            hovertemplate=(
                                f'<b>{product} {trade.action}</b><br>' +
                                f'Time: {trade.timestamp}<br>' +
                                f'Price: {trade.price}<br>' +
                                f'Qty: {trade.quantity}<br>' +
                                f'<extra></extra>'
                            ),
                            showlegend=(product_trades.index(trade) == 0),  # Only first in legend
                        ),
                        row=1, col=1
                    )
        
        # Add trade table at bottom
        if self.trades:
            table_trades = self.trades[:50]  # Show first 50 trades
            fig.add_trace(
                go.Table(
                    header=dict(
                        values=['<b>Time</b>', '<b>Product</b>', '<b>Action</b>', '<b>Price</b>', '<b>Qty</b>'],
                        fill_color='paleturquoise',
                        align='left',
                        font=dict(color='black')
                    ),
                    cells=dict(
                        values=[
                            [t.timestamp for t in table_trades],
                            [t.product for t in table_trades],
                            [t.action for t in table_trades],
                            [str(t.price) for t in table_trades],
                            [str(t.quantity) for t in table_trades]
                        ],
                        fill_color='lavender',
                        align='left'
                    )
                ),
                row=3, col=1
            )
        
        # Update layout
        fig.update_yaxes(title_text="Position", row=1, col=1, secondary_y=False)
        fig.update_yaxes(title_text="Spread (price units)", row=1, col=1, secondary_y=True, showgrid=False)
        fig.update_yaxes(title_text="P&L", row=2, col=1)
        fig.update_xaxes(title_text="Time Index", row=2, col=1)
        
        fig.update_layout(
            title_text=f"Trading Strategy Dashboard ({len(self.trades)} trades)",
            height=1600,
            hovermode='x unified',
            template='plotly_white',
            showlegend=True,
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1)
        )
        
        fig.write_html(output_file)
        print(f"✓ Created interactive dashboard: {output_file}")


def trade_type_to_color(action: str) -> str:
    """Convert trade action to color."""
    return 'green' if action.upper() == 'BUY' else 'red'


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python log_visualizer.py <log_file> [output_format]")
        print("Output formats: summary, timeline, chart, interactive, all")
        sys.exit(1)
    
    log_file = sys.argv[1]
    format_type = sys.argv[2] if len(sys.argv) > 2 else "all"
    
    visualizer = LogVisualizer(log_file)
    
    if format_type in ["summary", "all"]:
        summary = visualizer.generate_summary()
        print("\n=== TRADE SUMMARY ===")
        print(json.dumps(summary, indent=2))
    
    if format_type in ["timeline", "all"]:
        visualizer.export_trade_timeline()
    
    if format_type in ["chart", "all"]:
        for product in visualizer.snapshots.keys():
            output_file = f"{product.lower()}_chart.png"
            visualizer.create_matplotlib_chart(product, output_file)
    
    if format_type in ["interactive", "all"]:
        visualizer.create_interactive_html()
