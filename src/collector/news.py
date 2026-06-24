"""新闻采集 — 国内（财联社/东方财富）+ 国际（RSS）"""
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


def _hash_title(source: str, title: str) -> str:
    return hashlib.md5(f"{source}:{title}".encode()).hexdigest()[:16]


def fetch_cls_telegraph() -> list[dict]:
    """财联社电报（快讯）"""
    import akshare as ak
    try:
        # akshare不同版本函数名不同
        df = None
        for func_name in ["stock_telegraph_cls", "stock_info_cls_telegraph"]:
            try:
                fn = getattr(ak, func_name, None)
                if fn:
                    df = fn()
                    break
            except Exception:
                continue
        if df is None or df.empty:
            return []
        news_list = []
        for _, row in df.head(30).iterrows():
            title = str(row.get("title", row.get("content", "")))
            content = str(row.get("content", ""))
            ctime = str(row.get("ctime", ""))
            now = datetime.now()
            news_list.append({
                "source": "cls_telegraph",
                "title": title[:200],
                "content": content[:500],
                "url": "",
                "pub_time": ctime,
                "fetched_at": now.isoformat(),
            })
        return news_list
    except Exception as e:
        logger.error(f"获取财联社电报失败: {e}")
        return []


def fetch_eastmoney_news() -> list[dict]:
    """东方财富全球要闻"""
    import akshare as ak
    try:
        df = ak.stock_info_global_em()
        if df is None or df.empty:
            return []
        news_list = []
        for _, row in df.head(30).iterrows():
            title = str(row.get("标题", ""))
            news_list.append({
                "source": "eastmoney",
                "title": title[:200],
                "content": str(row.get("内容", ""))[:500],
                "url": str(row.get("链接", "")),
                "pub_time": str(row.get("发布时间", "")),
                "fetched_at": datetime.now().isoformat(),
            })
        return news_list
    except Exception as e:
        logger.error(f"获取东方财富新闻失败: {e}")
        return []


def fetch_sina_global_news() -> list[dict]:
    """新浪财经国际新闻"""
    import akshare as ak
    try:
        df = ak.stock_info_global_sina()
        if df is None or df.empty:
            return []
        news_list = []
        for _, row in df.head(20).iterrows():
            news_list.append({
                "source": "sina_global",
                "title": str(row.get("title", ""))[:200],
                "content": str(row.get("content", ""))[:500],
                "url": str(row.get("url", "")),
                "pub_time": str(row.get("pub_time", "")),
                "fetched_at": datetime.now().isoformat(),
            })
        return news_list
    except Exception as e:
        logger.debug(f"获取新浪国际新闻失败: {e}")
        return []


def fetch_all_news(sources: Optional[list[str]] = None) -> list[dict]:
    """统一新闻采集入口，按配置拉取所有新闻源"""
    if sources is None:
        sources = ["cls_telegraph", "eastmoney", "sina_global"]

    all_news = []
    source_map = {
        "cls_telegraph": fetch_cls_telegraph,
        "eastmoney": fetch_eastmoney_news,
        "sina_global": fetch_sina_global_news,
    }

    for src in sources:
        fetcher = source_map.get(src)
        if fetcher:
            try:
                items = fetcher()
                all_news.extend(items)
                logger.info(f"新闻源 [{src}]: 获取 {len(items)} 条")
            except Exception as e:
                logger.warning(f"新闻源 [{src}] 采集异常: {e}")

    # 简单去重（按标题相似度）
    seen = set()
    deduped = []
    for item in all_news:
        h = _hash_title(item["source"], item["title"])
        if h not in seen:
            seen.add(h)
            deduped.append(item)

    logger.info(f"新闻采集完成: 原始{len(all_news)}条, 去重后{len(deduped)}条")
    return deduped


# ====== 行业/板块分类 ======

SECTOR_KEYWORDS = {
    "消费": ["茅台", "五粮液", "伊利", "美的", "格力", "海尔", "消费", "白酒", "食品", "饮料", "家电", "零售", "电商", "拼多多", "京东", "阿里"],
    "科技": ["芯片", "半导体", "中芯", "AI", "人工智能", "大模型", "GPT", "软件", "华为", "鸿蒙", "算力", "服务器", "光模块", "PCB"],
    "金融": ["银行", "保险", "券商", "证券", "平安", "招商", "东方财富", "中信", "利率", "LPR", "降息", "降准", "金融"],
    "医药": ["医药", "药明", "恒瑞", "医疗", "创新药", "疫苗", "生物", "基因", "CXO"],
    "新能源": ["宁德", "比亚迪", "锂电", "光伏", "储能", "新能源", "风电", "氢能", "太阳能", "电池", "碳酸锂", "固态电池"],
    "汽车": ["汽车", "整车", "特斯拉", "蔚来", "理想", "小鹏", "智驾", "自动驾驶", "新能源车", "充电桩"],
    "房地产": ["地产", "房地产", "万科", "保利", "碧桂园", "楼市", "房贷", "住房"],
    "军工": ["军工", "航天", "船舶", "战斗机", "国防", "中航", "兵器"],
    "周期": ["煤炭", "钢铁", "有色", "化工", "石油", "铜", "铝", "黄金", "稀土", "航运"],
    "电力": ["电力", "电网", "发电", "水电", "火电", "核电", "长江电力"],
}


