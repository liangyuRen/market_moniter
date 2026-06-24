"""
FastAPI Web看板 — REST API + WebSocket实时推送 + 策略数据库查询
"""
import asyncio
import json
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse, HTMLResponse

from src.config_loader import get_settings, get_watchlist
from src.storage.state import state
from src.storage.database import get_conn

logger = logging.getLogger(__name__)

# ====== WebSocket连接管理器 ======

class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)
        logger.info(f"WebSocket连接 +1 (当前{len(self._connections)}个)")

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            if ws in self._connections:
                self._connections.remove(ws)
        logger.info(f"WebSocket断开 -1")

    async def broadcast(self, message: dict):
        async with self._lock:
            dead = []
            payload = json.dumps(message, ensure_ascii=False, default=str)
            for ws in self._connections:
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._connections.remove(ws)

    @property
    def active_count(self):
        return len(self._connections)


ws_manager = ConnectionManager()


def broadcast_alert_sync(alert: dict):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast({"type": "alert", "data": alert}), loop
            )
    except Exception:
        pass


def broadcast_quotes_sync():
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            quotes = state.get_all_quotes()
            payload = {
                "type": "quotes",
                "data": {
                    "quotes": quotes,
                    "last_update": state.last_quote_update.isoformat() if state.last_quote_update else None,
                    "market_session": state.get_market_session(),
                },
            }
            asyncio.run_coroutine_threadsafe(ws_manager.broadcast(payload), loop)
    except Exception:
        pass


# ====== FastAPI应用 ======

