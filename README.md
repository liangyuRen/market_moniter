# ${EMOJI} 自动盯盘Agent

A股智能监控系统 v0.2.0 — 实时行情 + 策略信号 + 全球市场 + 日报总结

## 功能

- **实时行情监控**：新浪+腾讯双源，含价格/涨跌幅/量比/PE/PB/市值
- **多维度告警**：涨跌幅、量比、冲高回落、资金流向、涨停跌停
- **策略信号**：MACD金叉死叉、RSI超买超卖、KDJ极端值
- **资金流向**：主力/超大单/大单/中单/小单净流向
- **全球市场**：美股三大指数、日经225、韩国KOSPI、恒生指数、VIX恐慌指数
- **日报总结**：盘后自动生成利好/利空因子分析
- **Web看板**：FastAPI + WebSocket实时推送，多Tab终端
- **行业板块**：行业/概念板块异动监控
- **新闻整合**：财联社电报、东方财富要闻、情绪分析

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

编辑 `config/settings.yaml`:
- 邮件SMTP（可选）
- 调度参数、分析阈值按需调整

编辑 `config/watchlist.yaml`:
- 添加你的自选股
- 调整行业ETF列表

### 3. 初始化

```bash
python scripts/init_db.py
```

### 4. 启动

```bash
python -m src.main
```

启动后访问 http://localhost:8000 查看Web看板。

### 5. Docker部署

```bash
docker-compose up -d
```

## Web看板功能

| Tab | 功能 |
|-----|------|
| 监控 | 自选股实时行情 + 量比/PE/PB + 告警流 + 新闻 |
| 告警 | 分类查看风险/机会/信息告警 |
| 全球 | 美股/日韩/港股指数 + VIX + 市场情绪 |
| 资金 | 自选股资金流向 + 行业板块异动 + 北向资金 |
| 策略 | MACD/RSI/KDJ信号 + 技术指标详情 |
| 日报 | 每日利好/利空因子分析 + 情绪计 |

## 数据源

- 行情数据：新浪 (hq.sinajs.cn) + 腾讯 (qt.gtimg.cn)
- 量比/PE/PB/市值：腾讯财经接口
- 新闻数据：财联社、东方财富、新浪财经（akshare封装）
- 全球指数：新浪 + Yahoo Finance
- 交易日历：akshare自动获取

## 项目结构

```
自动盯盘agent/
├── config/
│   ├── settings.yaml       # 主配置
│   ├── watchlist.yaml      # 自选股列表
│   └── alert_rules.yaml    # 告警规则
├── src/
│   ├── main.py             # 主入口
│   ├── scheduler.py        # 定时任务调度
│   ├── collector/          # 数据采集
│   │   ├── market_data.py  # A股行情
│   │   ├── global_markets.py # 全球市场
│   │   ├── news.py         # 新闻采集
│   │   └── industry.py     # 行业板块
│   ├── analyzer/           # 分析引擎
│   │   ├── anomaly.py      # 异动检测
│   │   ├── technical.py    # 技术指标
│   │   └── sentiment.py    # 情绪分析
│   ├── alerter/            # 告警引擎
│   ├── notifier/           # 通知服务
│   ├── storage/            # 数据存储
│   │   ├── database.py     # SQLite(12张表)
│   │   └── state.py        # 内存状态
│   └── web/                # Web看板
│       ├── app.py          # FastAPI + WebSocket
│       └── dashboard.html  # 监控终端
├── scripts/                # 辅助脚本
└── data/                   # SQLite数据库
```

## 数据库表

| 表名 | 用途 |
|------|------|
| stock_snapshot | 行情快照 |
| alert_log | 告警记录 |
| news_cache | 新闻缓存 |
| daily_summary | 每日总结(利好/利空) |
| strategy_signals | 策略信号 |
| strategy_backtest | 策略回测 |
| fund_flow | 资金流向 |
| global_market | 全球指数 |
| north_bound_flow | 北向资金 |
| market_sentiment | 市场情绪 |
| sector_anomaly | 行业异动 |

## 注意事项

- 首次运行akshare会下载较多依赖，请耐心等待
- Windows环境下建议使用Python 3.11+
- 交易日历依赖akshare，节假日可能需手动确认
- 配置 `config/settings.yaml.example` 为模板参考
