# 🚀 自动盯盘Agent

A股智能监控系统，整合实时行情+国内外新闻，通过飞书/邮件推送机会和风险告警。

## 功能

- **实时行情监控**：基于akshare获取全A股实时数据
- **多维度告警**：涨跌幅、量比、冲高回落、资金流向、涨停跌停
- **新闻整合**：财联社电报、东方财富要闻、情绪分析
- **飞书推送**：实时告警卡片 + 盘前简报 + 盘后总结
- **邮件推送**：HTML格式收盘总结
- **Web看板**：FastAPI驱动的实时监控面板
- **行业板块监控**：板块异动、龙头股追踪

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

编辑 `config/settings.yaml`:
- 飞书Webhook URL（必填，否则无法推送）
- 邮件SMTP（可选）
- 其他参数按需调整

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
# 基本启动
docker-compose up -d

# 带Redis缓存
docker-compose --profile with-redis up -d
```

## 项目结构

```
自动盯盘agent/
├── config/                 # 配置文件
│   ├── settings.yaml       # 主配置（通知/调度/数据源）
│   ├── watchlist.yaml      # 自选股列表
│   └── alert_rules.yaml    # 告警规则
├── src/
│   ├── main.py             # 主入口
│   ├── scheduler.py        # 定时任务调度
│   ├── collector/          # 数据采集
│   ├── analyzer/           # 分析引擎
│   ├── alerter/            # 告警引擎
│   ├── notifier/           # 通知服务
│   ├── storage/            # 数据存储
│   └── web/                # Web看板
├── scripts/                # 辅助脚本
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

## 数据源

- 行情数据：akshare（封装东方财富、新浪等）
- 新闻数据：财联社、东方财富、新浪财经
- 交易日历：akshare自动获取

## 飞书机器人配置

1. 在飞书群设置 → 群机器人 → 添加自定义机器人
2. 复制Webhook地址
3. 填入 `config/settings.yaml` 的 `notify.feishu.webhook_url`

## 注意事项

- 首次运行akshare会下载较多依赖，请耐心等待
- 飞书Webhook限制约20条/分钟，系统已做限频处理
- 交易日历依赖akshare，节假日可能需手动确认
- Windows环境下建议使用Python 3.11+