def create_app() -> FastAPI:
    app = FastAPI(title="自动盯盘Agent", version="0.2.0")

    # ---- WebSocket ----
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws_manager.connect(ws)
        await ws.send_text(json.dumps({
            "type": "connected",
            "data": {"message": "盯盘Agent已连接", "time": datetime.now().isoformat()}
        }, ensure_ascii=False))
        try:
            while True:
                data = await ws.receive_text()
                if data == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
        except WebSocketDisconnect:
            await ws_manager.disconnect(ws)
        except Exception:
            await ws_manager.disconnect(ws)

    # ---- 系统状态 ----
    @app.get("/api/status")
    async def api_status():
        return {
            "running": state.running,
            "start_time": state.start_time.isoformat() if state.start_time else None,
            "uptime_seconds": (datetime.now() - state.start_time).total_seconds() if state.start_time else 0,
            "today_is_trading_day": state.today_is_trading_day,
            "market_session": state.get_market_session(),
            "is_trading_time": state.is_trading_time(),
            "stats": state.today_stats,
            "ws_connections": ws_manager.active_count,
        }

    # ---- 行情数据 ----
    @app.get("/api/quotes")
    async def api_quotes():
        quotes = state.get_all_quotes()
        return {
            "count": len(quotes),
            "last_update": state.last_quote_update.isoformat() if state.last_quote_update else None,
            "quotes": quotes,
            "market_session": state.get_market_session(),
        }

    @app.get("/api/watchlist")
    async def api_watchlist():
        watchlist = get_watchlist()
        quotes = state.get_all_quotes()
        enriched = []
        for item in watchlist:
            code = item["code"]
            entry = dict(item)
            q = quotes.get(code, {})
            entry.update({
                "price": q.get("price", 0),
                "change_pct": q.get("change_pct", 0),
                "change_amount": q.get("change_amount", 0),
                "volume_ratio": q.get("volume_ratio", 1),
                "turnover": q.get("turnover", 0),
                "pe": q.get("pe", 0),
                "pb": q.get("pb", 0),
                "total_market_cap": q.get("total_market_cap", 0),
                "circ_market_cap": q.get("circ_market_cap", 0),
                "high": q.get("high", 0),
                "low": q.get("low", 0),
                "open": q.get("open", 0),
                "amount": q.get("amount", 0),
            })
            enriched.append(entry)
        return {"count": len(enriched), "stocks": enriched}

    @app.get("/api/market")
    async def api_market():
        quotes = state.get_all_quotes()
        up = sum(1 for q in quotes.values() if q.get("change_pct", 0) > 0)
        down = sum(1 for q in quotes.values() if q.get("change_pct", 0) < 0)
        return {
            "session": state.get_market_session(),
            "is_trading_time": state.is_trading_time(),
            "today_is_trading_day": state.today_is_trading_day,
            "stats": state.today_stats,
            "monitor_summary": {"up": up, "down": down, "total": len(quotes)},
            "ws_connections": ws_manager.active_count,
        }

    # ---- 告警 ----
    @app.get("/api/alerts")
    async def api_alerts(limit: int = Query(default=50, le=200)):
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM alert_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return {"count": len(rows), "alerts": [dict(r) for r in rows]}

    # ---- 新闻 ----
    @app.get("/api/news")
    async def api_news(limit: int = Query(default=30, le=100)):
        news = state.get_news()
        return {"count": len(news), "news": news[:limit]}

    # ---- 资金流向 ----
    @app.get("/api/fundflow")
    async def api_fundflow():
        from src.storage.database import get_fund_flow_summary
        flows = get_fund_flow_summary()
        return {"count": len(flows), "flows": flows}

    # ---- 全球市场 ----
    @app.get("/api/global")
    async def api_global():
        from src.storage.database import get_latest_global_markets
        markets = get_latest_global_markets()
        return {"count": len(markets), "markets": markets}

    # ---- 策略信号 ----
    @app.get("/api/signals")
    async def api_signals(limit: int = Query(default=50, le=200)):
        from src.storage.database import get_active_signals
        signals = get_active_signals(limit)
        return {"count": len(signals), "signals": signals}

    # ---- 市场情绪 ----
    @app.get("/api/sentiment")
    async def api_sentiment():
        from src.storage.database import get_latest_sentiment
        sent = get_latest_sentiment()
        return {"sentiment": sent}

    # ---- 日报总结 ----
    @app.get("/api/daily-summary")
    async def api_daily_summary(date_str: str = Query(default=None)):
        conn = get_conn()
        if date_str:
            row = conn.execute(
                "SELECT * FROM daily_summary WHERE date = ?", (date_str,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM daily_summary ORDER BY date DESC LIMIT 1"
            ).fetchone()
        if row:
            return {"summary": dict(row)}
        return {"summary": None}

    # ---- 技术分析快照 ----
    @app.get("/api/technical/{code}")
    async def api_technical(code: str):
        from src.collector.market_data import fetch_stock_history
        from src.analyzer.technical import calc_technical_summary
        market = "SH" if code.startswith(("6", "688")) else "SZ"
        hist = fetch_stock_history(code, market, days=250)
        if hist.empty:
            return {"error": "无法获取历史数据", "code": code}
        summary = calc_technical_summary(hist)
        return {"code": code, "technical": summary}

    # ---- 策略回测 ----
    @app.get("/api/backtest/strategies")
    async def api_backtest_strategies():
        from src.strategy.backtest import STRATEGIES
        return {
            "strategies": [
                {"id": k, "name": v["name"], "params": v["params"]}
                for k, v in STRATEGIES.items()
            ]
        }

    @app.post("/api/backtest/run")
    async def api_backtest_run(data: dict):
        from src.strategy.backtest import run_backtest
        code = data.get("code", "")
        strategy_id = data.get("strategy_id", "macd_cross")
        days = int(data.get("days", 500))
        init_capital = float(data.get("init_capital", 100000))
        if not code:
            return {"error": "请提供股票代码"}
        result = run_backtest(code, strategy_id, days, init_capital)
        return {"backtest": result}

    @app.get("/api/backtest/results")
    async def api_backtest_results(
        code: str = Query(default=None),
        strategy: str = Query(default=None),
        limit: int = Query(default=30, le=100)
    ):
        from src.storage.database import get_backtest_results
        results = get_backtest_results(code, strategy, limit)
        return {"count": len(results), "results": results}

    # ---- 自选股管理 ----
    @app.post("/api/watchlist/add")
    async def api_watchlist_add(data: dict):
        code = data.get("code", "").strip()
        name = data.get("name", "").strip()
        category = data.get("category", "自选")
        if not code or not name:
            return {"error": "请提供股票代码和名称"}
        # 写YAML
        yaml_path = Path(__file__).parent.parent.parent / "config" / "watchlist.yaml"
        import yaml
        with open(yaml_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        stocks = config.setdefault("stocks", [])
        existing = [s for s in stocks if s.get("code") == code]
        if existing:
            return {"ok": False, "error": f"{code} 已在自选列表中"}
        market = "SH" if code.startswith(("6", "688")) else "SZ"
        stocks.append({
            "code": code, "market": market, "name": name,
            "category": category, "alert_enabled": True,
        })
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        # 同步SQLite
        from src.storage.database import add_watchlist_db
        add_watchlist_db(code, name, category)
        from src.config_loader import reload_config
        reload_config()
        return {"ok": True, "added": {"code": code, "name": name, "category": category}}

    @app.delete("/api/watchlist/{code}")
    async def api_watchlist_remove(code: str):
        yaml_path = Path(__file__).parent.parent.parent / "config" / "watchlist.yaml"
        import yaml
        with open(yaml_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        stocks = config.get("stocks", [])
        new_stocks = [s for s in stocks if s.get("code") != code]
        if len(new_stocks) == len(stocks):
            return {"ok": False, "error": f"未找到 {code}"}
        config["stocks"] = new_stocks
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        # 同步SQLite
        from src.storage.database import remove_watchlist_db
        remove_watchlist_db(code)
        from src.config_loader import reload_config
        reload_config()
        return {"ok": True, "removed": code}

    @app.get("/api/stock/search")
    async def api_stock_search(q: str = Query(default="")):
        if len(q) < 2:
            return {"results": []}
        import requests
        results = []
        # 腾讯接口（稳定）
        try:
            url = f"https://smartbox.gtimg.cn/s3/?t=all&q={q}"
            resp = requests.get(url, timeout=5)
            resp.encoding = "gbk"
            text = resp.text
            # 格式: v_hint="sh~600519~贵州茅台~gzmt~GP-A;sz~000858~五粮液~wly~GP-A"
            if '="' in text:
                text = text.split('="', 1)[1].rstrip('"')
            for item in text.split(";"):
                item = item.strip()
                if not item:
                    continue
                parts = item.split("~")
                if len(parts) >= 3:
                    code = parts[1] if len(parts) > 1 else ""
                    name = parts[2]
                    # 腾讯返回的name可能是unicode转义序列 (贵州...)
                    if "\\u" in name:
                        try:
                            name = name.encode().decode("unicode_escape")
                        except Exception:
                            pass
                    mkt = "SH" if code.startswith(("6", "688")) else "SZ"
                    results.append({"code": code, "name": name, "market": mkt})
        except Exception:
            pass
        # 东方财富搜索兜底
        if not results:
            try:
                url = f"https://searchapi.eastmoney.com/bussiness/Web/GetCMSSearchResult?type=8192&keyword={q}&pageindex=1&pagesize=10"
                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
                data = resp.json()
                for item in data.get("Data", []):
                    code = item.get("SecurityCode", "")
                    name = item.get("Name", "")
                    mkt = "SH" if code.startswith(("6", "688")) else "SZ"
                    results.append({"code": code, "name": name, "market": mkt})
            except Exception:
                pass
        return {"results": results[:10]}

    # ---- HTML Dashboard ----
    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        dashboard_path = Path(__file__).parent / "dashboard.html"
        if dashboard_path.exists():
            return dashboard_path.read_text(encoding="utf-8")
        return "<h1>Dashboard not found</h1>"

    return app
