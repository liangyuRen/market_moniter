"""
新闻情绪分析 — 关键词匹配 + 权重评分 + 影响范围评估
"""
import logging
from collections import Counter

logger = logging.getLogger(__name__)

# 正面关键词（利多）+ 权重
POSITIVE_KW = {
    "利好": 5, "涨停": 3, "大涨": 3, "突破": 4, "新高": 4, "增长": 2,
    "利润": 2, "营收": 2, "增持": 4, "回购": 4, "分红": 3, "中标": 3,
    "订单": 3, "合作": 3, "签约": 3, "获批": 4, "上市": 2, "量产": 3,
    "政策支持": 5, "降准": 5, "降息": 5, "触底反弹": 4, "逆势上涨": 4,
    "资金流入": 3, "机构买入": 3, "北向资金": 3, "业绩预增": 5, "扭亏": 4,
    "利好推动": 4, "放量上攻": 4, "主力加仓": 4, "底部放量": 4, "超跌反弹": 3,
    "技术突破": 4, "研发成功": 4, "大单买入": 3, "抢筹": 3, "行情启动": 3,
    "政策红利": 4, "行业景气": 3, "供需改善": 3, "价格上调": 3, "毛利率提升": 3,
    "新基建": 3, "国产替代": 4, "自主可控": 4, "人工智能": 3, "数字经济": 3,
}

NEGATIVE_KW = {
    "利空": 5, "跌停": 4, "大跌": 3, "暴跌": 5, "暴雷": 5, "崩盘": 5,
    "亏损": 3, "下滑": 2, "减持": 4, "套现": 4, "质押": 3, "立案": 5,
    "调查": 5, "处罚": 4, "制裁": 5, "违约": 5, "破产": 5, "重组失败": 4,
    "退市": 5, "暂停上市": 5, "停牌": 3, "资金流出": 3, "机构卖出": 3,
    "北向流出": 3, "抛售": 4, "踩踏": 4, "业绩预亏": 5, "预降": 3,
    "同比下降": 2, "暴仓": 5, "闪崩": 5, "断崖": 5, "踩雷": 5,
    "债务违约": 5, "信用危机": 5, "资金链断裂": 5, "实控人": 3,
    "商誉减值": 4, "计提": 3, "毛利率下降": 3, "需求疲软": 3, "产能过剩": 2,
    "贸易摩擦": 4, "加征关税": 5, "地缘政治": 3, "经济衰退": 4, "通胀": 2,
}

URGENT_KW = {
    "突发": 5, "紧急": 4, "刚刚": 3, "快讯": 3, "公告": 2,
    "辟谣": 4, "澄清": 3, "重大": 4, "停牌": 5, "暂停": 3,
    "最新": 2, "此消息": 3,
}

SECTOR_KW = {
    "新能源": ["新能源", "光伏", "风电", "锂电", "储能", "宁德", "比亚迪", "隆基", "阳光电源"],
    "半导体": ["半导体", "芯片", "集成电路", "晶圆", "光刻", "中芯", "华为", "海思"],
    "消费": ["消费", "白酒", "食品", "饮料", "茅台", "五粮液", "美的", "格力"],
    "医药": ["医药", "医疗", "生物", "疫苗", "创新药", "CRO", "药明", "恒瑞"],
    "金融": ["银行", "券商", "保险", "金融", "招商银行", "中国平安", "东方财富"],
    "汽车": ["汽车", "新能源车", "电动车", "智能驾驶", "特斯拉", "蔚来", "理想"],
    "AI": ["AI", "人工智能", "GPT", "大模型", "算力", "英伟达", "百度文心"],
    "房地产": ["房地产", "楼市", "房价", "地产", "万科", "保利", "碧桂园"],
}


def analyze_title_sentiment(title: str) -> dict:
    """分析单条新闻标题的情绪、紧急程度和影响行业"""
    pos_score = 0
    neg_score = 0
    pos_hits = []
    neg_hits = []
    urgent_hits = []

    for kw, weight in POSITIVE_KW.items():
        if kw in title:
            pos_score += weight
            pos_hits.append(kw)
    for kw, weight in NEGATIVE_KW.items():
        if kw in title:
            neg_score += weight
            neg_hits.append(kw)
    for kw, weight in URGENT_KW.items():
        if kw in title:
            urgent_hits.append(kw)

    total = pos_score + neg_score
    if total == 0:
        score = 0
        direction = "neutral"
    else:
        score = int((pos_score - neg_score) / total * 100)
        if score > 15:
            direction = "positive"
        elif score < -15:
            direction = "negative"
        else:
            direction = "neutral"

    # 影响行业
    sectors_affected = []
    for sector, kws in SECTOR_KW.items():
        if any(kw in title for kw in kws):
            sectors_affected.append(sector)

    return {
        "sentiment": direction,
        "score": score,
        "pos_hits": pos_hits,
        "neg_hits": neg_hits,
        "pos_score": pos_score,
        "neg_score": neg_score,
        "urgent_keywords": urgent_hits,
        "is_urgent": len(urgent_hits) > 0,
        "is_important": len(urgent_hits) > 0 or abs(score) >= 40 or len(sectors_affected) > 0,
        "sectors_affected": sectors_affected,
    }


def filter_important_news(news_list: list[dict], watchlist_stocks: list = None) -> list[dict]:
    """过滤重要新闻：影响自选股、高情绪得分、紧急新闻"""
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
        related = any(name in title for name in watch_names) or any(code in title for code in watch_codes)
        if sentiment["is_important"] or related:
            news["_sentiment"] = sentiment
            news["_related"] = related
            important.append(news)

    important.sort(key=lambda n: (
        n.get("_related", False),
        n.get("_sentiment", {}).get("is_urgent", False),
        abs(n.get("_sentiment", {}).get("score", 0)),
    ), reverse=True)
    return important


def market_sentiment_summary(news_list: list[dict]) -> dict:
    """从新闻列表计算整体市场情绪摘要"""
    if not news_list:
        return {"sentiment": "neutral", "score": 0, "positive_count": 0, "negative_count": 0}
    sentiments = [analyze_title_sentiment(n.get("title", "")) for n in news_list]
    pos_count = sum(1 for s in sentiments if s["sentiment"] == "positive")
    neg_count = sum(1 for s in sentiments if s["sentiment"] == "negative")
    avg_score = sum(s["score"] for s in sentiments) / len(sentiments) if sentiments else 0
    return {
        "sentiment": "positive" if avg_score > 10 else "negative" if avg_score < -10 else "neutral",
        "score": round(avg_score, 2),
        "positive_count": pos_count,
        "negative_count": neg_count,
        "total": len(sentiments),
    }


def generate_news_brief(news_list: list[dict], max_items: int = 15) -> str:
    """生成新闻简报文本"""
    important = filter_important_news(news_list)
    if not important:
        return "今日无重要新闻。"

    lines = [f"重要新闻 ({len(important)}条)\n"]
    for i, news in enumerate(important[:max_items], 1):
        sent = news.get("_sentiment", {})
        emoji = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(
            sent.get("sentiment", "neutral"), "⚪")
        title = news.get("title", "")[:120]
        if news.get("_related"):
            emoji = "⭐"
        if sent.get("is_urgent"):
            emoji = "🚨"
        sectors = sent.get("sectors_affected", [])
        sector_tag = f" [{', '.join(sectors[:2])}]" if sectors else ""
        lines.append(f"{emoji}{i}. {title}{sector_tag}")
    return "\n".join(lines)
