"""
自动盯盘Agent v0.2.0 — A股智能监控系统
"""
import json
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.config_loader import get_settings, get_watchlist, get_indices, reload_config
from src.storage.database import init_db
from src.storage.state import state

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
    """实时监控：拉行情 -> 资金流 -> 分析 -> 告警 -> WebSocket推送"""
    from src.collector.market_data import fetch_watchlist_quotes, fetch_market_overview, fetch_fund_flow_batch
    from src.alerter.rules import evaluate_realtime_rules
    from src.alerter.evaluator import process_alerts
    from src.storage.database import save_batch_snapshots, save_fund_flow_batch

    watchlist = get_watchlist()
    if not watchlist:
        return

    logger.debug(f"实时监控: {len(watchlist)}只自选股")

    # 1. 拉实时行情（东方财富源，含量比/PE/PB等）
    quotes = fetch_watchlist_quotes(watchlist)
    if quotes:
        state.update_quotes(quotes)
        # 保存行情快照到数据库
        try:
            snapshots = [{
                **q, "code": code,
                "name": q.get("name", ""),
                "volume": q.get("volume", 0),
                "amount": q.get("amount", 0),
                "turnover": q.get("turnover", 0),
                "volume_ratio": q.get("volume_ratio", 1.0),
                "pe": q.get("pe", 0),
                "pb": q.get("pb", 0),
                "total_market_cap": q.get("total_market_cap", 0),
                "circ_market_cap": q.get("circ_market_cap", 0),
                "fetched_at": datetime.now().isoformat(),
            } for code, q in quotes.items()]
            save_batch_snapshots(snapshots)
        except Exception:
            pass

    # 2. 市场总览
    market_overview = fetch_market_overview()

    # 3. 资金流向（分批拉取，每5分钟才拉一次全部）
    fund_flows = {}
    should_fetch_funds = True
    if state.last_quote_update:
        elapsed = (datetime.now() - state.last_quote_update).total_seconds()
        if elapsed < 300 and not getattr(state, '_last_fund_fetch', None):
            should_fetch_funds = True
        elif elapsed < 300:
            should_fetch_funds = (datetime.now() - state._last_fund_fetch).total_seconds() >= 300

    if should_fetch_funds:
        codes = [item["code"].strip() for item in watchlist]
        code_name = {item["code"].strip(): item.get("name", "") for item in watchlist}
        fund_flows = fetch_fund_flow_batch(codes)
        if fund_flows:
            state._last_fund_fetch = datetime.now()
            try:
                flow_records = []
                today = datetime.now().strftime("%Y-%m-%d")
                for code, flow in fund_flows.items():
                    flow_records.append({
                        "code": code,
                        "name": code_name.get(code, ""),
                        "date": flow.get("date", today),
                        "main_net_inflow": flow.get("main_net_inflow", 0),
                        "main_net_inflow_pct": flow.get("main_net_inflow_pct", 0),
                        "super_large_net_inflow": flow.get("super_large_net_inflow", 0),
                        "large_net_inflow": flow.get("large_net_inflow", 0),
                        "mid_net_inflow": flow.get("mid_net_inflow", 0),
                        "small_net_inflow": flow.get("small_net_inflow", 0),
                        "fetched_at": datetime.now().isoformat(),
                    })
                save_fund_flow_batch(flow_records)
            except Exception:
                pass

    # 4. 评估告警规则
    raw_alerts = evaluate_realtime_rules(quotes, fund_flows, market_overview)

    # 5. 告警处理
    final_alerts = process_alerts(raw_alerts)

    # 6. WebSocket推送行情
    from src.web.app import broadcast_quotes_sync, broadcast_alert_sync
    try:
        broadcast_quotes_sync()
    except Exception:
        pass

    # 7. WebSocket推送告警
    if final_alerts:
        logger.info(f"触发 {len(final_alerts)} 条告警")
        for alert in final_alerts:
            try:
                broadcast_alert_sync(alert)
            except Exception:
                pass


