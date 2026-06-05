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
