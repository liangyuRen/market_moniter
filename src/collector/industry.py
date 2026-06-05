"""行业板块数据采集"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def fetch_industry_boards() -> list[dict]:
    """获取所有行业板块行情（涨幅排序）"""
    import akshare as ak
    try:
        df = ak.stock_board_industry_name_em()
        if df is None or df.empty:
            return []
        boards = []
        for _, row in df.head(30).iterrows():
            boards.append({
                "name": str(row.get("板块名称", "")),
                "code": str(row.get("板块代码", "")),
                "price": float(row.get("最新价", 0) or 0),
                "change_pct": float(row.get("涨跌幅", 0) or 0),
                "volume": float(row.get("成交量", 0) or 0),
                "amount": float(row.get("成交额", 0) or 0),
                "up_count": int(row.get("上涨家数", 0) or 0),
                "down_count": int(row.get("下跌家数", 0) or 0),
                "lead_stock": str(row.get("领涨个股", "")),
                "lead_stock_change": float(row.get("领涨个股-涨跌幅", 0) or 0),
            })
        return boards
    except Exception as e:
        logger.error(f"获取行业板块失败: {e}")
        return []


def fetch_concept_boards() -> list[dict]:
    """获取所有概念板块行情（涨幅排序）"""
    import akshare as ak
    try:
        df = ak.stock_board_concept_name_em()
        if df is None or df.empty:
            return []
        boards = []
        for _, row in df.head(30).iterrows():
            boards.append({
                "name": str(row.get("板块名称", "")),
                "code": str(row.get("板块代码", "")),
                "price": float(row.get("最新价", 0) or 0),
                "change_pct": float(row.get("涨跌幅", 0) or 0),
                "volume": float(row.get("成交量", 0) or 0),
                "amount": float(row.get("成交额", 0) or 0),
                "lead_stock": str(row.get("领涨个股", "")),
            })
        return boards
    except Exception as e:
        logger.error(f"获取概念板块失败: {e}")
        return []


def fetch_top_boards(limit: int = 5) -> tuple[list[dict], list[dict]]:
    """获取涨幅前N和跌幅前N的行业板块"""
    boards = fetch_industry_boards()
    if not boards:
        return [], []

    sorted_boards = sorted(boards, key=lambda x: x["change_pct"], reverse=True)
    top_up = sorted_boards[:limit]
    top_down = sorted_boards[-limit:]
    top_down.reverse()
    return top_up, top_down


def fetch_sector_anomaly() -> list[dict]:
    """发现行业板块异动（涨/跌幅超过阈值）"""
    boards = fetch_industry_boards()
    concepts = fetch_concept_boards()

    anomalies = []
    threshold = 2.0  # 涨跌幅超过2%

    all_boards = boards + concepts
    for b in all_boards:
        if abs(b["change_pct"]) >= threshold:
            anomalies.append({
                "detected_at": datetime.now().isoformat(),
                "board_name": b["name"],
                "change_pct": b["change_pct"],
                "lead_stock": b.get("lead_stock", ""),
                "direction": "up" if b["change_pct"] > 0 else "down",
                "type": "industry" if "板块代码" in b else "concept",
            })

    # 按涨跌幅绝对值排序
    anomalies.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
    return anomalies[:10]