def news_collector():
    """新闻采集：拉新闻 -> 板块分类 -> 情绪分析 -> 存储 -> 推送"""
    from src.collector.news import fetch_all_news, fetch_sector_news
    from src.alerter.rules import evaluate_news_alerts
    from src.alerter.evaluator import process_alerts
    from src.storage.database import save_news_batch

    watchlist = get_watchlist()
    logger.debug("新闻采集...")
    news_cfg = get_settings().get("data_source", {}).get("news_sources", [])
    all_news = fetch_all_news(news_cfg)
    if not all_news:
        return
    state.set_news(all_news)
    save_news_batch(all_news)

    # 板块分类新闻（缓存到state供dashboard API使用）
    try:
        sector_data = fetch_sector_news(watchlist, count=80)
        state._sector_news = sector_data
    except Exception:
        pass

    news_alerts = evaluate_news_alerts(all_news, watchlist)
    final_alerts = process_alerts(news_alerts)
    if final_alerts:
        logger.info(f"触发 {len(final_alerts)} 条新闻告警")
        from src.web.app import broadcast_alert_sync
        for alert in final_alerts:
            try:
                broadcast_alert_sync(alert)
            except Exception:
                pass


def global_market_task():
    """全球市场采集：美股/日韩/港股/期货"""
    from src.collector.global_markets import fetch_global_market_report
    from src.storage.database import save_global_market_batch, save_market_sentiment

    try:
        report = fetch_global_market_report()
        all_indices = []
        for region_key in ["us", "jp_kr", "hk"]:
            for idx in report[region_key]["indices"]:
                idx["region"] = region_key
                all_indices.append(idx)
        if report.get("vix"):
            vix = report["vix"]
            all_indices.append({
                "code": "VIX", "name": "VIX恐慌指数", "region": "US",
                "price": vix.get("price", 0),
                "change_pct": vix.get("change_pct", 0),
                "change_amount": 0,
                "fetched_at": datetime.now().isoformat(),
            })
        if all_indices:
            save_global_market_batch(all_indices)
            logger.info(f"全球市场: 保存 {len(all_indices)} 条指数数据")
    except Exception as e:
        logger.error(f"全球市场采集失败: {e}")


def technical_scan_task():
    """技术指标扫描：对自选股计算技术指标，生成策略信号"""
    from src.collector.market_data import fetch_stock_history
    from src.analyzer.technical import calc_macd, calc_rsi, check_macd_golden_cross, check_macd_dead_cross, check_rsi_extreme
    from src.storage.database import save_signal, deactivate_signals

    watchlist = get_watchlist()
    now = datetime.now().isoformat()
    signal_count = 0

    for item in watchlist:
        code = item["code"].strip()
        market = item.get("market", "SH" if code.startswith(("6", "688")) else "SZ")
        hist = fetch_stock_history(code, market, days=250)
        if hist.empty or len(hist) < 30:
            continue

        close = hist["收盘"].astype(float)
        price = close.iloc[-1]
        indicators_json = json.dumps({"price": price}, ensure_ascii=False)

        # MACD信号 — 用完整历史计算MACD柱
        macd = calc_macd(close)
        macd_hist_series = macd["hist"]
        if len(macd_hist_series) >= 3:
            if check_macd_golden_cross(macd_hist_series):
                deactivate_signals(code, "macd_golden")
                save_signal({
                    "signal_at": now, "stock_code": code, "stock_name": item["name"],
                    "signal_type": "buy", "strategy": "macd_golden",
                    "strength": "medium", "price": price,
                    "indicators": indicators_json,
                    "reason": "MACD金叉信号，DIF上穿DEA",
                })
                signal_count += 1
            elif check_macd_dead_cross(macd_hist_series):
                deactivate_signals(code, "macd_dead")
                save_signal({
                    "signal_at": now, "stock_code": code, "stock_name": item["name"],
                    "signal_type": "sell", "strategy": "macd_dead",
                    "strength": "medium", "price": price,
                    "indicators": indicators_json,
                    "reason": "MACD死叉信号，DIF下穿DEA",
                })
                signal_count += 1

        # RSI极端信号
        rsi_series = calc_rsi(close)
        rsi = round(rsi_series.iloc[-1], 2) if len(rsi_series) > 0 else 50
        rsi_state = check_rsi_extreme(rsi)
        if rsi_state == "oversold":
            deactivate_signals(code, "rsi_oversold")
            save_signal({
                "signal_at": now, "stock_code": code, "stock_name": item["name"],
                "signal_type": "buy", "strategy": "rsi_oversold",
                "strength": "strong" if rsi < 20 else "medium", "price": price,
                "indicators": indicators_json,
                "reason": f"RSI超卖({rsi})，短期可能反弹",
            })
            signal_count += 1
        elif rsi_state == "overbought":
            deactivate_signals(code, "rsi_overbought")
            save_signal({
                "signal_at": now, "stock_code": code, "stock_name": item["name"],
                "signal_type": "sell", "strategy": "rsi_overbought",
                "strength": "strong" if rsi > 80 else "medium", "price": price,
                "indicators": indicators_json,
                "reason": f"RSI超买({rsi})，注意回调风险",
            })
            signal_count += 1

    if signal_count > 0:
        logger.info(f"技术扫描: 生成 {signal_count} 条策略信号")


