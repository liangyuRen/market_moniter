"""
全球市场数据采集 — 美股/日韩/港股/欧股主要指数
"""
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# 全球主要指数列表
GLOBAL_INDICES = [
    # 美股三大指数
    {"code": ".IXIC",   "name": "纳斯达克",   "region": "US"},
    {"code": ".SPX",    "name": "标普500",    "region": "US"},
    {"code": ".DJI",    "name": "道琼斯",     "region": "US"},
    # 日韩
    {"code": "N225",    "name": "日经225",    "region": "JP"},
    {"code": "KOSPI",   "name": "韩国KOSPI",  "region": "KR"},
    # 港股
    {"code": "HSI",     "name": "恒生指数",    "region": "HK"},
    {"code": "HSCEI",   "name": "国企指数",    "region": "HK"},
    # 欧洲
    {"code": "FTSE",    "name": "英国富时100", "region": "EU"},
    {"code": "DAX",     "name": "德国DAX",     "region": "EU"},
    # VIX恐慌指数 (Yahoo单独获取，不在akshare列表内)
    {"code": "^VIX",    "name": "VIX恐慌指数",  "region": "US"},
]

# 美股知名中概股（在港上市或美股的A股相关）
US_CHINA_STOCKS = [
    {"code": "BABA",  "name": "阿里巴巴"},
    {"code": "BIDU",  "name": "百度"},
    {"code": "JD",    "name": "京东"},
    {"code": "NIO",   "name": "蔚来"},
    {"code": "PDD",   "name": "拼多多"},
    {"code": "TSLA",  "name": "特斯拉"},
    {"code": "AAPL",  "name": "苹果"},
    {"code": "NVDA",  "name": "英伟达"},
]


_em_reachable = None


def fetch_global_indices() -> list[dict]:
    """获取全球主要指数行情 — akshare主源 + 新浪备用"""
    global _em_reachable
    import akshare as ak
    if _em_reachable is None:
        try:
            import requests as _r
            resp = _r.get("https://push2.eastmoney.com/api/qt/clist/get", timeout=3)
            _em_reachable = resp.status_code == 200
        except Exception:
            _em_reachable = False
    if _em_reachable is False:
        return _fetch_global_fallback()
    try:
        df = ak.index_global_spot_em()
        if df is None or df.empty:
            return _fetch_global_fallback()

        now = datetime.now().isoformat()
        result = []
        for _, row in df.iterrows():
            name = str(row.get("名称", ""))
            code = str(row.get("代码", ""))
            price = float(row.get("最新价", 0) or 0)
            pre_close = float(row.get("昨收", 0) or 0)
            change_pct = float(row.get("涨跌幅", 0) or 0)
            change_amount = float(row.get("涨跌额", 0) or 0)
            open_price = float(row.get("今开", 0) or 0)
            high = float(row.get("最高", 0) or 0)
            low = float(row.get("最低", 0) or 0)

            result.append({
                "code": code,
                "name": name,
                "region": _guess_region(name),
                "price": price,
                "change_pct": round(change_pct, 4),
                "change_amount": round(change_amount, 4),
                "pre_close": pre_close,
                "open": open_price,
                "high": high,
                "low": low,
                "fetched_at": now,
            })
        if result:
            logger.info(f"全球指数: 获取 {len(result)} 个")
            return result
    except Exception as e:
        logger.error(f"全球指数获取失败: {e}")
    return _fetch_global_fallback()


