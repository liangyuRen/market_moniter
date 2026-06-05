"""异动检测 — 涨跌停/量比异常/冲高回落/资金异动"""
import logging
from datetime import datetime
from typing import Optional

from src.storage.state import state

logger = logging.getLogger(__name__)


def detect_price_change(code: str, quote: dict, threshold: float) -> Optional[dict]:
    """检测涨跌幅异动"""
    change_pct = quote.get("change_pct", 0)
    threshold = abs(threshold)  # 防御：确保阈值为正
    if abs(change_pct) >= threshold:
        return {
            "alert_at": datetime.now().isoformat(),
            "alert_type": "price_change",
            "category": "opportunity" if change_pct > 0 else "risk",
            "stock_code": code,
            "stock_name": quote.get("name", ""),
            "rule_id": "price_surge" if change_pct > 0 else "price_drop",
            "title": f"{'📈' if change_pct > 0 else '📉'} {quote.get('name', code)} {'大涨' if change_pct > 0 else '大跌'} {change_pct:+.2f}%",
            "detail": f"当前价格: ¥{quote.get('price', 0):.2f}\n涨跌幅: {change_pct:+.2f}%\n成交额: {quote.get('amount', 0)/1e8:.2f}亿\n换手率: {quote.get('turnover', 0):.2f}%",
            "notified": 0,
        }
    return None


def detect_limit_up_down(code: str, quote: dict, threshold: float = 9.8) -> Optional[dict]:
    """检测涨跌停"""
    threshold = abs(threshold)  # 防御：确保阈值为正
    change_pct = quote.get("change_pct", 0)
    if abs(change_pct) >= threshold:
        is_up = change_pct > 0
        return {
            "alert_at": datetime.now().isoformat(),
            "alert_type": "limit_up_down",
            "category": "info" if is_up else "risk",
            "stock_code": code,
            "stock_name": quote.get("name", ""),
            "rule_id": "limit_up" if is_up else "limit_down",
            "title": f"{'🔥' if is_up else '💥'} {quote.get('name', code)} {'涨停!' if is_up else '跌停!'}",
            "detail": f"当前价格: ¥{quote.get('price', 0):.2f}\n涨跌幅: {change_pct:+.2f}%\n成交额: {quote.get('amount', 0)/1e8:.2f}亿",
            "notified": 0,
        }
    return None


def detect_volume_surge(code: str, quote: dict, min_vol_ratio: float = 2.0,
                        min_change_pct: float = 0) -> Optional[dict]:
    """检测放量上涨（机会信号）"""
    vol_ratio = quote.get("volume_ratio", 1)
    change_pct = quote.get("change_pct", 0)
    if vol_ratio >= min_vol_ratio and change_pct >= min_change_pct:
        return {
            "alert_at": datetime.now().isoformat(),
            "alert_type": "volume_surge",
            "category": "opportunity",
            "stock_code": code,
            "stock_name": quote.get("name", ""),
            "rule_id": "volume_surge",
            "title": f"📊 {quote.get('name', code)} 放量上涨",
            "detail": f"当前价格: ¥{quote.get('price', 0):.2f}\n涨跌幅: {change_pct:+.2f}%\n量比: {vol_ratio:.2f}\n成交额: {quote.get('amount', 0)/1e8:.2f}亿",
            "notified": 0,
        }
    return None


def detect_volume_surge_drop(code: str, quote: dict, min_vol_ratio: float = 1.5,
                              max_change_pct: float = -2.0) -> Optional[dict]:
    """检测放量下跌（风险信号）"""
    vol_ratio = quote.get("volume_ratio", 1)
    change_pct = quote.get("change_pct", 0)
    if vol_ratio >= min_vol_ratio and change_pct <= max_change_pct:
        return {
            "alert_at": datetime.now().isoformat(),
            "alert_type": "volume_drop",
            "category": "risk",
            "stock_code": code,
            "stock_name": quote.get("name", ""),
            "rule_id": "volume_surge_drop",
            "title": f"⚠️ {quote.get('name', code)} 放量下跌",
            "detail": f"当前价格: ¥{quote.get('price', 0):.2f}\n涨跌幅: {change_pct:+.2f}%\n量比: {vol_ratio:.2f}\n成交额: {quote.get('amount', 0)/1e8:.2f}亿\n⚠️ 放量下跌，注意风险！",
            "notified": 0,
        }
    return None


