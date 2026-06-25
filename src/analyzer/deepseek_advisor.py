"""
DeepSeek AI 投资顾问 — 趋势预测 + 仓位建议 + 风险评估 + 情绪分析
"""
import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def _get_deepseek_config() -> dict:
    from src.config_loader import get_settings
    return get_settings().get("deepseek", {})


def _build_analysis_prompt(code: str, name: str, sector: str,
                           technical: dict, hist_summary: dict,
                           market_context: dict) -> str:
    """构建DeepSeek分析提示词"""
    price = technical.get("price", 0)
    rsi = technical.get("rsi14", 50)
    macd_hist = technical.get("macd_hist", 0)
    kdj_k = technical.get("kdj_k", 50)
    kdj_j = technical.get("kdj_j", 50)
    boll_pos = technical.get("boll_position", "N/A")
    vol_ratio = technical.get("volume_ratio", 1.0)
    mas = technical.get("mas", {})
    signals = technical.get("signals", [])

    mas_str = ", ".join(f"MA{k}={v:.2f}" for k, v in sorted(mas.items()))
    signals_str = ", ".join(signals) if signals else "无明显信号"

    chg_5d = hist_summary.get("change_5d", 0)
    chg_20d = hist_summary.get("change_20d", 0)
    vol_trend = hist_summary.get("volume_trend", "平稳")
    price_trend = hist_summary.get("price_trend", "震荡")

    prompt = f"""你是一位资深A股投资分析师，请对以下股票进行全面分析。

【股票信息】
代码: {code}
名称: {name}
行业板块: {sector}

【技术指标】
现价: ¥{price:.2f}
RSI(14): {rsi:.1f}
MACD柱: {macd_hist:.4f}
KDJ-K: {kdj_k:.1f} / KDJ-J: {kdj_j:.1f}
布林带位置: {boll_pos}
量比: {vol_ratio:.2f}
均线: {mas_str}
当前信号: {signals_str}

【近期走势】
5日涨跌: {chg_5d:+.2f}%
20日涨跌: {chg_20d:+.2f}%
价格趋势: {price_trend}
成交量趋势: {vol_trend}

【大盘环境】
市场情绪: {market_context.get('market_sentiment', 'neutral')}
板块热度: {market_context.get('sector_heat', 'normal')}
北向资金: {market_context.get('north_bound', 'N/A')}

请严格按以下JSON格式回复（不要添加任何其他文字）:
{{"trend":"bullish|bearish|neutral","confidence":0-100,"position_advice":"加仓|减仓|持有|观望","position_pct":-100到100,"support_level":价格,"resistance_level":价格,"risk_level":"low|medium|high|critical","risk_factors":["因素1","因素2"],"bullish_factors":["利好1","利好2"],"summary":"一句话总结(50字内)","target_price":价格,"stop_loss":价格}}"""

    return prompt


def call_deepseek(prompt: str, api_key: str = None, base_url: str = None,
                  model: str = None) -> Optional[dict]:
    """调用DeepSeek API（OpenAI兼容接口）"""
    cfg = _get_deepseek_config()
    api_key = api_key or cfg.get("api_key", "")
    base_url = base_url or cfg.get("base_url", "https://api.deepseek.com/v1")
    model = model or cfg.get("model", "deepseek-chat")

    if not api_key or api_key == "your_deepseek_api_key":
        logger.warning("DeepSeek API key未配置，使用本地分析模式")
        return None

    try:
        import requests
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "你是一位专业A股分析师，回复严格使用JSON格式，不要添加markdown代码块。"},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": cfg.get("max_tokens", 2048),
                "temperature": cfg.get("temperature", 0.3),
            },
            timeout=30,
        )
        if resp.status_code != 200:
            logger.error(f"DeepSeek API错误: {resp.status_code} {resp.text[:200]}")
            return None
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        # 提取JSON（处理可能包裹的markdown代码块）
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("\n```", 1)[0] if "```" in content[3:] else content[3:]
        return json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"DeepSeek返回格式错误: {e}, 原始内容: {content[:200]}")
        return None
    except Exception as e:
        logger.error(f"DeepSeek调用失败: {e}")
        return None


