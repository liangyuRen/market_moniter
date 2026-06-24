"""
SQLite数据库操作 — 行情 / 告警 / 新闻 / 策略信号 / 资金流向 / 全球市场
"""
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, date

DB_DIR = Path(__file__).parent.parent.parent / "data"
DB_PATH = DB_DIR / "agent.db"
_local = threading.local()


def get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        -- 行情快照
        CREATE TABLE IF NOT EXISTS stock_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            name TEXT,
            price REAL, change_pct REAL,
            volume REAL, amount REAL, turnover REAL,
            high REAL, low REAL, open REAL, pre_close REAL,
            volume_ratio REAL, pe REAL, pb REAL,
            total_market_cap REAL, circ_market_cap REAL,
            fetched_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_snapshot_code_time ON stock_snapshot(code, fetched_at);

        -- 每日收盘总结
        CREATE TABLE IF NOT EXISTS daily_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            sh_index REAL, sh_change_pct REAL,
            sz_index REAL, sz_change_pct REAL,
            cyb_index REAL, cyb_change_pct REAL,
            kcb_index REAL, kcb_change_pct REAL,
            up_count INTEGER, down_count INTEGER,
            limit_up_count INTEGER, limit_down_count INTEGER,
            total_amount REAL,
            bullish_factors TEXT,
            bearish_factors TEXT,
            global_summary TEXT,
            created_at TEXT NOT NULL
        );

        -- 告警日志
        CREATE TABLE IF NOT EXISTS alert_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_at TEXT NOT NULL, alert_type TEXT NOT NULL,
            category TEXT NOT NULL, stock_code TEXT NOT NULL,
            stock_name TEXT, rule_id TEXT NOT NULL,
            title TEXT, detail TEXT, notified INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_alert_code_time ON alert_log(stock_code, alert_at);

        -- 新闻缓存
        CREATE TABLE IF NOT EXISTS news_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL, title TEXT NOT NULL,
            content TEXT, url TEXT, pub_time TEXT, fetched_at TEXT NOT NULL,
            UNIQUE(source, title)
        );
        CREATE INDEX IF NOT EXISTS idx_news_time ON news_cache(fetched_at);

        -- ====== 策略信号数据库 ======

        -- 量化策略信号
        CREATE TABLE IF NOT EXISTS strategy_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_at TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT,
            signal_type TEXT NOT NULL,  -- buy / sell / hold
            strategy TEXT NOT NULL,      -- macd_golden / ma_breakout / rsi_oversold / kdj / volume_break
            strength TEXT,               -- strong / medium / weak
            price REAL,
            indicators TEXT,             -- JSON: 技术指标快照
            reason TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_signal_code_time ON strategy_signals(stock_code, signal_at);
        CREATE INDEX IF NOT EXISTS idx_signal_type ON strategy_signals(signal_type, is_active);

        -- 资金流向快照
        CREATE TABLE IF NOT EXISTS fund_flow (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            name TEXT,
            date TEXT NOT NULL,
            main_net_inflow REAL,
            main_net_inflow_pct REAL,
            super_large_net_inflow REAL,
            large_net_inflow REAL,
            mid_net_inflow REAL,
            small_net_inflow REAL,
            fetched_at TEXT NOT NULL,
            UNIQUE(code, date)
        );
        CREATE INDEX IF NOT EXISTS idx_fund_flow_code_date ON fund_flow(code, date);

        -- 全球市场快照
        CREATE TABLE IF NOT EXISTS global_market (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            index_code TEXT NOT NULL,
            index_name TEXT,
            region TEXT,
            price REAL,
            change_pct REAL,
            change_amount REAL,
            fetched_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_global_region_time ON global_market(region, fetched_at);

        -- 北向资金
        CREATE TABLE IF NOT EXISTS north_bound_flow (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            net_inflow REAL,
            buy_amount REAL,
            sell_amount REAL,
            fetched_at TEXT NOT NULL
        );

        -- 市场情绪记录
        CREATE TABLE IF NOT EXISTS market_sentiment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            overall_sentiment TEXT,       -- bullish / bearish / neutral
            sentiment_score REAL,
            up_ratio REAL,
            limit_up_count INTEGER,
            limit_down_count INTEGER,
            north_bound_inflow REAL,
            vix_level TEXT,
            global_bias TEXT,             -- global markets bias: risk_on / risk_off / neutral
            key_factors TEXT,             -- JSON: 主要影响因子
            created_at TEXT NOT NULL
        );

        -- 行业板块异动
        CREATE TABLE IF NOT EXISTS sector_anomaly (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            detected_at TEXT NOT NULL,
            board_name TEXT NOT NULL,
            board_type TEXT,              -- industry / concept
            change_pct REAL,
            lead_stock TEXT,
            direction TEXT,               -- up / down
            fetched_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sector_time ON sector_anomaly(detected_at);

        -- 策略回测记录
        CREATE TABLE IF NOT EXISTS strategy_backtest (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            strategy TEXT NOT NULL,
            signal_date TEXT NOT NULL,
            entry_price REAL,
            exit_price REAL,
            return_pct REAL,
            holding_days INTEGER,
            result TEXT,                  -- win / lose / active
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_backtest_code ON strategy_backtest(stock_code, strategy);

        -- 自选股管理表
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT,
            category TEXT DEFAULT '自选',
            created_at TEXT NOT NULL
        );

        -- 批量回测结果
        CREATE TABLE IF NOT EXISTS backtest_result (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            strategy TEXT NOT NULL,
            backtest_date TEXT NOT NULL,
            total_return REAL,
            win_rate REAL,
            max_drawdown REAL,
            avg_return REAL,
            total_trades INTEGER,
            buy_hold_return REAL,
            trades_json TEXT,
            equity_json TEXT,
            UNIQUE(code, strategy, backtest_date)
        );
        CREATE INDEX IF NOT EXISTS idx_bt_result_code ON backtest_result(code, strategy);
    """)
    conn.commit()


# ====== 行情操作 ======

def save_snapshot(data: dict):
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO stock_snapshot
            (code, name, price, change_pct, volume, amount, turnover,
             high, low, open, pre_close, volume_ratio, pe, pb,
             total_market_cap, circ_market_cap, fetched_at)
        VALUES (:code, :name, :price, :change_pct, :volume, :amount, :turnover,
                :high, :low, :open, :pre_close, :volume_ratio, :pe, :pb,
                :total_market_cap, :circ_market_cap, :fetched_at)
    """, data)
    conn.commit()


