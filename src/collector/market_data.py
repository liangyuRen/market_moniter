"""行情数据采集 — 新浪主源 + akshare备用"""
import logging
import re
import time
from datetime import datetime
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

SINA_QUOTE_URL = "https://hq.sinajs.cn/list={codes}"
SINA_HEADERS = {"Referer": "https://finance.sina.com.cn"}
BATCH_SIZE = 300  # 新浪单次请求最大股票数

# 新浪行情字段位置
SINA_FIELDS = {
    "name": 0, "open": 1, "pre_close": 2, "price": 3,
    "high": 4, "low": 5, "bid": 6, "ask": 7,
    "volume": 8, "amount": 9,
    "date": 30, "time": 31,
}


def _to_sina_code(code: str, market: str) -> str:
    """转为新浪格式代码: sh600519 / sz000858"""
    c = code.strip()
    if c.startswith(("SH", "sh")):
        return f"sh{c[2:]}"
    if c.startswith(("SZ", "sz")):
        return f"sz{c[2:]}"
    m = market.strip().lower()
    if m in ("sh", "shanghai"):
        return f"sh{c}"
    return f"sz{c}"


def _parse_sina_line(line: str) -> Optional[dict]:
    """解析单条新浪行情数据"""
    if not line or "=" not in line:
        return None
    try:
        code_str = line.split("=")[0].strip().split("_str_")[-1]
        market = code_str[:2]  # sh or sz
        code = code_str[2:]
        data_str = line.split('"')[1]
        if not data_str or data_str == "":
            return None
        parts = data_str.split(",")
        if len(parts) < 32:
            return None

        price = float(parts[3])
        pre_close = float(parts[2])
        change_pct = round((price - pre_close) / pre_close * 100, 4) if pre_close != 0 else 0
        volume = float(parts[8]) if parts[8] else 0
        amount = float(parts[9]) if parts[9] else 0

        # 换手率：沪市在37, 深市在36-38不等
        turnover = 0.0
        if market == "sh" and len(parts) > 37:
            turnover = float(parts[37]) if parts[37] else 0.0
        elif market == "sz" and len(parts) > 36:
            turnover = float(parts[36]) if parts[36] else 0.0

        return {
            "code": code,
            "name": parts[0].strip(),
            "price": price,
            "change_pct": change_pct,
            "change_amount": round(price - pre_close, 4),
            "volume": volume,
            "amount": amount,
            "turnover": turnover,
            "high": float(parts[4]) if parts[4] else 0,
            "low": float(parts[5]) if parts[5] else 0,
            "open": float(parts[1]) if parts[1] else 0,
            "pre_close": pre_close,
            "volume_ratio": 1.0,  # 新浪没有量比
            "pe": 0.0,
            "total_market_cap": 0.0,
            "circ_market_cap": 0.0,
            "fetched_at": datetime.now().isoformat(),
        }
    except (ValueError, IndexError) as e:
        logger.debug(f"解析新浪行情异常: {e}")
        return None


def _fetch_sina_raw(codes: list[str]) -> str:
    """批量请求新浪行情原始数据"""
    batches = [codes[i:i + BATCH_SIZE] for i in range(0, len(codes), BATCH_SIZE)]
    results = []
    for batch in batches:
        try:
            url = SINA_QUOTE_URL.format(codes=",".join(batch))
            resp = requests.get(url, headers=SINA_HEADERS, timeout=10)
            resp.encoding = "gbk"
            results.append(resp.text)
            if len(batches) > 1:
                time.sleep(0.5)
        except Exception as e:
            logger.error(f"新浪行情请求失败: {e}")
    return "\n".join(results)


def fetch_watchlist_quotes(watchlist: list) -> dict[str, dict]:
    """
    获取自选股列表的实时行情（新浪源）
    返回 {code: {price, change_pct, volume, ...}}
    """
    if not watchlist:
        return {}

    sina_codes = []
    code_map = {}
    for item in watchlist:
        code = item["code"].strip()
        market = item.get("market", "SZ")
        s_code = _to_sina_code(code, market)
        sina_codes.append(s_code)
        code_map[s_code] = code

    raw = _fetch_sina_raw(sina_codes)
    if not raw:
        return {}

    quotes = {}
    for line in raw.strip().split("\n"):
        q = _parse_sina_line(line)
        if q is None:
            continue
        # 用原始code匹配（新浪返回code不带市场前缀）
        for s_code, orig_code in code_map.items():
            s_market = s_code[:2]
            s_num = s_code[2:]
            if q["code"] == s_num:
                quote_code = orig_code
                q["code"] = quote_code
                quotes[quote_code] = q
                break

    logger.info(f"新浪行情: 获取 {len(quotes)}/{len(watchlist)} 只自选股")
    return quotes


