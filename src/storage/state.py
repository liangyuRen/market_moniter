"""运行状态管理 — 内存中的全局状态"""
import threading
from datetime import datetime, time
from typing import Optional


class AppState:
    """可观测的全局状态容器"""

    def __init__(self):
        self._lock = threading.Lock()

        # 系统状态
        self.running = True
        self.start_time: Optional[datetime] = None

        # 市场状态
        self.today_is_trading_day: Optional[bool] = None
        self.market_session: str = "unknown"  # pre_open / morning / lunch / afternoon / closed
        self.last_market_check: Optional[datetime] = None

        # 行情缓存 {code: snapshot_dict}
        self.quote_cache: dict = {}
        self.last_quote_update: Optional[datetime] = None

        # 自选股日内高/低点 {code: {"high": ..., "low": ..., "open": ...}}
        self.intraday_extremes: dict = {}

        # 新闻缓存
        self.news_cache: list = []
        self.last_news_update: Optional[datetime] = None

        # 告警冷却追踪 {f"{code}:{rule_id}": last_alert_time}
        self.alert_cooldowns: dict = {}

        # 今日统计数据
        self.today_stats: dict = {
            "alerts_fired": 0,
            "news_fetched": 0,
            "quotes_fetched": 0,
        }

    # ---- 市场时段判断 ----

    @staticmethod
    def get_market_session(now: datetime = None) -> str:
        """判断当前处于哪个交易时段"""
        if now is None:
            now = datetime.now()
        t = now.time()

        if time(9, 15) <= t < time(9, 26):
            return "auction"       # 集合竞价
        elif time(9, 30) <= t < time(11, 31):
            return "morning"       # 上午交易
        elif time(11, 31) <= t < time(13, 0):
            return "lunch"         # 午休
        elif time(13, 0) <= t < time(15, 1):
            return "afternoon"     # 下午交易
        elif time(15, 1) <= t < time(15, 31):
            return "post_market"   # 盘后
        else:
            return "closed"

    @staticmethod
    def is_trading_time(now: datetime = None) -> bool:
        """是否正在交易时段（竞价+连续交易）"""
        session = AppState.get_market_session(now)
        return session in ("auction", "morning", "afternoon")

    @staticmethod
    def is_auction_time(now: datetime = None) -> bool:
        return AppState.get_market_session(now) == "auction"

    # ---- 线程安全操作 ----

    def update_quotes(self, quotes: dict):
        with self._lock:
            self.quote_cache.update(quotes)
            self.last_quote_update = datetime.now()
            self.today_stats["quotes_fetched"] += len(quotes)
            self._update_extremes(quotes)

    def _update_extremes(self, quotes: dict):
        for code, q in quotes.items():
            if code not in self.intraday_extremes:
                self.intraday_extremes[code] = {
                    "high": q.get("high", q.get("price", 0)),
                    "low": q.get("low", q.get("price", 0)),
                    "open": q.get("open", q.get("price", 0)),
                    "pre_close": q.get("pre_close", 0),
                }
            else:
                price = q.get("price", 0)
                if price > self.intraday_extremes[code]["high"]:
                    self.intraday_extremes[code]["high"] = price
                if price > 0 and price < self.intraday_extremes[code]["low"]:
                    self.intraday_extremes[code]["low"] = price

    def get_quote(self, code: str) -> Optional[dict]:
        with self._lock:
            return self.quote_cache.get(code)

    def get_all_quotes(self) -> dict:
        with self._lock:
            return dict(self.quote_cache)

    def set_news(self, news_list: list):
        with self._lock:
            self.news_cache = news_list
            self.last_news_update = datetime.now()
            self.today_stats["news_fetched"] += len(news_list)

    def get_news(self) -> list:
        with self._lock:
            return list(self.news_cache)

    def is_on_cooldown(self, key: str, cooldown_seconds: int) -> bool:
        with self._lock:
            if key not in self.alert_cooldowns:
                return False
            elapsed = (datetime.now() - self.alert_cooldowns[key]).total_seconds()
            return elapsed < cooldown_seconds

    def set_cooldown(self, key: str):
        with self._lock:
            self.alert_cooldowns[key] = datetime.now()

    def increment_alerts(self):
        with self._lock:
            self.today_stats["alerts_fired"] += 1

    def reset_daily_stats(self):
        with self._lock:
            self.today_stats = {"alerts_fired": 0, "news_fetched": 0, "quotes_fetched": 0}
            self.intraday_extremes.clear()
            self.alert_cooldowns.clear()


# 全局单例
state = AppState()
