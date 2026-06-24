"""测试服务器 — 单进程内嵌Uvicorn，保证内存状态共享"""
import sys, time, threading, logging
logging.basicConfig(level=logging.WARNING)

# 先跑一次数据采集填充状态
from src.config_loader import reload_config; reload_config()
from src.storage.database import init_db; init_db()
from src.collector.market_data import fetch_watchlist_quotes, fetch_index_spot
from src.collector.news import fetch_all_news
from src.storage.state import state
from datetime import datetime
state.start_time = datetime.now()

wl = __import__('src.config_loader', fromlist=['get_watchlist']).get_watchlist()
quotes = fetch_watchlist_quotes(wl)
state.update_quotes(quotes)
print(f'[数据] 行情 {len(quotes)}只')

news = fetch_all_news(['eastmoney', 'sina_global'])
state.set_news(news)
print(f'[数据] 新闻 {len(news)}条')

# 生成一条测试告警
from src.storage.database import save_alert
save_alert({
    "alert_at": datetime.now().isoformat(),
    "alert_type": "test",
    "category": "opportunity",
    "stock_code": "600519",
    "stock_name": "贵州茅台",
    "rule_id": "test_alert",
    "title": "📈 测试告警: 贵州茅台放量突破",
    "detail": "当前价格: ¥1,272.86\n涨跌幅: +0.38%\n量比: 2.35\n成交额: 39.84亿",
    "notified": 0,
})
print('[数据] 测试告警已插入')

# 启动Web服务
from src.web.app import create_app
import uvicorn
import os

app = create_app()
port = 8765
print(f'[服务] 启动于 http://127.0.0.1:{port}')
threading.Thread(target=uvicorn.run, args=(app,), kwargs={'host':'127.0.0.1','port':port,'log_level':'error'}, daemon=True).start()
time.sleep(3)
print('[服务] 就绪')