def fetch_index_spot(index_list: list) -> dict[str, dict]:
    """获取指数实时行情（新浪源）"""
    sina_codes = []
    for item in index_list:
        code = item["code"].strip()
        market = item.get("market", "SH")
        s = _to_sina_code(code, market)
        sina_codes.append(s)

    raw = _fetch_sina_raw(sina_codes)
    if not raw:
        return {}

    result = {}
    for line in raw.strip().split("\n"):
        q = _parse_sina_line(line)
        if q is None:
            continue
        for item in index_list:
            if q["code"] == item["code"].strip():
                q["code"] = item["code"].strip()
                result[item["code"].strip()] = q
                break

    return result


def fetch_stock_history(code: str, market: str = "SH", period: str = "daily", days: int = 250) -> pd.DataFrame:
    """获取个股历史K线数据"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_hist(symbol=code, period=period, adjust="qfq")
        if df is not None and not df.empty:
            return df.tail(days)
        return pd.DataFrame()
    except Exception as e:
        logger.debug(f"akshare获取{code}历史K线失败: {e}")

    # 新浪备用（日线）
    try:
        s_code = _to_sina_code(code, market)
        url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={s_code}&scale=240&ma=no&datalen={days}"
        resp = requests.get(url, headers=SINA_HEADERS, timeout=15)
        data = resp.json()
        if not data:
            return pd.DataFrame()
        records = []
        for d in data:
            records.append({
                "日期": d["day"],
                "开盘": float(d["open"]),
                "收盘": float(d["close"]),
                "最高": float(d["high"]),
                "最低": float(d["low"]),
                "成交量": float(d["volume"]),
            })
        return pd.DataFrame(records)
    except Exception as e:
        logger.error(f"新浪获取{code}历史K线失败: {e}")
        return pd.DataFrame()


def fetch_stock_fund_flow(code: str, market: str = "SH") -> dict:
    """获取个股资金流向"""
    import akshare as ak
    try:
        df = ak.stock_individual_fund_flow(stock=code, market=market.lower())
        if df is not None and not df.empty:
            latest = df.iloc[0]
            return {
                "date": str(latest.get("日期", "")),
                "main_net_inflow": float(latest.get("主力净流入-净额", 0) or 0),
                "main_net_inflow_pct": float(latest.get("主力净流入-净占比", 0) or 0),
                "super_large_net_inflow": float(latest.get("超大单净流入-净额", 0) or 0),
                "large_net_inflow": float(latest.get("大单净流入-净额", 0) or 0),
                "mid_net_inflow": float(latest.get("中单净流入-净额", 0) or 0),
                "small_net_inflow": float(latest.get("小单净流入-净额", 0) or 0),
            }
        return {}
    except Exception as e:
        logger.debug(f"获取{code}资金流向失败: {e}")
        return {}


def fetch_market_overview() -> dict:
    """获取市场总览 — 优先东方财富，失败则从新浪实时计算"""
    # 尝试东方财富
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        if df is not None and not df.empty:
            up = int((df["涨跌幅"] > 0).sum())
            down = int((df["涨跌幅"] < 0).sum())
            limit_up = int((df["涨跌幅"] >= 9.8).sum())
            limit_down = int((df["涨跌幅"] <= -9.8).sum())
            total_amount = df["成交额"].astype(float).sum() / 1e8
            return {
                "up_count": up, "down_count": down, "flat_count": len(df) - up - down,
                "limit_up_count": limit_up, "limit_down_count": limit_down,
                "total_amount_billion": round(total_amount, 2),
                "fetched_at": datetime.now().isoformat(),
            }
    except Exception:
        pass

    # 新浪备用：获取大盘指数 + 简要统计
    try:
        indices = fetch_index_spot([
            {"code": "000001", "market": "SH", "name": "上证"},
            {"code": "399001", "market": "SZ", "name": "深证"},
        ])
        return {
            "up_count": 0, "down_count": 0, "flat_count": 0,
            "limit_up_count": 0, "limit_down_count": 0,
            "total_amount_billion": 0,
            "indices": indices,
            "fetched_at": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"获取市场总览失败: {e}")
        return {}
