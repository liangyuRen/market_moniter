"""新闻情绪分析 — 简单的关键词匹配+词频评分"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 正面关键词（利多）
POSITIVE_KEYWORDS = [
    "利好", "涨停", "大涨", "突破", "新高", "增长", "利润", "营收",
    "增持", "回购", "分红", "政策支持", "降准", "降息", "中标",
    "订单", "合作", "签约", "获批", "上市", "研发成功", "量产",
    "触底反弹", "逆势上涨", "资金流入", "机构买入", "北向资金",
    "业绩预增", "扭亏", "利好推动",
]

# 负面关键词（利空）
NEGATIVE_KEYWORDS = [
    "利空", "跌停", "大跌", "暴跌", "暴雷", "崩盘", "亏损", "下滑",
    "减持", "套现", "质押", "立案", "调查", "处罚", "制裁",
    "违约", "破产", "重组失败", "退市", "暂停上市", "停牌",
    "资金流出", "机构卖出", "北向流出", "抛售", "踩踏",
    "业绩预亏", "预降", "同比下降",
]

# 重要程度关键词
URGENT_KEYWORDS = [
    "突发", "紧急", "刚刚", "快讯", "公告", "辟谣", "澄清",
    "重大", "停牌", "暂停",
]


def analyze_title_sentiment(title: str) -> dict:
    """分析单条新闻标题的情绪和重要性"""
    title_lower = title

    pos_count = sum(1 for kw in POSITIVE_KEYWORDS if kw in title_lower)
    neg_count = sum(1 for kw in NEGATIVE_KEYWORDS if kw in title_lower)
    urgent_hits = [kw for kw in URGENT_KEYWORDS if kw in title_lower]

    # 情绪得分: -100到+100
    total = pos_count + neg_count
    if total == 0:
        score = 0
        direction = "neutral"
    else:
        score = int((pos_count - neg_count) / total * 100)
        if score > 20:
            direction = "positive"
        elif score < -20:
            direction = "negative"
        else:
            direction = "neutral"

    return {
        "sentiment": direction,
        "score": score,
        "pos_hits": pos_count,
        "neg_hits": neg_count,
        "urgent_keywords": urgent_hits,
        "is_important": len(urgent_hits) > 0 or abs(score) >= 50,
    }


def filter_important_news(news_list: list[dict], watchlist_stocks: list = None) -> list[dict]:
    """过滤重要新闻：情绪影响大、与自选股相关、紧急新闻"""
    important = []
    watch_names = set()
    watch_codes = set()

    if watchlist_stocks:
        for s in watchlist_stocks:
            watch_names.add(s.get("name", ""))
            watch_codes.add(s.get("code", ""))

    for news in news_list:
        title = news.get("title", "")
        sentiment = analyze_title_sentiment(title)

        # 判断是否与自选股相关
        related = False
        for name in watch_names:
            if name in title:
                related = True
                break
        for code in watch_codes:
            if code in title:
                related = True
                break

        # 重要新闻判定
        if sentiment["is_important"] or related:
            news["_sentiment"] = sentiment
            news["_related"] = related
            important.append(news)

    # 排序：自选股相关 + 紧急 优先
    important.sort(key=lambda n: (
        n.get("_related", False),
        len(n.get("_sentiment", {}).get("urgent_keywords", [])),
        abs(n.get("_sentiment", {}).get("score", 0)),
    ), reverse=True)

    return important


def generate_news_brief(news_list: list[dict], max_items: int = 10) -> str:
    """生成新闻简报文本"""
    important = filter_important_news(news_list)
    if not important:
        return "今日无重要新闻。"

    lines = [f"📰 重要新闻 ({len(important)}条)\n"]
    for i, news in enumerate(important[:max_items], 1):
        sent = news.get("_sentiment", {})
        emoji = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(
            sent.get("sentiment", "neutral"), "⚪")
        title = news.get("title", "")[:120]
        if news.get("_related"):
            emoji = "⭐"
        if sent.get("urgent_keywords"):
            emoji = "🚨"
        lines.append(f"{emoji}{i}. {title}")

    return "\n".join(lines)
