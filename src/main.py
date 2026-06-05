"""自动盯盘Agent — 主入口"""
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from src.config_loader import get_settings, get_watchlist, get_indices, reload_config
from src.storage.database import init_db
from src.storage.state import state

# 日志配置
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

cfg = get_settings()
log_level = getattr(logging, cfg.get("logging", {}).get("level", "INFO"))

logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "agent.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


def realtime_monitor():
    """实时监控任务：拉行情 → 分析 → 告警 → 推送"""
    from src.collector.market_data import fetch_watchlist_quotes, fetch_market_overview
    from src.alerter.rules import evaluate_realtime_rules
    from src.alerter.evaluator import process_alerts

    watchlist = get_watchlist()
    if not watchlist:
        return

    logger.debug(f"实时监控: {len(watchlist)}只自选股")

    # 1. 拉实时行情
    quotes = fetch_watchlist_quotes(watchlist)
    if not quotes:
        logger.debug("行情数据为空")
        return

    state.update_quotes(quotes)

    # 2. 拉资金流向（可选，较慢）
    fund_flows = {}
    # 资金流向接口较慢，每5分钟拉一次即可
    # from src.collector.market_data import fetch_stock_fund_flow
    # for item in watchlist:
    #     code = item["code"]
    #     market = item.get("market", "SH")
    #     fund_flows[code] = fetch_stock_fund_flow(code, market)

    # 3. 市场总览
    market_overview = fetch_market_overview()

    # 4. 评估规则
    raw_alerts = evaluate_realtime_rules(quotes, fund_flows, market_overview)

    # 5. 告警处理（去重/排序/限频）
    final_alerts = process_alerts(raw_alerts)

    # 6. WebSocket实时推送行情
    try:
        from src.web.app import broadcast_quotes_sync
        broadcast_quotes_sync()
    except Exception:
        pass

    # 7. 推送
    if final_alerts:
        logger.info(f"触发 {len(final_alerts)} 条告警")
        state.increment_alerts()
        # WebSocket广播告警
        from src.web.app import broadcast_alert_sync
        for alert in final_alerts:
            try:
                broadcast_alert_sync(alert)
            except Exception:
                pass
        # 飞书推送（兼容已配置的情况）
        try:
            from src.notifier.feishu import send_alert_batch
            sent = send_alert_batch(final_alerts)
            logger.info(f"已推送 {sent}/{len(final_alerts)} 条告警")
        except Exception:
            pass


def news_collector():
    """新闻采集任务：拉新闻 → 分析 → 推送"""
    from src.collector.news import fetch_all_news
    from src.alerter.rules import evaluate_news_alerts
    from src.alerter.evaluator import process_alerts
    from src.notifier.feishu import send_alert_batch
    from src.storage.database import save_news_batch

    watchlist = get_watchlist()

    logger.debug("新闻采集...")

    # 1. 拉新闻
    news_cfg = get_settings().get("data_source", {}).get("news_sources", [])
    all_news = fetch_all_news(news_cfg)

    if not all_news:
        return

    state.set_news(all_news)
    save_news_batch(all_news)

    # 2. 新闻告警
    news_alerts = evaluate_news_alerts(all_news, watchlist)
    final_alerts = process_alerts(news_alerts)

    # 3. 推送
    if final_alerts:
        logger.info(f"触发 {len(final_alerts)} 条新闻告警")
        # WebSocket广播
        from src.web.app import broadcast_alert_sync
        for alert in final_alerts:
            try:
                broadcast_alert_sync(alert)
            except Exception:
                pass
        # 飞书兜底
        try:
            from src.notifier.feishu import send_alert_batch
            send_alert_batch(final_alerts)
        except Exception:
            pass


def pre_market_brief():
    """盘前简报任务"""
    from src.collector.news import fetch_pre_market_brief
    from src.notifier.feishu import _get_webhook_url, _send_card

    logger.info("生成盘前简报...")
    brief = fetch_pre_market_brief()

    url = _get_webhook_url()
    if url:
        import requests
        try:
            payload = {
                "msg_type": "interactive",
                "card": {
                    "header": {
                        "title": {"tag": "plain_text", "content": f"🌅 盘前简报 {datetime.now().strftime('%m-%d')}"},
                        "template": "blue",
                    },
                    "elements": [{
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": brief},
                    }],
                },
            }
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"盘前简报推送失败: {e}")


def post_market_summary():
    """盘后总结任务"""
    from src.collector.market_data import fetch_watchlist_quotes, fetch_index_spot, fetch_market_overview
    from src.collector.news import fetch_all_news
    from src.alerter.evaluator import generate_daily_summary
    from src.notifier.feishu import send_daily_summary
    from src.notifier.email_sender import send_daily_summary_email

    logger.info("生成盘后总结...")

    watchlist = get_watchlist()
    index_list = get_indices()

    # 拉当日收盘数据
    quotes = fetch_watchlist_quotes(watchlist)
    index_quotes = fetch_index_spot(index_list)
    market_overview = fetch_market_overview()

    # 新闻
    news_cfg = get_settings().get("data_source", {}).get("news_sources", [])
    all_news = fetch_all_news(news_cfg)

    # 生成总结
    summary = generate_daily_summary(quotes, index_quotes, all_news, market_overview)

    # 推送飞书
    send_daily_summary(summary)

    # 推送邮件
    send_daily_summary_email(summary)

    logger.info("盘后总结已推送")


def start_web():
    """启动Web看板服务"""
    from src.web.app import create_app
    import uvicorn

    web_cfg = get_settings().get("web", {})
    host = web_cfg.get("host", "0.0.0.0")
    port = web_cfg.get("port", 8000)

    logger.info(f"Web看板: http://{host}:{port}")
    uvicorn.run(
        create_app(),
        host=host,
        port=port,
        log_level="warning",
    )


def main():
    """主入口"""
    print("=" * 50)
    print("   🚀 自动盯盘Agent v0.1.0")
    print("   A股智能监控系统")
    print("=" * 50)

    # 初始化数据库
    init_db()
    logger.info("数据库初始化完成")

    # 初始化状态
    state.start_time = datetime.now()

    # 注册调度任务
    from src.scheduler import (
        register_realtime_task,
        register_news_task,
        register_pre_market_task,
        register_post_market_task,
        start as start_scheduler,
        stop as stop_scheduler,
    )

    register_realtime_task(realtime_monitor)
    register_news_task(news_collector)
    register_pre_market_task(pre_market_brief)
    register_post_market_task(post_market_summary)

    # 启动调度器
    start_scheduler()

    # 启动提示
    try:
        from src.notifier.feishu import send_test_message
        send_test_message()
    except Exception:
        pass
    try:
        from src.notifier.email_sender import send_email
        logger.info("邮件通知已就绪")
    except Exception:
        pass

    # 信号处理
    def shutdown(sig, frame):
        logger.info("收到退出信号...")
        state.running = False
        stop_scheduler()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # 启动Web看板（主线程阻塞）
    logger.info(f"交易时段: {'是' if state.today_is_trading_day else '否（今日非交易日）'}")
    start_web()


if __name__ == "__main__":
    main()