def save_batch_snapshots(rows: list[dict]):
    conn = get_conn()
    conn.executemany("""
        INSERT OR REPLACE INTO stock_snapshot
            (code, name, price, change_pct, volume, amount, turnover,
             high, low, open, pre_close, volume_ratio, pe, pb,
             total_market_cap, circ_market_cap, fetched_at)
        VALUES (:code, :name, :price, :change_pct, :volume, :amount, :turnover,
                :high, :low, :open, :pre_close, :volume_ratio, :pe, :pb,
                :total_market_cap, :circ_market_cap, :fetched_at)
    """, rows)
    conn.commit()


# ====== 告警操作 ======

def save_alert(alert: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO alert_log (alert_at, alert_type, category, stock_code, stock_name,
                               rule_id, title, detail, notified, created_at)
        VALUES (:alert_at, :alert_type, :category, :stock_code, :stock_name,
                :rule_id, :title, :detail, :notified, :created_at)
    """, {**alert, "created_at": datetime.now().isoformat()})
    conn.commit()


def check_alert_cooldown(stock_code: str, rule_id: str, cooldown_seconds: int) -> bool:
    conn = get_conn()
    row = conn.execute("""
        SELECT MAX(alert_at) as last_alert FROM alert_log
        WHERE stock_code=? AND rule_id=?
    """, (stock_code, rule_id)).fetchone()
    if not row or not row["last_alert"]:
        return False
    last = datetime.fromisoformat(row["last_alert"])
    return (datetime.now() - last).total_seconds() < cooldown_seconds


# ====== 新闻操作 ======

def save_news_batch(news_items: list[dict]) -> int:
    conn = get_conn()
    inserted = 0
    for item in news_items:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO news_cache (source, title, content, url, pub_time, fetched_at)
                VALUES (:source, :title, :content, :url, :pub_time, :fetched_at)
            """, item)
            if conn.changes > 0:
                inserted += 1
        except Exception:
            continue
    conn.commit()
    return inserted


# ====== 策略信号操作 ======

def save_signal(signal: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO strategy_signals
            (signal_at, stock_code, stock_name, signal_type, strategy, strength,
             price, indicators, reason, is_active, created_at)
        VALUES (:signal_at, :stock_code, :stock_name, :signal_type, :strategy, :strength,
                :price, :indicators, :reason, 1, :created_at)
    """, {**signal, "created_at": datetime.now().isoformat()})
    conn.commit()


def deactivate_signals(stock_code: str, strategy: str):
    conn = get_conn()
    conn.execute("""
        UPDATE strategy_signals SET is_active = 0
        WHERE stock_code = ? AND strategy = ? AND is_active = 1
    """, (stock_code, strategy))
    conn.commit()


def get_active_signals(limit: int = 50) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM strategy_signals WHERE is_active = 1
        ORDER BY signal_at DESC LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


# ====== 资金流向操作 ======

def save_fund_flow_batch(flows: list[dict]):
    conn = get_conn()
    conn.executemany("""
        INSERT OR REPLACE INTO fund_flow
            (code, name, date, main_net_inflow, main_net_inflow_pct,
             super_large_net_inflow, large_net_inflow, mid_net_inflow,
             small_net_inflow, fetched_at)
        VALUES (:code, :name, :date, :main_net_inflow, :main_net_inflow_pct,
                :super_large_net_inflow, :large_net_inflow, :mid_net_inflow,
                :small_net_inflow, :fetched_at)
    """, flows)
    conn.commit()


def get_fund_flow_summary(date: str = None) -> list[dict]:
    conn = get_conn()
    if date:
        rows = conn.execute("SELECT * FROM fund_flow WHERE date = ?", (date,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM fund_flow WHERE date = (SELECT MAX(date) FROM fund_flow)
        """).fetchall()
    return [dict(r) for r in rows]


