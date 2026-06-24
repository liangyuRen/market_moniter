"""
行情数据采集 — 东方财富主源(量比/PE/PB等全字段) + akshare备用
"""
import logging
import time
from datetime import datetime
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

SINA_QUOTE_URL = "https://hq.sinajs.cn/list={codes}"
SINA_HEADERS = {"Referer": "https://finance.sina.com.cn"}
BATCH_SIZE = 300
SINA_FIELDS = {
    "name": 0, "open": 1, "pre_close": 2, "price": 3,
    "high": 4, "low": 5, "bid": 6, "ask": 7,
    "volume": 8, "amount": 9, "date": 30, "time": 31,
}


def _to_sina_code(code: str, market: str) -> str:
    c = code.strip()
    if c.startswith(("SH", "sh")):
        return f"sh{c[2:]}"
    if c.startswith(("SZ", "sz")):
        return f"sz{c[2:]}"
    m = market.strip().lower()
    if m in ("sh", "shanghai"):
        return f"sh{c}"
    return f"sz{c}"


def _fetch_sina_raw(codes: list[str]) -> str:
    batches = [codes[i:i + BATCH_SIZE] for i in range(0, len(codes), BATCH_SIZE)]
    results = []
    for batch in batches:
        try:
            url = SINA_QUOTE_URL.format(codes=",".join(batch))
            resp = requests.get(url, headers=SINA_HEADERS, timeout=10)
            resp.encoding = "gbk"
            results.append(resp.text)
            if len(batches) > 1:
                time.sleep(0.3)
        except Exception as e:
            logger.error(f"新浪行情请求失败: {e}")
    return "\n".join(results)


def _parse_sina_line(line: str) -> Optional[dict]:
    if not line or "=" not in line:
        return None
    try:
        code_str = line.split("=")[0].strip().split("_str_")[-1]
        market = code_str[:2]
        code = code_str[2:]
        data_str = line.split('"')[1]
        if not data_str:
            return None
        parts = data_str.split(",")
        if len(parts) < 32:
            return None
        price = float(parts[3])
        pre_close = float(parts[2])
        change_pct = round((price - pre_close) / pre_close * 100, 4) if pre_close != 0 else 0
        volume = float(parts[8]) if parts[8] else 0
        amount = float(parts[9]) if parts[9] else 0
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
            "volume_ratio": 1.0,
            "pe": 0.0, "pb": 0.0,
            "total_market_cap": 0.0,
            "circ_market_cap": 0.0,
            "fetched_at": datetime.now().isoformat(),
        }
    except (ValueError, IndexError):
        return None


# ====== 东方财富源：获取量比/PE/PB/总市值等全字段 ======

_em_reachable = None  # 缓存东方财富是否可达


def _fetch_eastmoney_spot() -> dict[str, dict]:
    """从东方财富获取全A股实时行情（含量比/PE/PB/总市值/流通市值）"""
    global _em_reachable
    if _em_reachable is False:
        return {}
    import akshare as ak
    # 快速探测
    if _em_reachable is None:
        try:
            import requests as _r
            resp = _r.get("https://82.push2.eastmoney.com/api/qt/clist/get", timeout=3,
                          params={"pn": "1", "pz": "1", "np": "1", "fltt": "2",
                                  "fs": "m:0+t:6", "fields": "f12"})
            _em_reachable = resp.status_code == 200
        except Exception:
            _em_reachable = False
            logger.info("东方财富API不可达，将使用新浪+腾讯源")
            return {}
    try:
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            return {}
        em = {}
        for _, row in df.iterrows():
            code = str(row.get("代码", ""))
            name = str(row.get("名称", ""))
            price = float(row.get("最新价", 0) or 0)
            pre_close = float(row.get("昨收", 0) or 0)
            change_pct = float(row.get("涨跌幅", 0) or 0)
            change_amount = float(row.get("涨跌额", 0) or 0)
            volume_hand = float(row.get("成交量", 0) or 0)
            amount_val = float(row.get("成交额", 0) or 0)
            turnover = float(row.get("换手率", 0) or 0)
            high = float(row.get("最高", 0) or 0)
            low = float(row.get("最低", 0) or 0)
            open_price = float(row.get("今开", 0) or 0)
            vol_ratio = float(row.get("量比", 0) or 0)
            pe = float(row.get("市盈率-动态", 0) or 0)
            pb = float(row.get("市净率", 0) or 0)
            total_mv = float(row.get("总市值", 0) or 0)
            circ_mv = float(row.get("流通市值", 0) or 0)
            em[code] = {
                "code": code,
                "name": name,
                "price": price,
                "change_pct": round(change_pct, 4) if price > 0 else change_pct,
                "change_amount": round(change_amount, 4),
                "volume": volume_hand,
                "amount": amount_val,
                "turnover": turnover,
                "high": high,
                "low": low,
                "open": open_price,
                "pre_close": pre_close,
                "volume_ratio": round(vol_ratio, 2) if vol_ratio > 0 else 1.0,
                "pe": round(pe, 2),
                "pb": round(pb, 2),
                "total_market_cap": total_mv,
                "circ_market_cap": circ_mv,
                "fetched_at": datetime.now().isoformat(),
            }
        return em
    except Exception as e:
        logger.warning(f"东方财富行情获取失败(将用新浪+历史量比): {e}")
        return {}