def detect_high_drop(code: str, quote: dict, high_rise: float = 5.0,
                     drop_from_high: float = 3.0) -> Optional[dict]:
    """检测冲高回落"""
    extreme = state.intraday_extremes.get(code)
    if not extreme:
        return None

    open_price = extreme.get("open", 0)
    intraday_high = extreme.get("high", 0)
    current_price = quote.get("price", 0)

    if open_price <= 0 or intraday_high <= 0 or current_price <= 0:
        return None

    rise_pct = (intraday_high - open_price) / open_price * 100
    drop_pct = (intraday_high - current_price) / intraday_high * 100

    if rise_pct >= high_rise and drop_pct >= drop_from_high:
        return {
            "alert_at": datetime.now().isoformat(),
            "alert_type": "high_drop",
            "category": "risk",
            "stock_code": code,
            "stock_name": quote.get("name", ""),
            "rule_id": "high_drop",
            "title": f"🔴 {quote.get('name', code)} 冲高回落",
            "detail": f"高点: ¥{intraday_high:.2f} (涨{rise_pct:.2f}%)\n"
                      f"现价: ¥{current_price:.2f}\n"
                      f"回落: -{drop_pct:.2f}%\n"
                      f"当前涨跌幅: {quote.get('change_pct', 0):+.2f}%",
            "notified": 0,
        }
    return None


def detect_fund_flow_anomaly(code: str, quote: dict, fund_flow: dict,
                              inflow_threshold: float = 1e8,
                              outflow_threshold: float = 1e8) -> Optional[dict]:
    """检测资金流向异常"""
    if not fund_flow:
        return None

    main_inflow = fund_flow.get("main_net_inflow", 0)

    if main_inflow >= inflow_threshold:
        return {
            "alert_at": datetime.now().isoformat(),
            "alert_type": "fund_inflow",
            "category": "opportunity",
            "stock_code": code,
            "stock_name": quote.get("name", ""),
            "rule_id": "main_inflow",
            "title": f"💰 {quote.get('name', code)} 主力资金大幅流入",
            "detail": f"主力净流入: {main_inflow/1e8:+.2f}亿\n"
                      f"主力净占比: {fund_flow.get('main_net_inflow_pct', 0):+.2f}%\n"
                      f"当前涨跌幅: {quote.get('change_pct', 0):+.2f}%",
            "notified": 0,
        }
    elif main_inflow <= -outflow_threshold:
        return {
            "alert_at": datetime.now().isoformat(),
            "alert_type": "fund_outflow",
            "category": "risk",
            "stock_code": code,
            "stock_name": quote.get("name", ""),
            "rule_id": "main_outflow",
            "title": f"💸 {quote.get('name', code)} 主力资金大幅流出",
            "detail": f"主力净流出: {main_inflow/1e8:+.2f}亿\n"
                      f"主力净占比: {fund_flow.get('main_net_inflow_pct', 0):+.2f}%\n"
                      f"当前涨跌幅: {quote.get('change_pct', 0):+.2f}%",
            "notified": 0,
        }
    return None


def detect_market_anomaly(market_overview: dict) -> Optional[dict]:
    """检测市场整体异动（极端涨跌比、暴跌普涨等）"""
    up = market_overview.get("up_count", 0)
    down = market_overview.get("down_count", 0)
    total = up + down + market_overview.get("flat_count", 0)
    if total == 0:
        return None

    up_ratio = up / total

    # 极端普涨（>85%上涨）
    if up_ratio > 0.85:
        return {
            "alert_at": datetime.now().isoformat(),
            "alert_type": "market_anomaly",
            "category": "opportunity",
            "stock_code": "MARKET",
            "stock_name": "全市场",
            "rule_id": "market_extreme_up",
            "title": f"🌟 市场极端普涨 {up_ratio*100:.0f}%",
            "detail": f"上涨: {up} | 下跌: {down}\n涨停: {market_overview.get('limit_up_count', 0)}\n总成交额: {market_overview.get('total_amount_billion', 0)}亿",
            "notified": 0,
        }

    # 极端普跌（>85%下跌）
    if up_ratio < 0.15:
        return {
            "alert_at": datetime.now().isoformat(),
            "alert_type": "market_anomaly",
            "category": "risk",
            "stock_code": "MARKET",
            "stock_name": "全市场",
            "rule_id": "market_extreme_down",
            "title": f"🌪️ 市场极端普跌 {(1-up_ratio)*100:.0f}%",
            "detail": f"上涨: {up} | 下跌: {down}\n跌停: {market_overview.get('limit_down_count', 0)}\n总成交额: {market_overview.get('total_amount_billion', 0)}亿",
            "notified": 0,
        }

    return None