def _fetch_global_fallback() -> list[dict]:
    """备用方案：新浪接口(全球指数) + Yahoo Finance(KOSPI/VIX)"""
    import requests
    # 新浪全球指数（简单格式：name,price,change_amount,change_pct）
    sina_codes = {
        "int_dji":     ("道琼斯", "US"),
        "int_nasdaq":  ("纳斯达克", "US"),
        "int_sp500":   ("标普500", "US"),
        "int_hangseng":("恒生指数", "HK"),
        "int_hscei":   ("国企指数", "HK"),
        "int_nikkei":  ("日经225", "JP"),
    }
    now = datetime.now().isoformat()
    result = []
    try:
        url = "https://hq.sinajs.cn/list=" + ",".join(sina_codes.keys())
        resp = requests.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
        resp.encoding = "gbk"
        for line in resp.text.strip().split("\n"):
            if "=" not in line:
                continue
            code = line.split("=")[0].strip().replace("var hq_str_", "")
            name_info = sina_codes.get(code)
            if not name_info:
                continue
            name, region = name_info
            data = line.split('"')[1] if '"' in line else ""
            if not data:
                continue
            parts = data.split(",")
            if len(parts) < 4:
                continue
            price = float(parts[1]) if parts[1] else 0
            change_amount = float(parts[2]) if parts[2] else 0
            change_pct = float(parts[3]) if parts[3] else 0
            result.append({
                "code": code, "name": name, "region": region,
                "price": price, "change_pct": round(change_pct, 2),
                "change_amount": round(change_amount, 2),
                "pre_close": price - change_amount, "fetched_at": now,
            })
    except Exception as e:
        logger.error(f"新浪全球指数失败: {e}")

    # Yahoo Finance补充KOSPI/VIX
    yahoo_symbols = {"^KS11": ("韩国KOSPI", "KR"), "^VIX": ("VIX恐慌指数", "US")}
    for symbol, (name, region) in yahoo_symbols.items():
        try:
            yurl = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
            yresp = requests.get(yurl, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            ydata = yresp.json()
            meta = ydata["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice", 0)
            prev_close = meta.get("previousClose", price)
            chg = price - prev_close
            chg_pct = (chg / prev_close * 100) if prev_close else 0
            result.append({
                "code": symbol, "name": name, "region": region,
                "price": round(price, 2), "change_pct": round(chg_pct, 2),
                "change_amount": round(chg, 2), "pre_close": round(prev_close, 2),
                "fetched_at": now,
            })
        except Exception:
            continue

    return result


def fetch_us_futures() -> list[dict]:
    """获取美股期货（盘前参考）"""
    import requests
    futures = [
        ("ES", "标普500期货"),
        ("NQ", "纳斯达克期货"),
        ("YM", "道琼斯期货"),
    ]
    result = []
    now = datetime.now().isoformat()
    try:
        url = "https://hq.sinajs.cn/list=hf_ES,hf_NQ,hf_YM"
        resp = requests.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
        resp.encoding = "gbk"
        for line in resp.text.strip().split("\n"):
            if "=" not in line:
                continue
            parts = line.split('"')[1].split(",")
            if len(parts) < 3:
                continue
            code = line.split("=")[0].strip()
            name_map = {"hf_ES": "标普500期货", "hf_NQ": "纳斯达克期货", "hf_YM": "道琼斯期货"}
            result.append({
                "code": code,
                "name": name_map.get(code, code),
                "price": float(parts[1]) if parts[1] else 0,
                "change_pct": float(parts[3]) if len(parts) > 3 and parts[3] else 0,
                "fetched_at": now,
            })
    except Exception:
        pass
    return result


def fetch_global_market_report() -> dict:
    """生成全球市场简报（含美股/日韩/港股判断）"""
    indices = fetch_global_indices()
    report = {
        "us": {"indices": [], "summary": "无数据"},
        "jp_kr": {"indices": [], "summary": "无数据"},
        "hk": {"indices": [], "summary": "无数据"},
        "vix": {"price": 0, "change_pct": 0, "level": "unknown"},
        "fetched_at": datetime.now().isoformat(),
    }
    for idx in indices:
        name = idx.get("name", "")
        region = _guess_region(name)
        if "VIX" in name.upper():
            report["vix"] = {
                "price": idx.get("price", 0),
                "change_pct": idx.get("change_pct", 0),
                "level": _vix_level(idx.get("price", 0)),
            }
        elif region == "US":
            report["us"]["indices"].append(idx)
        elif region in ("JP", "KR"):
            report["jp_kr"]["indices"].append(idx)
        elif region == "HK":
            report["hk"]["indices"].append(idx)

    # 生成摘要
    report["us"]["summary"] = _region_summary(report["us"]["indices"])
    report["jp_kr"]["summary"] = _region_summary(report["jp_kr"]["indices"])
    report["hk"]["summary"] = _region_summary(report["hk"]["indices"])
    return report


def _guess_region(name: str) -> str:
    n = name.upper()
    if "KOSPI" in n or "韩国" in n:
        return "KR"
    if "日经" in n or "NIKKEI" in n:
        return "JP"
    if any(k in n for k in ["恒生", "国企", "HSI", "HSCEI"]):
        return "HK"
    # 美股: 必须精确匹配，排除澳大利亚/加拿大等
    us_names = ["纳斯达克", "NASDAQ", "标普500", "S&P 500", "SPX", "道琼斯", "DOW JONES",
                "VIX", "恐慌"]
    if any(k in n for k in us_names) and "澳大利亚" not in n and "加拿大" not in n:
        return "US"
    return "OTHER"


def _vix_level(price: float) -> str:
    if price <= 0:
        return "unknown"
    if price < 15:
        return "低波动(平静)"
    elif price < 20:
        return "正常"
    elif price < 25:
        return "中等恐慌"
    elif price < 35:
        return "高恐慌"
    return "极度恐慌"


def _region_summary(indices: list[dict]) -> str:
    if not indices:
        return "无数据"
    up = sum(1 for i in indices if i.get("change_pct", 0) > 0)
    down = len(indices) - up
    if up > down:
        return "普涨"
    elif down > up:
        return "普跌"
    return "分化"