def daily_summary_task():
    """每日收盘总结：生成利好/利空因素，存储日报"""
    from src.collector.market_data import fetch_watchlist_quotes, fetch_index_spot, fetch_market_overview, fetch_north_bound_flow
    from src.collector.global_markets import fetch_global_market_report
    from src.collector.news import fetch_all_news
    from src.analyzer.sentiment import filter_important_news
    from src.storage.database import save_north_bound

    logger.info("生成每日收盘总结...")
    watchlist = get_watchlist()
    index_list = get_indices()
    today = datetime.now().strftime("%Y-%m-%d")

    # 收盘行情
    quotes = fetch_watchlist_quotes(watchlist)
    index_quotes = fetch_index_spot(index_list)
    market_overview = fetch_market_overview()

    # 北向资金
    north_bound = fetch_north_bound_flow()
    if north_bound:
        north_bound["fetched_at"] = datetime.now().isoformat()
        try:
            save_north_bound(north_bound)
        except Exception:
            pass

    # 全球市场
    global_report = fetch_global_market_report()

    # 新闻
    news_cfg = get_settings().get("data_source", {}).get("news_sources", [])
    all_news = fetch_all_news(news_cfg)
    important_news = filter_important_news(all_news, watchlist)

    # ---- 生成利好/利空因子 ----
    bullish_factors = []
    bearish_factors = []

    # 1. 涨跌家数
    up_count = market_overview.get("up_count", 0)
    down_count = market_overview.get("down_count", 0)
    if up_count > down_count * 2:
        bullish_factors.append(f"全市场涨跌比 {up_count}:{down_count}，多方占优")
    elif down_count > up_count * 2:
        bearish_factors.append(f"全市场涨跌比 {up_count}:{down_count}，空方占优")

    # 2. 涨停/跌停
    limit_up = market_overview.get("limit_up_count", 0)
    limit_down = market_overview.get("limit_down_count", 0)
    if limit_up >= 50:
        bullish_factors.append(f"涨停家数 {limit_up} 家，市场情绪热烈")
    if limit_down >= 20:
        bearish_factors.append(f"跌停家数 {limit_down} 家，恐慌情绪蔓延")

    # 3. 成交额
    total_amount = market_overview.get("total_amount_billion", 0)
    if total_amount > 15000:
        bullish_factors.append(f"成交额 {total_amount:.0f} 亿，成交活跃")
    elif total_amount > 0 and total_amount < 5000:
        bearish_factors.append(f"成交额仅 {total_amount:.0f} 亿，交投清淡")

    # 4. 北向资金
    if north_bound:
        nb_flow = north_bound.get("net_inflow", 0)
        if nb_flow > 5_000_000_000:
            bullish_factors.append(f"北向资金净流入 {nb_flow/1e8:.1f} 亿，外资持续加仓")
        elif nb_flow < -5_000_000_000:
            bearish_factors.append(f"北向资金净流出 {abs(nb_flow)/1e8:.1f} 亿，外资撤离")

    # 5. 全球市场
    us_summary = global_report.get("us", {}).get("summary", "")
    if us_summary == "普涨":
        bullish_factors.append("隔夜美股普涨，外部环境利好A股")
    elif us_summary == "普跌":
        bearish_factors.append("隔夜美股普跌，外部风险传导A股")

    jp_kr_summary = global_report.get("jp_kr", {}).get("summary", "")
    if jp_kr_summary == "普涨":
        bullish_factors.append("日韩市场普涨，亚太市场整体向好")
    elif jp_kr_summary == "普跌":
        bearish_factors.append("日韩市场普跌，亚太市场整体承压")

    # 6. VIX
    vix = global_report.get("vix", {})
    if vix:
        vix_level = vix.get("level", "unknown")
        if "恐慌" in vix_level:
            bearish_factors.append(f"VIX: {vix_level}，全球风险偏好下降")

    # 7. 自选股异动
    big_ups = []
    big_downs = []
    for code, q in quotes.items():
        chg = q.get("change_pct", 0)
        if chg >= 5:
            big_ups.append(f"{q.get('name', code)} +{chg:.2f}%")
        elif chg <= -5:
            big_downs.append(f"{q.get('name', code)} {chg:.2f}%")
    if big_ups:
        bullish_factors.append(f"自选大涨: {', '.join(big_ups[:5])}")
    if big_downs:
        bearish_factors.append(f"自选大跌: {', '.join(big_downs[:5])}")

    # 8. 重要新闻
    pos_news = [n for n in important_news if n.get("_sentiment", {}).get("sentiment") == "positive"][:3]
    neg_news = [n for n in important_news if n.get("_sentiment", {}).get("sentiment") == "negative"][:3]
    for n in pos_news:
        bullish_factors.append(f"利好: {n.get('title', '')[:80]}")
    for n in neg_news:
        bearish_factors.append(f"利空: {n.get('title', '')[:80]}")

    # 9. 指数表现
    for code, idx in index_quotes.items():
        chg = idx.get("change_pct", 0)
        name = idx.get("name", "")
        if chg >= 2:
            bullish_factors.append(f"{name} 涨{chg:+.2f}%，大盘强势")
        elif chg <= -2:
            bearish_factors.append(f"{name} 跌{chg:+.2f}%，大盘弱势")

    # 存储日报
    from src.storage.database import get_conn
    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO daily_summary
                (date, up_count, down_count, limit_up_count, limit_down_count,
                 total_amount, bullish_factors, bearish_factors, global_summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            today,
            up_count, down_count,
            limit_up, limit_down,
            total_amount,
            "\n".join(bullish_factors) if bullish_factors else "无明显利好",
            "\n".join(bearish_factors) if bearish_factors else "无明显利空",
            f"美股: {us_summary} | 日韩: {jp_kr_summary} | VIX: {vix.get('level', 'N/A')}",
            datetime.now().isoformat(),
        ))
        conn.commit()
        logger.info(f"日报已保存: 利好{bullish_factors}条, 利空{bearish_factors}条")
    except Exception as e:
        logger.error(f"保存日报失败: {e}")

    logger.info("每日总结生成完成")


