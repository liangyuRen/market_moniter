"""历史数据回填 — 将自选股历史K线导入SQLite"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from datetime import datetime

from src.config_loader import get_watchlist
from src.collector.market_data import fetch_stock_history
from src.storage.database import init_db, save_batch_snapshots


def backfill_history(days: int = 250):
    """回填自选股历史行情到数据库"""
    init_db()
    watchlist = get_watchlist()
    print(f"开始回填 {len(watchlist)} 只自选股最近 {days} 天历史数据...")

    total = 0
    for item in watchlist:
        code = item["code"]
        name = item["name"]
        market = item.get("market", "SH")
        print(f"  获取 {name}({code})...", end=" ")
        try:
            df = fetch_stock_history(code, market, days=days)
            if df.empty:
                print("无数据")
                continue
            rows = []
            for _, row in df.iterrows():
                rows.append({
                    "code": code,
                    "name": name,
                    "price": float(row.get("收盘", 0) or 0),
                    "change_pct": float(row.get("涨跌幅", 0) or 0),
                    "volume": float(row.get("成交量", 0) or 0),
                    "amount": float(row.get("成交额", 0) or 0),
                    "turnover": float(row.get("换手率", 0) or 0),
                    "high": float(row.get("最高", 0) or 0),
                    "low": float(row.get("最低", 0) or 0),
                    "open": float(row.get("开盘", 0) or 0),
                    "pre_close": float(row.get("昨收", row.get("前收盘", 0)) or 0),
                    "volume_ratio": 1.0,
                    "fetched_at": str(row.get("日期", datetime.now().date())),
                })
            save_batch_snapshots(rows)
            total += len(rows)
            print(f"{len(rows)} 条")
        except Exception as e:
            print(f"失败: {e}")

    print(f"\n回填完成! 共写入 {total} 条记录。")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="历史数据回填")
    parser.add_argument("--days", type=int, default=250, help="回填天数")
    args = parser.parse_args()
    backfill_history(args.days)
