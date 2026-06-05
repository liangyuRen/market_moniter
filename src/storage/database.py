"""SQLite数据库操作 — 轻量级本地存储"""
import sqlite3
import threading
from pathlib import Path
from datetime import datetime

DB_DIR = Path(__file__).parent.parent.parent / "data"
DB_PATH = DB_DIR / "agent.db"

_local = threading.local()


def get_conn() -> sqlite3.Connection:
    """获取线程本地的数据库连接"""
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn


def init_db():
    """初始化数据库表"""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS stock_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            name TEXT,
            price REAL,
            change_pct REAL,
            volume REAL,
            amount REAL,
            turnover REAL,
            high REAL,
            low REAL,
            open REAL,
            pre_close REAL,
            volume_ratio REAL,
            fetched_at TEXT NOT NULL,
            UNIQUE(code, fetched_at)
        );

        CREATE INDEX IF NOT EXISTS idx_snapshot_code_time
            ON stock_snapshot(code, fetched_at);

        CREATE TABLE IF NOT EXISTS daily_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            sh_index REAL,
            sh_change_pct REAL,
            sz_index REAL,
            sz_change_pct REAL,
            cyb_index REAL,
            cyb_change_pct REAL,
            kcb_index REAL,
            kcb_change_pct REAL,
            up_count INTEGER,
            down_count INTEGER,
            limit_up_count INTEGER,
            limit_down_count INTEGER,
            total_amount REAL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS alert_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_at TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            category TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT,
            rule_id TEXT NOT NULL,
            title TEXT,
            detail TEXT,
            notified INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_alert_code_time
            ON alert_log(stock_code, alert_at);

        CREATE TABLE IF NOT EXISTS news_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT,
            url TEXT,
            pub_time TEXT,
            fetched_at TEXT NOT NULL,
            UNIQUE(source, title)
        );

        CREATE INDEX IF NOT EXISTS idx_news_time
            ON news_cache(fetched_at);
    """)
    conn.commit()


def save_snapshot(data: dict):
    """保存一条行情快照"""
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO stock_snapshot
            (code, name, price, change_pct, volume, amount, turnover,
             high, low, open, pre_close, volume_ratio, fetched_at)
        VALUES (:code, :name, :price, :change_pct, :volume, :amount, :turnover,
                :high, :low, :open, :pre_close, :volume_ratio, :fetched_at)
    """, data)
    conn.commit()


def save_batch_snapshots(rows: list[dict]):
    """批量保存行情快照"""
    conn = get_conn()
    conn.executemany("""
        INSERT OR REPLACE INTO stock_snapshot
            (code, name, price, change_pct, volume, amount, turnover,
             high, low, open, pre_close, volume_ratio, fetched_at)
        VALUES (:code, :name, :price, :change_pct, :volume, :amount, :turnover,
                :high, :low, :open, :pre_close, :volume_ratio, :fetched_at)
    """, rows)
    conn.commit()


def save_alert(alert: dict):
    """记录告警"""
    conn = get_conn()
    conn.execute("""
        INSERT INTO alert_log
            (alert_at, alert_type, category, stock_code, stock_name,
             rule_id, title, detail, notified, created_at)
        VALUES (:alert_at, :alert_type, :category, :stock_code, :stock_name,
                :rule_id, :title, :detail, :notified, :created_at)
    """, {
        **alert,
        "created_at": datetime.now().isoformat()
    })
    conn.commit()


def check_alert_cooldown(stock_code: str, rule_id: str, cooldown_seconds: int) -> bool:
    """检查告警冷却期，返回True表示在冷却期内"""
    conn = get_conn()
    row = conn.execute("""
        SELECT MAX(alert_at) as last_alert FROM alert_log
        WHERE stock_code=? AND rule_id=?
    """, (stock_code, rule_id)).fetchone()
    if not row or not row["last_alert"]:
        return False
    last = datetime.fromisoformat(row["last_alert"])
    return (datetime.now() - last).total_seconds() < cooldown_seconds


def save_news_batch(news_items: list[dict]):
    """批量保存新闻（去重写入）"""
    conn = get_conn()
    inserted = 0
    for item in news_items:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO news_cache
                    (source, title, content, url, pub_time, fetched_at)
                VALUES (:source, :title, :content, :url, :pub_time, :fetched_at)
            """, item)
            if conn.changes > 0:
                inserted += 1
        except Exception:
            continue
    conn.commit()
    return inserted
