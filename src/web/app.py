"""FastAPI Web看板 — WebSocket实时推送 + REST API"""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.config_loader import get_settings, get_watchlist
from src.storage.state import state
from src.storage.database import get_conn

logger = logging.getLogger(__name__)

# ====== WebSocket连接管理器 ======

class ConnectionManager:
    """管理所有WebSocket连接，支持线程安全的广播"""

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
        logger.info(f"WebSocket断开 -1 (当前{len(self._connections)}个)")

    async def broadcast(self, message: dict):
        """广播消息到所有连接"""
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

# 线程间告警广播队列（从同步代码→异步WebSocket的桥接）
_alert_queue: asyncio.Queue = None


def get_alert_queue() -> asyncio.Queue:
    global _alert_queue
    if _alert_queue is None:
        _alert_queue = asyncio.Queue(maxsize=200)
    return _alert_queue


# 提供给同步代码调用的接口
def broadcast_alert_sync(alert: dict):
    """同步线程中调用，向所有WebSocket推送告警"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast({"type": "alert", "data": alert}), loop
            )
    except Exception:
        pass


def broadcast_quotes_sync():
    """同步线程中调用，推送实时行情"""
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
            asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast(payload), loop
            )
    except Exception:
        pass


# ====== FastAPI应用 ======

def create_app() -> FastAPI:
    app = FastAPI(title="自动盯盘Agent", version="0.1.0")

    # ---- WebSocket ----

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws_manager.connect(ws)
        # 发送初始连接确认
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

    # ---- REST API ----

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
                "volume_ratio": q.get("volume_ratio", 1),
                "turnover": q.get("turnover", 0),
                "high": q.get("high", 0),
                "low": q.get("low", 0),
                "amount": q.get("amount", 0),
                "change_amount": q.get("change_amount", 0),
            })
            enriched.append(entry)
        return {"count": len(enriched), "stocks": enriched}

    @app.get("/api/alerts")
    async def api_alerts(limit: int = Query(default=50, le=200)):
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM alert_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return {"count": len(rows), "alerts": [dict(r) for r in rows]}

    @app.get("/api/news")
    async def api_news(limit: int = Query(default=30, le=100)):
        news = state.get_news()
        return {"count": len(news), "news": news[:limit]}

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

    # ---- HTML Dashboard ----

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        dashboard_path = Path(__file__).parent / "dashboard.html"
        if dashboard_path.exists():
            return dashboard_path.read_text(encoding="utf-8")
        return "<h1>Dashboard not found</h1>"

    return app