def start_web():
    """启动Web看板"""
    from src.web.app import create_app
    import uvicorn
    web_cfg = get_settings().get("web", {})
    host = web_cfg.get("host", "0.0.0.0")
    port = web_cfg.get("port", 8000)
    logger.info(f"Web看板: http://{host}:{port}")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


def main():
    print("=" * 50)
    print("   自动盯盘Agent v0.2.0")
    print("   A股智能监控系统")
    print("=" * 50)

    init_db()
    logger.info("数据库初始化完成")
    state.start_time = datetime.now()

    from src.scheduler import (
        register_realtime_task, register_news_task,
        register_pre_market_task, register_post_market_task,
        register_global_market_task, register_technical_scan_task,
        start as start_scheduler, stop as stop_scheduler,
    )

    register_realtime_task(realtime_monitor)
    register_news_task(news_collector)
    register_pre_market_task(lambda: logger.info("盘前简报(Web看板查看)"))
    register_post_market_task(daily_summary_task)
    register_global_market_task(global_market_task)
    register_technical_scan_task(technical_scan_task)

    start_scheduler()
    logger.info(f"交易时段: {'是' if state.today_is_trading_day else '否'}")

    def shutdown(sig, frame):
        logger.info("收到退出信号...")
        state.running = False
        stop_scheduler()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    start_web()


if __name__ == "__main__":
    main()