# ====== 全球市场操作 ======

def save_global_market_batch(indices: list[dict]):
    conn = get_conn()
    conn.executemany("""
        INSERT INTO global_market (index_code, index_name, region, price, change_pct, change_amount, fetched_at)
        VALUES (:code, :name, :region, :price, :change_pct, :change_amount, :fetched_at)
    """, indices)
    conn.commit()


def get_latest_global_markets() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM global_market
        WHERE fetched_at = (SELECT MAX(fetched_at) FROM global_market)
        ORDER BY region
    """).fetchall()
    return [dict(r) for r in rows]


# ====== 北向资金操作 ======

def save_north_bound(data: dict):
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO north_bound_flow (date, net_inflow, buy_amount, sell_amount, fetched_at)
        VALUES (:date, :net_inflow, :buy_amount, :sell_amount, :fetched_at)
    """, data)
    conn.commit()


# ====== 市场情绪操作 ======

def save_market_sentiment(data: dict):
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO market_sentiment
            (date, overall_sentiment, sentiment_score, up_ratio, limit_up_count,
             limit_down_count, north_bound_inflow, vix_level, global_bias, key_factors, created_at)
        VALUES (:date, :overall_sentiment, :sentiment_score, :up_ratio, :limit_up_count,
                :limit_down_count, :north_bound_inflow, :vix_level, :global_bias, :key_factors, :created_at)
    """, {**data, "created_at": datetime.now().isoformat()})
    conn.commit()


def get_latest_sentiment() -> dict:
    conn = get_conn()
    row = conn.execute("""
        SELECT * FROM market_sentiment ORDER BY date DESC LIMIT 1
    """).fetchone()
    return dict(row) if row else {}


# ====== 行业板块操作 ======

def save_sector_anomalies(anomalies: list[dict]):
    conn = get_conn()
    conn.executemany("""
        INSERT INTO sector_anomaly (detected_at, board_name, board_type, change_pct, lead_stock, direction, fetched_at)
        VALUES (:detected_at, :board_name, :board_type, :change_pct, :lead_stock, :direction, :fetched_at)
    """, anomalies)
    conn.commit()


# ====== 回测操作 ======

def save_backtest_entry(signal: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO strategy_backtest (stock_code, strategy, signal_date, entry_price, result, created_at)
        VALUES (:stock_code, :strategy, :signal_date, :entry_price, 'active', :created_at)
    """, {**signal, "created_at": datetime.now().isoformat()})
    conn.commit()


def update_backtest_exit(stock_code: str, strategy: str, exit_price: float, holding_days: int):
    conn = get_conn()
    conn.execute("""
        UPDATE strategy_backtest SET exit_price = ?, holding_days = ?,
        return_pct = ROUND((exit_price - entry_price) / entry_price * 100, 2),
        result = CASE WHEN exit_price > entry_price THEN 'win' ELSE 'lose' END
        WHERE stock_code = ? AND strategy = ? AND result = 'active'
    """, (exit_price, holding_days, stock_code, strategy))
    conn.commit()


# ====== 批量回测结果操作 ======

def save_backtest_result(code: str, strategy: str, stats: dict, trades: list):
    import json
    conn = get_conn()
    today = date.today().isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO backtest_result
            (code, strategy, backtest_date, total_return, win_rate, max_drawdown,
             avg_return, total_trades, buy_hold_return, trades_json, equity_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        code, strategy, today,
        stats.get("total_return", 0),
        stats.get("win_rate", 0),
        stats.get("max_drawdown", 0),
        stats.get("avg_return", 0),
        stats.get("total_trades", 0),
        stats.get("buy_hold_return", 0),
        json.dumps(trades, ensure_ascii=False, default=str),
        json.dumps(stats.get("equity_curve", []), ensure_ascii=False),
    ))
    conn.commit()


def get_backtest_results(code: str = None, strategy: str = None, limit: int = 50) -> list[dict]:
    conn = get_conn()
    sql = "SELECT * FROM backtest_result WHERE 1=1"
    params = []
    if code:
        sql += " AND code = ?"
        params.append(code)
    if strategy:
        sql += " AND strategy = ?"
        params.append(strategy)
    sql += " ORDER BY backtest_date DESC, total_return DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


# ====== 自选股管理（SQLite备份 + YAML同步） ======

def get_watchlist_db() -> list[dict]:
    """从数据库读取自选股"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM watchlist ORDER BY category, id
    """).fetchall()
    return [dict(r) for r in rows] if rows else []


def add_watchlist_db(code: str, name: str, category: str = "自选") -> bool:
    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO watchlist (code, name, category, created_at)
            VALUES (?, ?, ?, ?)
        """, (code, name, category, datetime.now().isoformat()))
        conn.commit()
        return conn.changes > 0
    except Exception:
        return False


def remove_watchlist_db(code: str) -> bool:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM watchlist WHERE code = ?", (code,))
        conn.commit()
        return conn.changes > 0
    except Exception:
        return False