def local_fallback_analysis(code: str, name: str, sector: str,
                            technical: dict, hist_summary: dict,
                            market_context: dict) -> dict:
    """本地规则引擎分析（DeepSeek不可用时的回退方案）"""
    price = technical.get("price", 0)
    rsi = technical.get("rsi14", 50)
    macd_hist = technical.get("macd_hist", 0)
    kdj_j = technical.get("kdj_j", 50)
    boll_pos = technical.get("boll_position", "")
    vol_ratio = technical.get("volume_ratio", 1.0)
    signals = technical.get("signals", [])
    mas = technical.get("mas", {})
    chg_20d = hist_summary.get("change_20d", 0)

    # ---- 趋势判断 ----
    trend_score = 0
    if rsi < 30:
        trend_score += 20
    elif rsi > 70:
        trend_score -= 20
    if macd_hist > 0:
        trend_score += 15
    else:
        trend_score -= 15
    if kdj_j < 0:
        trend_score += 15
    elif kdj_j > 100:
        trend_score -= 15
    if boll_pos in ("below_lower",):
        trend_score += 15
    elif boll_pos in ("above_upper",):
        trend_score -= 15
    if "macd_golden_cross" in signals:
        trend_score += 25
    if "macd_dead_cross" in signals:
        trend_score -= 25
    if "rsi_oversold" in signals:
        trend_score += 20
    if "rsi_overbought" in signals:
        trend_score -= 20
    if chg_20d > 10:
        trend_score -= 10
    elif chg_20d < -10:
        trend_score += 10

    if trend_score > 30:
        trend = "bullish"
        confidence = min(90, 50 + trend_score)
    elif trend_score < -30:
        trend = "bearish"
        confidence = min(90, 50 - trend_score)
    else:
        trend = "neutral"
        confidence = 50 - abs(trend_score) // 2

    # ---- 仓位建议 ----
    if trend == "bullish" and confidence > 70:
        position_advice = "加仓"
        position_pct = min(80, confidence - 20)
    elif trend == "bearish" and confidence > 70:
        position_advice = "减仓"
        position_pct = -min(80, confidence - 20)
    elif trend == "bullish":
        position_advice = "持有"
        position_pct = 20
    elif trend == "bearish":
        position_advice = "观望"
        position_pct = -20
    else:
        position_advice = "持有"
        position_pct = 0

    # ---- 支撑/阻力位 ----
    ma20 = mas.get("ma20", price)
    ma60 = mas.get("ma60", price)
    ma120 = mas.get("ma120", price)
    support_level = min(ma20, ma60, ma120) if min(ma20, ma60, ma120) < price else price * 0.95
    resistance_level = max(ma20, ma60, ma120) if max(ma20, ma60, ma120) > price else price * 1.05
    stop_loss = round(price * 0.93, 2)
    target_price = round(price * 1.08, 2) if trend == "bullish" else round(price * 1.03, 2)

    # ---- 风险因素 ----
    risk_factors = []
    if rsi > 75:
        risk_factors.append(f"RSI超买({rsi:.1f})，短线回调风险")
    if rsi < 25:
        risk_factors.append(f"RSI超卖({rsi:.1f})，下跌趋势可能延续")
    if vol_ratio > 2.5:
        risk_factors.append("成交量异常放大，注意资金动向")
    if vol_ratio < 0.5:
        risk_factors.append("交投清淡，流动性风险")
    if abs(chg_20d) > 25:
        risk_factors.append(f"近20日波动{chg_20d:+.1f}%，波动风险较大")
    if boll_pos == "above_upper":
        risk_factors.append("价格触及布林上轨，短期承压")
    elif boll_pos == "below_lower":
        risk_factors.append("价格跌破布林下轨，趋势偏弱")

    bullish_factors = []
    if macd_hist > 0:
        bullish_factors.append("MACD柱状图为正，多头占优")
    if rsi < 40:
        bullish_factors.append("RSI偏低，存在超跌反弹机会")
    if "macd_golden_cross" in signals:
        bullish_factors.append("MACD金叉信号，趋势向好")
    if chg_20d < -15:
        bullish_factors.append("短期超跌，技术性反弹可期")

    risk_level = "low" if len(risk_factors) == 0 else \
                 "medium" if len(risk_factors) <= 2 else \
                 "high" if len(risk_factors) <= 4 else "critical"

    return {
        "trend": trend,
        "confidence": confidence,
        "position_advice": position_advice,
        "position_pct": position_pct,
        "support_level": round(support_level, 2),
        "resistance_level": round(resistance_level, 2),
        "risk_level": risk_level,
        "risk_factors": risk_factors,
        "bullish_factors": bullish_factors,
        "summary": f"{name}: {'看多' if trend == 'bullish' else '看空' if trend == 'bearish' else '震荡'}，建议{position_advice}（置信度{confidence}%）",
        "target_price": target_price,
        "stop_loss": stop_loss,
        "source": "local",
    }


