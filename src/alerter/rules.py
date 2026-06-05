"""规则引擎 — 加载和评估告警规则"""
import logging
from typing import Optional

from src.config_loader import get_enabled_rules
from src.analyzer.anomaly import (
    detect_price_change,
    detect_limit_up_down,
    detect_volume_surge,
    detect_volume_surge_drop,
    detect_high_drop,
    detect_fund_flow_anomaly,
    detect_market_anomaly,
)
from src.analyzer.sentiment import analyze_title_sentiment, filter_important_news
from src.storage.state import state

logger = logging.getLogger(__name__)


def evaluate_realtime_rules(watchlist_quotes: dict, fund_flows: dict = None,
                             market_overview: dict = None) -> list[dict]:
    """评估所有实时告警规则，返回触发告警列表"""
    rules = get_enabled_rules()
    realtime_rules = [r for r in rules if r.get("type") == "realtime"]
    alerts = []
    cooldown = 600  # 默认10分钟冷却

    for rule in realtime_rules:
        rule_id = rule["id"]
        params = rule.get("params", {})

        if rule_id == "price_surge":
            for code, quote in watchlist_quotes.items():
                key = f"{code}:{rule_id}"
                if state.is_on_cooldown(key, cooldown):
                    continue
                alert = detect_price_change(code, quote, params.get("change_pct", 5.0))
                if alert and alert["category"] == "opportunity":
                    alert["rule_id"] = rule_id
                    alerts.append(alert)
                    state.set_cooldown(key)

        elif rule_id == "price_drop":
            for code, quote in watchlist_quotes.items():
                key = f"{code}:{rule_id}"
                if state.is_on_cooldown(key, cooldown):
                    continue
                alert = detect_price_change(code, quote, abs(params.get("change_pct", 5.0)))
                if alert and alert["category"] == "risk":
                    alert["rule_id"] = rule_id
                    alerts.append(alert)
                    state.set_cooldown(key)

        elif rule_id in ("limit_up", "limit_down"):
            for code, quote in watchlist_quotes.items():
                key = f"{code}:{rule_id}"
                if state.is_on_cooldown(key, cooldown):
                    continue
                alert = detect_limit_up_down(code, quote, params.get("change_pct", 9.8))
                if alert:
                    alert["rule_id"] = rule_id
                    alerts.append(alert)
                    state.set_cooldown(key)

        elif rule_id == "volume_surge":
            for code, quote in watchlist_quotes.items():
                key = f"{code}:{rule_id}"
                if state.is_on_cooldown(key, cooldown):
                    continue
                alert = detect_volume_surge(
                    code, quote,
                    min_vol_ratio=params.get("volume_ratio", 2.0),
                    min_change_pct=params.get("min_change_pct", 0),
                )
                if alert:
                    alerts.append(alert)
                    state.set_cooldown(key)

        elif rule_id == "volume_surge_drop":
            for code, quote in watchlist_quotes.items():
                key = f"{code}:{rule_id}"
                if state.is_on_cooldown(key, cooldown):
                    continue
                alert = detect_volume_surge_drop(
                    code, quote,
                    min_vol_ratio=params.get("volume_ratio", 1.5),
                    max_change_pct=params.get("max_change_pct", -2.0),
                )
                if alert:
                    alerts.append(alert)
                    state.set_cooldown(key)

        elif rule_id == "high_drop":
            for code, quote in watchlist_quotes.items():
                key = f"{code}:{rule_id}"
                if state.is_on_cooldown(key, cooldown):
                    continue
                alert = detect_high_drop(
                    code, quote,
                    high_rise=params.get("high_rise", 5.0),
                    drop_from_high=params.get("drop_from_high", 3.0),
                )
                if alert:
                    alerts.append(alert)
                    state.set_cooldown(key)

        elif rule_id == "main_inflow" and fund_flows:
            for code, quote in watchlist_quotes.items():
                key = f"{code}:{rule_id}"
                if state.is_on_cooldown(key, cooldown * 2):
                    continue
                flow = fund_flows.get(code, {})
                alert = detect_fund_flow_anomaly(
                    code, quote, flow,
                    inflow_threshold=params.get("inflow_amount", 1e8),
                    outflow_threshold=0,  # 只看流入
                )
                if alert and alert["category"] == "opportunity":
                    alert["rule_id"] = rule_id
                    alerts.append(alert)
                    state.set_cooldown(key)

        elif rule_id == "main_outflow" and fund_flows:
            for code, quote in watchlist_quotes.items():
                key = f"{code}:{rule_id}"
                if state.is_on_cooldown(key, cooldown * 2):
                    continue
                flow = fund_flows.get(code, {})
                alert = detect_fund_flow_anomaly(
                    code, quote, flow,
                    inflow_threshold=0,
                    outflow_threshold=params.get("outflow_amount", 1e8),
                )
                if alert and alert["category"] == "risk":
                    alert["rule_id"] = rule_id
                    alerts.append(alert)
                    state.set_cooldown(key)

    # 市场整体异动
    if market_overview:
        market_alert = detect_market_anomaly(market_overview)
        if market_alert:
            key = "MARKET:market_extreme"
            if not state.is_on_cooldown(key, 1800):  # 30分钟冷却
                alerts.append(market_alert)
                state.set_cooldown(key)

    return alerts


def evaluate_news_alerts(news_list: list[dict], watchlist_stocks: list = None) -> list[dict]:
    """评估新闻相关告警"""
    rules = get_enabled_rules()
    news_rules = [r for r in rules if r.get("type") == "news" and r.get("enabled")]

    if not news_rules:
        return []

    important = filter_important_news(news_list, watchlist_stocks)
    alerts = []

    for rule in news_rules:
        params = rule.get("params", {})
        keywords = params.get("keywords", [])
        for news in important:
            title = news.get("title", "")
            matched = [kw for kw in keywords if kw in title]
            if not matched:
                continue

            sent = news.get("_sentiment", {})
            is_risk = rule["category"] == "risk"
            alert = {
                "alert_at": news.get("pub_time", ""),
                "alert_type": "news",
                "category": rule["category"],
                "stock_code": "NEWS",
                "stock_name": "新闻",
                "rule_id": rule["id"],
                "title": f"{'🔴' if is_risk else '🟢'} {rule['name']}: {title[:80]}",
                "detail": f"匹配关键词: {', '.join(matched)}\n"
                          f"情绪: {sent.get('sentiment', 'unknown')} (得分: {sent.get('score', 0)})\n"
                          f"内容: {news.get('title', '')[:200]}\n"
                          f"来源: {news.get('source', '')}",
                "notified": 0,
            }
            alerts.append(alert)

    return alerts