def classify_news_sector(title: str, content: str = "") -> str:
    """根据标题/内容判断新闻所属行业板块"""
    text = (title + " " + content).lower()
    scores = {}
    for sector, keywords in SECTOR_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text)
        if score > 0:
            scores[sector] = score
    if not scores:
        return "综合"
    return max(scores, key=scores.get)


def match_watchlist_news(news_items: list[dict], watchlist_stocks: list[dict]) -> list[dict]:
    """筛选与自选股相关的新闻，按相关性排序"""
    stock_names = {s["name"]: s for s in watchlist_stocks}
    stock_codes = {s["code"]: s for s in watchlist_stocks}

    matched = []
    for item in news_items:
        title = item.get("title", "")
        content = item.get("content", "")
        text = title + " " + content
        score = 0
        matched_stocks = []

        for name, stock in stock_names.items():
            if name in text:
                score += 10
                matched_stocks.append(name)
        for code, stock in stock_codes.items():
            if code in text:
                score += 8
                matched_stocks.append(stock["name"])

        # 行业关键词匹配
        sector = classify_news_sector(title, content)
        sector_score = sum(1 for kw in SECTOR_KEYWORDS.get(sector, []) if kw.lower() in text.lower())
        score += sector_score

        if score > 0 or sector != "综合":
            item["sector"] = sector
            item["relevance"] = score
            item["matched_stocks"] = list(set(matched_stocks))
            matched.append(item)

    matched.sort(key=lambda x: x.get("relevance", 0), reverse=True)
    return matched


def fetch_sina_roll_news(count: int = 50) -> list[dict]:
    """直接从新浪财经滚动接口获取新闻（不依赖akshare）"""
    import requests
    news_list = []
    try:
        url = f"https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&k=&num={count}&page=1&r={datetime.now().timestamp()}"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}, timeout=10)
        data = resp.json()
        items = data.get("result", {}).get("data", [])
        for item in items:
            title = item.get("title", "")
            content = item.get("intro", item.get("summary", ""))
            ctime = item.get("ctime", "")
            news_list.append({
                "source": "sina_finance",
                "title": title[:200],
                "content": content[:500],
                "url": item.get("url", ""),
                "pub_time": datetime.fromtimestamp(int(ctime)).isoformat() if ctime else "",
                "fetched_at": datetime.now().isoformat(),
            })
        logger.info(f"新浪滚动新闻: 获取 {len(news_list)} 条")
    except Exception as e:
        logger.error(f"新浪滚动新闻获取失败: {e}")
    return news_list


def fetch_sector_news(watchlist_stocks: list[dict] = None, count: int = 80) -> dict:
    """获取板块分类的新闻（直接HTTP源，过滤自选股相关）"""
    all_news = []
    # 新浪滚动新闻
    all_news.extend(fetch_sina_roll_news(count))

    # 再尝试akshare源（可能被代理阻断）
    try:
        all_news.extend(fetch_cls_telegraph())
    except Exception:
        pass
    try:
        all_news.extend(fetch_eastmoney_news())
    except Exception:
        pass

    # 去重
    seen = set()
    deduped = []
    for item in all_news:
        h = _hash_title(item["source"], item["title"])
        if h not in seen:
            seen.add(h)
            deduped.append(item)

    # 按行业分类
    by_sector = {}
    for item in deduped:
        sector = classify_news_sector(item.get("title", ""), item.get("content", ""))
        item["sector"] = sector
        by_sector.setdefault(sector, []).append(item)

    # 自选股相关筛选
    matched = []
    if watchlist_stocks:
        matched = match_watchlist_news(deduped, watchlist_stocks)

    return {
        "total": len(deduped),
        "by_sector": {k: len(v) for k, v in sorted(by_sector.items(), key=lambda x: -len(x[1]))},
        "sector_news": {k: v[:10] for k, v in by_sector.items()},
        "watchlist_related": matched[:20],
        "fetched_at": datetime.now().isoformat(),
    }


def fetch_pre_market_brief() -> str:
    """盘前简报：隔夜国际市场+国内重要消息"""
    parts = []
    now = datetime.now()

    # 国际简讯
    try:
        sina = fetch_sina_global_news()
        if sina:
            parts.append("【隔夜国际市场】")
            for item in sina[:8]:
                parts.append(f"· {item['title'][:100]}")
    except Exception:
        pass

    # 国内快讯
    try:
        cls_news = fetch_cls_telegraph()
        if cls_news:
            parts.append("\n【国内盘前要闻】")
            for item in cls_news[:8]:
                parts.append(f"· {item['title'][:100]}")
    except Exception:
        pass

    if not parts:
        return "今日暂无重要盘前消息。"

    parts.insert(0, f"【盘前简报】{now.strftime('%Y-%m-%d %H:%M')}\n")
    return "\n".join(parts)
