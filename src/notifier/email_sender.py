"""邮件发送 — SMTP邮件推送"""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional

from src.config_loader import get_settings

logger = logging.getLogger(__name__)


def _get_email_config() -> Optional[dict]:
    cfg = get_settings().get("notify", {}).get("email", {})
    if not cfg.get("enabled"):
        return None
    if "your_email" in str(cfg.get("smtp_user", "")):
        logger.warning("邮件SMTP未配置")
        return None
    return cfg


def send_email(subject: str, html_body: str) -> bool:
    """发送HTML格式邮件"""
    cfg = _get_email_config()
    if not cfg:
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = cfg["from_addr"]
        msg["To"] = ", ".join(cfg.get("to_addrs", []))

        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP_SSL(cfg["smtp_host"], cfg.get("smtp_port", 465)) as server:
            server.login(cfg["smtp_user"], cfg["smtp_password"])
            server.sendmail(cfg["from_addr"], cfg["to_addrs"], msg.as_string())

        logger.info(f"邮件已发送: {subject}")
        return True
    except Exception as e:
        logger.error(f"邮件发送失败: {e}")
        return False


def build_daily_summary_html(summary: dict) -> str:
    """构建每日收盘总结HTML邮件"""
    indices = summary.get("indices", {})
    market = summary.get("market_overview", {})
    overview = summary.get("summary", {})
    top_gainers = summary.get("top_gainers", [])
    top_losers = summary.get("top_losers", [])
    important_news = summary.get("important_news", [])

    # 指数行
    index_rows = ""
    for code, idx in indices.items():
        color = "#27ae60" if idx.get("change_pct", 0) >= 0 else "#e74c3c"
        index_rows += (
            f"<tr>"
            f"<td>{idx.get('name', code)}</td>"
            f"<td>{idx.get('price', 0):.2f}</td>"
            f"<td style='color:{color}'>{idx.get('change_pct', 0):+.2f}%</td>"
            f"</tr>"
        )

    # 股票行
    def stock_rows(stocks, is_up=True):
        rows = ""
        for s in stocks[:10]:
            color = "#27ae60" if s["change_pct"] >= 0 else "#e74c3c"
            rows += (
                f"<tr>"
                f"<td>{s['name']}</td>"
                f"<td>{s['price']:.2f}</td>"
                f"<td style='color:{color}'>{s['change_pct']:+.2f}%</td>"
                f"</tr>"
            )
        return rows

    # 新闻行
    news_rows = ""
    for n in important_news[:10]:
        emoji = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(n.get("sentiment"), "⚪")
        news_rows += f"<tr><td>{emoji}</td><td>{n.get('title', '')}</td></tr>"

    html = f"""
    <html>
    <head><style>
        body {{ font-family: 'Microsoft YaHei', sans-serif; background: #f5f5f5; padding: 20px; }}
        .container {{ max-width: 720px; margin: 0 auto; background: #fff; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .header {{ background: #2c3e50; color: #fff; padding: 20px; border-radius: 8px 8px 0 0; }}
        .header h1 {{ margin: 0; font-size: 20px; }}
        .content {{ padding: 20px; }}
        .section {{ margin-bottom: 20px; }}
        .section h2 {{ font-size: 16px; color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 5px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #f8f9fa; color: #666; font-size: 12px; }}
        .stats {{ display: flex; justify-content: space-around; padding: 15px; background: #f8f9fa; border-radius: 8px; }}
        .stat-item {{ text-align: center; }}
        .stat-value {{ font-size: 24px; font-weight: bold; }}
        .footer {{ text-align: center; color: #999; font-size: 12px; padding: 15px; }}
    </style></head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📊 市场收盘总结 — {summary.get('date', '')}</h1>
            </div>
            <div class="content">
                <div class="section">
                    <h2>大盘指数</h2>
                    <table>
                        <tr><th>指数</th><th>点位</th><th>涨跌幅</th></tr>
                        {index_rows}
                    </table>
                </div>

                <div class="stats">
                    <div class="stat-item">
                        <div>📈 上涨</div>
                        <div class="stat-value" style="color:#e74c3c">{market.get('up_count', 0)}</div>
                    </div>
                    <div class="stat-item">
                        <div>📉 下跌</div>
                        <div class="stat-value" style="color:#27ae60">{market.get('down_count', 0)}</div>
                    </div>
                    <div class="stat-item">
                        <div>💰 成交额</div>
                        <div class="stat-value" style="font-size:16px">{market.get('total_amount_billion', 0)}亿</div>
                    </div>
                    <div class="stat-item">
                        <div>🔥 涨停/跌停</div>
                        <div class="stat-value" style="font-size:16px">{market.get('limit_up_count', 0)}/{market.get('limit_down_count', 0)}</div>
                    </div>
                </div>

                <div class="section">
                    <h2>自选股涨幅榜</h2>
                    <table>
                        <tr><th>名称</th><th>价格</th><th>涨跌幅</th></tr>
                        {stock_rows(top_gainers)}
                    </table>
                </div>

                <div class="section">
                    <h2>自选股跌幅榜</h2>
                    <table>
                        <tr><th>名称</th><th>价格</th><th>涨跌幅</th></tr>
                        {stock_rows(top_losers)}
                    </table>
                </div>

                <div class="section">
                    <h2>📰 重要新闻</h2>
                    <table>
                        {news_rows}
                    </table>
                </div>
            </div>
            <div class="footer">
                🚀 自动盯盘Agent | 生成时间: {datetime.now().strftime('%H:%M:%S')}
            </div>
        </div>
    </body>
    </html>
    """
    return html


def send_daily_summary_email(summary: dict) -> bool:
    """发送每日收盘总结邮件"""
    html = build_daily_summary_html(summary)
    subject = f"📊 市场收盘总结 - {summary.get('date', '')}"
    return send_email(subject, html)