def _calc_volume_ratios(quotes: dict[str, dict]) -> dict[str, dict]:
    """用历史数据计算量比 = 今日成交量 / 过去5日均量 (并行拉取)"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _calc_one(code, q):
        market = "SH" if code.startswith(("6", "688")) else "SZ"
        try:
            hist = fetch_stock_history(code, market, days=10)
            if hist.empty or len(hist) < 5:
                return code, None
            vol_series = hist["成交量"].astype(float)
            today_vol = q.get("volume", 0)
            if today_vol > 0 and len(vol_series) >= 5:
                avg_5d = vol_series.iloc[-6:-1].mean()
                if avg_5d > 0:
                    return code, round(today_vol / avg_5d, 2)
        except Exception:
            pass
        return code, None

    items = list(quotes.items())
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_calc_one, code, q): code for code, q in items}
        for future in as_completed(futures):
            code, ratio = future.result()
            if ratio is not None:
                quotes[code]["volume_ratio"] = ratio
    return quotes


def fetch_watchlist_quotes(watchlist: list) -> dict[str, dict]:
    """
    获取自选股实时行情 — 东方财富主源(含量比/PE/PB) + 新浪备用 + 历史数据计算量比
    """
    if not watchlist:
        return {}
    target_codes = {item["code"].strip() for item in watchlist}

    # 主源: 东方财富（有量比/PE/PB/市值等全字段）
    em_data = _fetch_eastmoney_spot()
    quotes = {}
    if em_data:
        for code in target_codes:
            if code in em_data:
                quotes[code] = em_data[code]
        if quotes:
            logger.info(f"东方财富行情: 获取 {len(quotes)}/{len(watchlist)} 只自选股")
            return quotes

    # 备用: 新浪 + 历史数据计算量比
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
    for line in raw.strip().split("\n"):
        q = _parse_sina_line(line)
        if q is None:
            continue
        for s_code, orig_code in code_map.items():
            s_num = s_code[2:]
            if q["code"] == s_num:
                quotes[orig_code] = q
                break
    logger.info(f"新浪行情(备用): 获取 {len(quotes)}/{len(watchlist)} 只自选股")

    # 腾讯财经补充量比/PE/PB/市值（1次HTTP请求覆盖所有股票）
    if quotes:
        quotes = _enrich_tencent_data(quotes)
        # 腾讯失败时用历史数据兜底计算量比
        any_no_vol = any(q.get("volume_ratio", 1.0) == 1.0 for q in quotes.values())
        if any_no_vol:
            quotes = _calc_volume_ratios(quotes)
    return quotes


def _enrich_tencent_data(quotes: dict[str, dict]) -> dict[str, dict]:
    """从腾讯财经接口补充量比/PE/PB/市值数据（新浪不提供这些字段）"""
    import requests as req
    t_codes = []
    code_map = {}
    for code in quotes:
        market = "sh" if code.startswith(("6", "688")) else "sz"
        t_code = f"{market}{code}"
        t_codes.append(t_code)
        code_map[t_code] = code
    if not t_codes:
        return quotes
    try:
        url = "http://qt.gtimg.cn/q=" + ",".join(t_codes)
        resp = req.get(url, timeout=10)
        resp.encoding = "gbk"
        for line in resp.text.strip().split("\n"):
            if "=" not in line or "~" not in line:
                continue
            data = line.split('"')[1] if '"' in line else ""
            if not data:
                continue
            parts = data.split("~")
            if len(parts) < 50:
                continue
            t_code = line.split("=")[0].replace("v_", "").strip()
            code = code_map.get(t_code)
            if not code or code not in quotes:
                continue
            try:
                # 字段索引: 39=PE, 46=PB, 44=流通市值(亿), 45=总市值(亿), 49=量比
                pe = float(parts[39]) if parts[39] else 0.0
                pb = float(parts[46]) if parts[46] else 0.0
                circ_mv = float(parts[44]) if parts[44] else 0.0
                total_mv = float(parts[45]) if parts[45] else 0.0
                vol_ratio = float(parts[49]) if parts[49] else 0.0
                if pe > 0:
                    quotes[code]["pe"] = round(pe, 2)
                if pb > 0:
                    quotes[code]["pb"] = round(pb, 2)
                if circ_mv > 0:
                    quotes[code]["circ_market_cap"] = circ_mv * 1e8  # 亿元转元
                if total_mv > 0:
                    quotes[code]["total_market_cap"] = total_mv * 1e8
                if vol_ratio > 0:
                    quotes[code]["volume_ratio"] = round(vol_ratio, 2)
            except (ValueError, IndexError):
                continue
        logger.debug(f"腾讯数据补充: {len(quotes)}只")
    except Exception as e:
        logger.debug(f"腾讯数据补充失败: {e}")
    return quotes


def fetch_index_spot(index_list: list) -> dict[str, dict]:
    """获取指数实时行情 — 东方财富主源 + 新浪备用"""
    import akshare as ak
    result = {}
    target_codes = {item["code"].strip() for item in index_list}
    # 主源: 东方财富指数行情
    try:
        df = ak.stock_zh_index_spot_em()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                code = str(row.get("代码", ""))
                if code not in target_codes:
                    continue
                price = float(row.get("最新价", 0) or 0)
                pre_close = float(row.get("昨收", 0) or 0)
                change_pct = float(row.get("涨跌幅", 0) or 0)
                volume = float(row.get("成交量", 0) or 0)
                amount = float(row.get("成交额", 0) or 0)
                result[code] = {
                    "code": code,
                    "name": str(row.get("名称", "")),
                    "price": price,
                    "change_pct": round(change_pct, 4),
                    "change_amount": round(price - pre_close, 4),
                    "pre_close": pre_close,
                    "volume": volume,
                    "amount": amount,
                    "high": float(row.get("最高", 0) or 0),
                    "low": float(row.get("最低", 0) or 0),
                    "open": float(row.get("今开", 0) or 0),
                    "volume_ratio": 1.0,
                    "pe": 0.0, "pb": 0.0,
                    "turnover": 0.0,
                    "total_market_cap": 0.0,
                    "circ_market_cap": 0.0,
                    "fetched_at": datetime.now().isoformat(),
                }
            if result:
                return result
    except Exception as e:
        logger.debug(f"东方财富指数获取失败: {e}")

    # 新浪备用
    sina_codes = []
    for item in index_list:
        code = item["code"].strip()
        market = item.get("market", "SH")
        sina_codes.append(_to_sina_code(code, market))
    raw = _fetch_sina_raw(sina_codes)
    if raw:
        for line in raw.strip().split("\n"):
            q = _parse_sina_line(line)
            if q is None:
                continue
            for item in index_list:
                if q["code"] == item["code"].strip():
                    result[item["code"].strip()] = q
                    break
    return result


def fetch_stock_history(code: str, market: str = "SH", period: str = "daily", days: int = 250) -> pd.DataFrame:
    try:
        import akshare as ak
        df = ak.stock_zh_a_hist(symbol=code, period=period, adjust="qfq")
        if df is not None and not df.empty:
            df = df.tail(days).copy()
            if "日期" in df.columns:
                df["日期"] = pd.to_datetime(df["日期"])
                df = df.set_index("日期")
            return df
        return pd.DataFrame()
    except Exception:
        pass
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
                "日期": d["day"], "开盘": float(d["open"]), "收盘": float(d["close"]),
                "最高": float(d["high"]), "最低": float(d["low"]), "成交量": float(d["volume"]),
            })
        df = pd.DataFrame(records)
        if not df.empty and "日期" in df.columns:
            df["日期"] = pd.to_datetime(df["日期"])
            df = df.set_index("日期")
        return df
    except Exception as e:
        logger.error(f"获取{code}历史K线失败: {e}")
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
    except Exception:
        return {}


def fetch_fund_flow_batch(codes: list[str]) -> dict[str, dict]:
    """批量获取资金流向（按股票逐个拉取，内置延迟防限流）"""
    flows = {}
    for code in codes:
        try:
            flow = fetch_stock_fund_flow(code, "SH" if code.startswith(("6", "688")) else "SZ")
            if flow:
                flows[code] = flow
            time.sleep(0.5)  # 防限流
        except Exception:
            continue
    logger.info(f"资金流向: 获取 {len(flows)}/{len(codes)} 只")
    return flows


def fetch_market_overview() -> dict:
    """获取全市场总览 — 东方财富源"""
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
                "up_count": up, "down_count": down,
                "flat_count": len(df) - up - down,
                "limit_up_count": limit_up, "limit_down_count": limit_down,
                "total_amount_billion": round(total_amount, 2),
                "fetched_at": datetime.now().isoformat(),
            }
    except Exception:
        pass
    try:
        indices = fetch_index_spot([
            {"code": "000001", "market": "SH", "name": "上证"},
            {"code": "399001", "market": "SZ", "name": "深证"},
        ])
        return {
            "up_count": 0, "down_count": 0, "flat_count": 0,
            "limit_up_count": 0, "limit_down_count": 0,
            "total_amount_billion": 0,
            "indices": indices, "fetched_at": datetime.now().isoformat(),
        }
    except Exception:
        return {}


def fetch_north_bound_flow() -> dict:
    """获取北向资金流向（沪深港通）"""
    import akshare as ak
    try:
        df = ak.stock_hsgt_hist_em(symbol="北向资金")
        if df is not None and not df.empty:
            latest = df.iloc[0]
            return {
                "date": str(latest.get("日期", "")),
                "net_inflow": float(latest.get("当日成交净买额", 0) or 0),
                "buy_amount": float(latest.get("买入成交额", 0) or 0),
                "sell_amount": float(latest.get("卖出成交额", 0) or 0),
            }
    except Exception:
        pass
    return {}
