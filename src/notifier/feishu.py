"""飞书机器人推送 — Webhook消息卡片"""
import json
import logging
import time
from datetime import datetime
from typing import Optional

import requests

from src.config_loader import get_settings

logger = logging.getLogger(__name__)


def _get_webhook_url() -> Optional[str]:
    cfg = get_settings()
    fs = cfg.get("notify", {}).get("feishu", {})
    if not fs.get("enabled"):
        return None
    url = fs.get("webhook_url", "")
    if "YOUR_WEBHOOK_URL" in url or not url:
        logger.warning("飞书Webhook未配置")
        return None
    return url


def _send_card(card: dict) -> bool:
    """发送飞书消息卡片"""
    url = _get_webhook_url()
    if not url:
        return False
    try:
        payload = {"msg_type": "interactive", "card": card}
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 0 or data.get("StatusCode") == 0:
                return True
            logger.warning(f"飞书发送失败: {data}")
            return False
        logger.warning(f"飞书HTTP错误: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        logger.error(f"飞书请求异常: {e}")
        return False


def _build_alert_card(alert: dict) -> dict:
    """构建单条告警的消息卡片"""
    category = alert.get("category", "info")
    color_map = {
        "risk": "red",
        "opportunity": "green",
        "info": "blue",
    }

    return {
        "header": {
            "title": {"tag": "plain_text", "content": alert.get("title", "告警")},
            "template": color_map.get(category, "blue"),
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": alert.get("detail", "").replace("\n", "  \n"),
                },
            },
            {
                "tag": "hr",
            },
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": f"⏰ {alert.get('alert_at', datetime.now().strftime('%H:%M:%S'))} | 规则: {alert.get('rule_id', '')}",
                    }
                ],
            },
        ],
    }


def send_alert(alert: dict) -> bool:
    """发送单条告警到飞书"""
    card = _build_alert_card(alert)
    return _send_card(card)


def send_alert_batch(alerts: list[dict]) -> int:
    """批量发送告警（带频率控制）"""
    cfg = get_settings()
    rate_limit = cfg.get("notify", {}).get("feishu", {}).get("rate_limit_per_minute", 15)
    success = 0

    for i, alert in enumerate(alerts):
        if i > 0 and i % rate_limit == 0:
            logger.info("飞书频率限制，等待60秒...")
            time.sleep(60)

        if send_alert(alert):
            success += 1
        time.sleep(0.5)  # 单条间隔

    return success


def send_daily_summary(summary: dict) -> bool:
    """发送每日收盘总结到飞书"""
    url = _get_webhook_url()
    if not url:
        return False

    indices = summary.get("indices", {})
    overview = summary.get("summary", {})
    market = summary.get("market_overview", {})
    top_gainers = summary.get("top_gainers", [])
    top_losers = summary.get("top_losers", [])
    important_news = summary.get("important_news", [])
    limit_up = overview.get("limit_up", [])
    limit_down = overview.get("limit_down", [])

    # 指数部分
    index_md = ""
    for code, idx in indices.items():
        emoji = "🟢" if idx.get("change_pct", 0) >= 0 else "🔴"
        index_md += f"{emoji} **{idx.get('name', code)}**: {idx.get('price', 0):.2f} ({idx.get('change_pct', 0):+.2f}%)  \n"

    # 涨跌停
    limit_info = ""
    if limit_up:
        limit_info += f"🔥 涨停: {', '.join(s['name'] + ' +' + str(s['change_pct'])+'%' for s in limit_up[:5])}  \n"
    if limit_down:
        limit_info += f"💥 跌停: {', '.join(s['name'] + ' ' + str(s['change_pct'])+'%' for s in limit_down[:5])}  \n"

    # 涨跌榜
    gainer_md = ""
    for s in top_gainers[:5]:
        gainer_md += f"📈 {s['name']}: ¥{s['price']:.2f} ({s['change_pct']:+.2f}%)  \n"

    loser_md = ""
    for s in top_losers[:5]:
        loser_md += f"📉 {s['name']}: ¥{s['price']:.2f} ({s['change_pct']:+.2f}%)  \n"

    # 新闻
    news_md = ""
    for n in important_news[:10]:
        emoji = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(n.get("sentiment", "neutral"), "⚪")
        news_md += f"{emoji} {n.get('title', '')}  \n"

    markdown = (
        f"**【📊 {summary.get('date', '')} 市场收盘总结】**\n\n"
        f"━━━━━━━━━━━━\n"
        f"**大盘指数**\n{index_md}\n"
        f"**市场情绪**\n"
        f"✅ 上涨: {market.get('up_count', 0)} | ❌ 下跌: {market.get('down_count', 0)}\n"
        f"成交额: {market.get('total_amount_billion', 0)}亿\n"
        f"涨停: {market.get('limit_up_count', 0)} | 跌停: {market.get('limit_down_count', 0)}\n\n"
        f"━━━━━━━━━━━━\n"
        f"**自选股概览**\n"
        f"📊 总计: {overview.get('total', 0)}只\n"
        f"✅ 上涨: {overview.get('up', 0)}只\n"
        f"❌ 下跌: {overview.get('down', 0)}只\n"
        f"{limit_info}\n"
        f"**涨幅榜**\n{gainer_md}\n"
        f"**跌幅榜**\n{loser_md}\n"
    )

    if important_news:
        markdown += f"━━━━━━━━━━━━\n**📰 重要新闻**\n{news_md}"

    try:
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"📊 {summary.get('date', '')} 收盘总结"},
                    "template": "blue",
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": markdown},
                    }
                ],
            },
        }
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"发送收盘总结失败: {e}")
        return False


def send_test_message() -> bool:
    """发送测试消息验证飞书配置"""
    url = _get_webhook_url()
    if not url:
        logger.error("飞书Webhook未配置，请在config/settings.yaml中设置")
        return False

    card = {
        "header": {
            "title": {"tag": "plain_text", "content": "✅ 自动盯盘Agent 已上线"},
            "template": "green",
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**启动时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                               "系统已开始监控您的自选股，有异动会及时推送。",
                },
            }
        ],
    }
    return _send_card(card)
