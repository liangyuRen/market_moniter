"""定时任务调度器 — APScheduler + 交易时段管理"""
import logging
from datetime import datetime, date
from typing import Optional, Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from src.config_loader import get_settings
from src.storage.state import state

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def is_trading_day(check_date: date = None) -> bool:
    """判断是否为A股交易日"""
    if check_date is None:
        check_date = date.today()

    # 周末直接跳过
    if check_date.weekday() >= 5:
        return False

    # 尝试用akshare交易日历验证
    try:
        import akshare as ak
        cal_df = ak.tool_trade_date_hist_sina()
        if cal_df is not None and not cal_df.empty:
            trade_dates = set(
                cal_df["trade_date"].astype(str).str.strip().tolist()
            )
            date_str = check_date.strftime("%Y-%m-%d")
            return date_str in trade_dates
    except Exception:
        pass

    # 回退：仅排除周末
    return True


def is_trading_time() -> bool:
    """当前是否在交易时段（9:15-15:00）"""
    return state.is_trading_time()


def should_run_realtime() -> bool:
    """判断是否应该运行实时监控任务"""
    if not is_trading_day():
        return False
    return is_trading_time()


def should_run_pre_market() -> bool:
    """判断是否应该运行盘前任务"""
    if not is_trading_day():
        return False
    return state.get_market_session() == "auction"


def should_run_post_market() -> bool:
    """判断是否应该运行盘后任务"""
    if not is_trading_day():
        return False
    return state.get_market_session() == "post_market"


# ====== 任务回调注册 ======

_realtime_callback: Optional[Callable] = None
_news_callback: Optional[Callable] = None
_pre_market_callback: Optional[Callable] = None
_post_market_callback: Optional[Callable] = None


def register_realtime_task(callback: Callable):
    global _realtime_callback
    _realtime_callback = callback


def register_news_task(callback: Callable):
    global _news_callback
    _news_callback = callback


def register_pre_market_task(callback: Callable):
    global _pre_market_callback
    _pre_market_callback = callback


def register_post_market_task(callback: Callable):
    global _post_market_callback
    _post_market_callback = callback


def _wrap_realtime():
    if should_run_realtime() and _realtime_callback:
        try:
            _realtime_callback()
        except Exception as e:
            logger.error(f"实时监控任务异常: {e}", exc_info=True)


def _wrap_news():
    if should_run_realtime() and _news_callback:
        try:
            _news_callback()
        except Exception as e:
            logger.error(f"新闻采集任务异常: {e}", exc_info=True)


def _wrap_pre_market():
    if should_run_pre_market() and _pre_market_callback:
        try:
            _pre_market_callback()
        except Exception as e:
            logger.error(f"盘前任务异常: {e}", exc_info=True)


def _wrap_post_market():
    if should_run_post_market() and _post_market_callback:
        try:
            _post_market_callback()
        except Exception as e:
            logger.error(f"盘后任务异常: {e}", exc_info=True)


def start():
    """启动调度器"""
    cfg = get_settings()
    sched_cfg = cfg.get("scheduler", {})

    realtime_interval = sched_cfg.get("realtime_interval", 10)
    news_interval = sched_cfg.get("news_interval", 300)
    pre_time = sched_cfg.get("pre_market_time", "09:15")
    post_time = sched_cfg.get("post_market_time", "15:10")

    pre_h, pre_m = map(int, pre_time.split(":"))
    post_h, post_m = map(int, post_time.split(":"))

    # 实时行情监控（仅交易时段）
    scheduler.add_job(
        _wrap_realtime,
        IntervalTrigger(seconds=realtime_interval),
        id="realtime_monitor",
        name="实时行情监控",
        replace_existing=True,
    )

    # 新闻采集
    scheduler.add_job(
        _wrap_news,
        IntervalTrigger(seconds=news_interval),
        id="news_collector",
        name="新闻采集",
        replace_existing=True,
    )

    # 盘前简报
    scheduler.add_job(
        _wrap_pre_market,
        CronTrigger(hour=pre_h, minute=pre_m, day_of_week="mon-fri"),
        id="pre_market",
        name="盘前简报",
        replace_existing=True,
    )

    # 盘后总结
    scheduler.add_job(
        _wrap_post_market,
        CronTrigger(hour=post_h, minute=post_m, day_of_week="mon-fri"),
        id="post_market",
        name="盘后总结",
        replace_existing=True,
    )

    # 每日0点重置状态
    scheduler.add_job(
        state.reset_daily_stats,
        CronTrigger(hour=0, minute=1),
        id="daily_reset",
        name="每日状态重置",
        replace_existing=True,
    )

    # 日终交易日检查
    scheduler.add_job(
        lambda: setattr(state, "today_is_trading_day", is_trading_day()),
        CronTrigger(hour=8, minute=0, day_of_week="mon-fri"),
        id="trading_day_check",
        name="交易日检查",
        replace_existing=True,
    )

    scheduler.start()
    state.today_is_trading_day = is_trading_day()
    logger.info(
        f"调度器已启动 | 实时间隔:{realtime_interval}s | "
        f"新闻间隔:{news_interval}s | "
        f"盘前:{pre_time} | 盘后:{post_time} | "
        f"今日交易日:{state.today_is_trading_day}"
    )


def stop():
    """停止调度器"""
    scheduler.shutdown(wait=False)
    logger.info("调度器已停止")