def analyze_stock(code: str, name: str = "", sector: str = "综合") -> dict:
    """
    综合分析一只股票：优先使用DeepSeek AI，API不可用时回退到本地规则引擎
    """
    from src.collector.market_data import fetch_stock_history
    from src.analyzer.technical import calc_technical_summary, calc_sentiment_line

    market = "SH" if code.startswith(("6", "688")) else "SZ"
    cfg = _get_deepseek_config()

    # 获取历史数据
    hist = fetch_stock_history(code, market, days=250)
    if hist.empty or len(hist) < 20:
        return {"error": "无法获取足够历史数据", "code": code}

    # 技术指标
    technical = calc_technical_summary(hist)
    if not technical:
        return {"error": "技术指标计算失败", "code": code}

    # 历史走势摘要
    close = hist["收盘"].astype(float)
    volume = hist["成交量"].astype(float)
    hist_summary = {
        "change_5d": round((close.iloc[-1] / close.iloc[-6] - 1) * 100, 2) if len(close) >= 6 else 0,
        "change_20d": round((close.iloc[-1] / close.iloc[-21] - 1) * 100, 2) if len(close) >= 21 else 0,
        "volume_trend": "放量" if volume.iloc[-5:].mean() > volume.iloc[-20:].mean() * 1.2 else (
            "缩量" if volume.iloc[-5:].mean() < volume.iloc[-20:].mean() * 0.8 else "平稳"),
        "price_trend": "上涨" if close.iloc[-1] > close.iloc[-20:].mean() else (
            "下跌" if close.iloc[-1] < close.iloc[-20:].mean() else "震荡"),
    }

    # 板块和市场上下文
    market_context = _get_market_context(code, sector)

    # 情绪线
    sentiment_data = calc_sentiment_line(hist)

    # 尝试DeepSeek
    features = cfg.get("features", {})
    ai_result = None
    if cfg.get("enabled", True) and features.get("trend_prediction", True):
        prompt = _build_analysis_prompt(code, name or code, sector, technical, hist_summary, market_context)
        ai_result = call_deepseek(prompt)

    # 回退
    if ai_result is None:
        ai_result = local_fallback_analysis(code, name or code, sector, technical, hist_summary, market_context)

    ai_result["code"] = code
    ai_result["name"] = name or code
    ai_result["sector"] = sector
    ai_result["price"] = technical.get("price", 0)
    ai_result["technical"] = technical
    ai_result["sentiment_line"] = sentiment_data
    ai_result["market_context"] = market_context
    ai_result["analyzed_at"] = datetime.now().isoformat()

    return ai_result


def _get_market_context(code: str, sector: str) -> dict:
    """获取股票所在的市场上下文"""
    from src.storage.state import state
    from src.storage.database import get_conn

    ctx = {"market_sentiment": "neutral", "sector_heat": "normal", "north_bound": "N/A"}

    # 市场状态
    session = state.get_market_session()
    ctx["market_session"] = session

    # 从数据库获取最新情绪
    try:
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM market_sentiment ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
        if row:
            d = dict(row)
            ctx["market_sentiment"] = d.get("overall", "neutral")
        # 北向资金
        row2 = conn.execute(
            "SELECT net_inflow FROM north_bound_flow ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
        if row2:
            nb = row2[0] or 0
            ctx["north_bound"] = f"净{'流入' if nb > 0 else '流出'}{abs(nb)/1e8:.1f}亿"
    except Exception:
        pass

    # 板块热度（从缓存的板块新闻数量推断）
    sector_news = getattr(state, '_sector_news', None)
    if sector_news:
        by_sector = sector_news.get("by_sector", {})
        count = by_sector.get(sector, 0)
        if count >= 10:
            ctx["sector_heat"] = "hot"
        elif count >= 5:
            ctx["sector_heat"] = "warm"
        elif count == 0:
            ctx["sector_heat"] = "cold"

    return ctx


def batch_analyze(codes: list[str], names: dict = None, sectors: dict = None) -> list[dict]:
    """批量分析多只股票"""
    results = []
    for code in codes:
        try:
            name = (names or {}).get(code, code)
            sector = (sectors or {}).get(code, "综合")
            result = analyze_stock(code, name, sector)
            results.append(result)
        except Exception as e:
            logger.error(f"分析{code}失败: {e}")
            results.append({"code": code, "error": str(e)})
    return results
