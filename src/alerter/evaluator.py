"""告警评估 — 去重合并、优先级排序、频率控制"""
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from src.config_loader import get_alert_rules
from src.storage.database import check_alert_cooldown, save_alert
from src.storage.state import state

logger = logging.getLogger(__name__)

# 同一股票/新闻，合并窗口（秒）
MERGE_WINDOW = 60


def deduplicate_alerts(alerts: list[dict]) -> list[dict]:
    """去重：合并同一股票相近时间内同类型告警"""
    if len(alerts) <= 1:
        return alerts

    groups = defaultdict(list)
    for alert in alerts:
        key = f"{alert.get('stock_code', '')}:{alert.get('rule_id', '')}"
        groups[key].append(alert)

    merged = []
    for key, group in groups.items():
        if len(group) == 1:
            merged.append(group[0])
        else:
            # 合并多条告警，保留第一条标题和详情合并
            base = group[0]
            detail_parts = [base["detail"]]
            for extra in group[1:]:
                detail_parts.append(f"\n---\n{extra['detail']}")
            base["detail"] = "\n".join(detail_parts)
            base["title"] = f"{base['title']} (+{len(group)-1})"
            merged.append(base)

    return merged


def priority_sort(alerts: list[dict]) -> list[dict]:
    """按优先级排序：风险 > 机会 > 信息，同类别按规则priority排序"""
    rules_map = {r["id"]: r for r in get_alert_rules()}

    category_rank = {"risk": 0, "opportunity": 1, "info": 2}

    def sort_key(alert):
        cat = alert.get("category", "info")
        rule = rules_map.get(alert.get("rule_id", ""), {})
        priority = rule.get("priority", 5)
        cat_r = category_rank.get(cat, 3)
        return (cat_r, -priority)

    return sorted(alerts, key=sort_key)


def rate_limit(alerts: list[dict], max_per_batch: int = 5) -> list[dict]:
    """频率控制：单批次最多推送N条告警"""
    if len(alerts) <= max_per_batch:
        return alerts
    logger.warning(f"告警超过限制 {len(alerts)} > {max_per_batch}，截断")
    return alerts[:max_per_batch]


def process_alerts(alerts: list[dict]) -> list[dict]:
    """完整的告警处理流水线"""
    if not alerts:
        return []

    # 1. 数据库冷却检查（持久化去重）
    db_filtered = []
    for alert in alerts:
        stock_code = alert.get("stock_code", "")
        rule_id = alert.get("rule_id", "")
        in_cooldown = check_alert_cooldown(stock_code, rule_id, 600)
        if not in_cooldown:
            db_filtered.append(alert)

    # 2. 内存去重合并
    deduped = deduplicate_alerts(db_filtered)

    # 3. 优先级排序
    sorted_alerts = priority_sort(deduped)

    # 4. 频率限制
    limited = rate_limit(sorted_alerts)

    # 5. 保存到数据库 + 更新状态
    for alert in limited:
        try:
            save_alert(alert)
            state.increment_alerts()
        except Exception as e:
            logger.error(f"保存告警失败: {e}")

    logger.info(f"告警处理: 原始{alerts} → DB过滤{db_filtered} → 去重{deduped} → 推送{len(limited)}条")
    return limited


def generate_daily_summary(watchlist_quotes: dict, index_quotes: dict,
                            news_list: list, market_overview: dict) -> dict:
    """生成每日收盘总结数据"""
    from src.analyzer.sentiment import filter_important_news

    # 自选股表现统计
    up_stocks = []
    down_stocks = []
    limit_up = []
    limit_down = []
    big_changers = []

    for code, q in watchlist_quotes.items():
        chg = q.get("change_pct", 0)
        entry = {
            "code": code,
            "name": q.get("name", ""),
            "price": q.get("price", 0),
            "change_pct": chg,
        }
        if chg >= 9.8:
            limit_up.append(entry)
        elif chg <= -9.8:
            limit_down.append(entry)
        elif chg > 0:
            up_stocks.append(entry)
        else:
            down_stocks.append(entry)

        if abs(chg) >= 5:
            big_changers.append(entry)

    # 新闻摘要
    important_news = filter_important_news(news_list)

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "indices": index_quotes,
        "market_overview": market_overview,
        "summary": {
            "total": len(watchlist_quotes),
            "up": len(up_stocks) + len(limit_up),
            "down": len(down_stocks) + len(limit_down),
            "limit_up": limit_up,
            "limit_down": limit_down,
            "big_changers": big_changers,
        },
        "top_gainers": sorted(down_stocks + up_stocks + limit_up,
                              key=lambda x: x["change_pct"], reverse=True)[:5],
        "top_losers": sorted(down_stocks + up_stocks + limit_down,
                             key=lambda x: x["change_pct"])[:5],
        "important_news": [{"title": n.get("title", "")[:100],
                            "source": n.get("source", ""),
                            "sentiment": n.get("_sentiment", {}).get("sentiment", "neutral")}
                           for n in important_news[:15]],
    }
