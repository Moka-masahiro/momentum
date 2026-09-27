"""1銘柄のテクニカル整理（ルールベース）。

紹介動画のアプリはここを「AI解析」としてLLMに書かせているが、このアプリでは
**決まったルールで機械的に**出す。

- 同じデータなら同じ結果になる（あとから検証できる）
- APIキーも費用も要らない
- 文章のもっともらしさと、中身の確かさが混ざらない

出すもの: 時間軸の流れ（月足・週足・日足の向き）／背景（52週レンジ内の位置・出来高・
移動平均からの乖離）／局面／節目（戻り高値・押し安値・移動平均）／警戒メモ。
売買の推奨ではなく、チャートを読むときに見る場所を揃えるためのもの。
"""
import math

import numpy as np
import pandas as pd

# 移動平均の傾きを「横ばい」とみなす幅（ノイズで上下判定がぱたぱた変わらないように）
_FLAT = {"daily": 0.003, "weekly": 0.01, "monthly": 0.02}
PIVOT_K = 5            # 前後5本の中で一番高い（安い）足を節目とみなす
PIVOT_LOOKBACK = 120   # 節目を探す期間（営業日）


def _trend(close: pd.Series, ma: pd.Series, slope_lag: int, flat: float) -> dict | None:
    ma = ma.dropna()
    if len(ma) <= slope_lag:
        return None
    last, m, m_prev = float(close.iloc[-1]), float(ma.iloc[-1]), float(ma.iloc[-1 - slope_lag])
    slope = m / m_prev - 1
    if last > m and slope > flat:
        label = "上昇"
    elif last < m and slope < -flat:
        label = "下降"
    else:
        label = "レンジ"
    return {"label": label, "ma": round(m, 2), "slope_pct": round(slope * 100, 2),
            "above": last > m}


def timeframes(c: pd.Series) -> dict:
    """月足・週足・日足の向き。

    日足: 25日線の上下と、25日線の5日間の傾き
    週足: 13週線の上下と、13週線の4週間の傾き
    月足: 6か月線の上下と、6か月線の2か月間の傾き（1年分の日足から作るので本数は少ない）
    """
    c = c.dropna()
    out = {"daily": _trend(c, c.rolling(25).mean(), 5, _FLAT["daily"])}
    cw = c.resample("W-FRI").last().dropna()
    out["weekly"] = _trend(cw, cw.rolling(13).mean(), 4, _FLAT["weekly"])
    cm = c.resample("ME").last().dropna()
    out["monthly"] = _trend(cm, cm.rolling(6).mean(), 2, _FLAT["monthly"])
    return out


def pivots(h: pd.Series, l: pd.Series, k: int = PIVOT_K, lookback: int = PIVOT_LOOKBACK):
    """前後 k 本の中で最も高い（安い）足を、戻り高値（押し安値）として拾う。"""
    h = h.dropna().iloc[-lookback:]
    l = l.dropna().iloc[-lookback:]
    highs, lows = [], []
    hv, lv = h.to_numpy(), l.to_numpy()
    for i in range(k, len(hv) - k):
        if hv[i] == hv[i - k:i + k + 1].max():
            highs.append((h.index[i], float(hv[i])))
    for i in range(k, len(lv) - k):
        if lv[i] == lv[i - k:i + k + 1].min():
            lows.append((l.index[i], float(lv[i])))
    return highs, lows


def build(o: pd.Series, h: pd.Series, l: pd.Series, c: pd.Series, v: pd.Series,
          metrics: dict) -> dict:
    """1銘柄のテクニカル整理。metrics は engine 側で計算済みの現在値。"""
    c_valid = c.dropna()
    if len(c_valid) < 30:
        return {"available": False, "reason": "日足が30営業日に満たないため整理できません"}
    close = float(c_valid.iloc[-1])
    cf = c.ffill()
    tf = timeframes(c_valid)

    ma25 = float(cf.rolling(25).mean().iloc[-1]) if len(c_valid) >= 25 else None
    ma75 = float(cf.rolling(75).mean().iloc[-1]) if len(c_valid) >= 75 else None
    pc = cf.shift(1)
    tr = np.maximum(h - l, np.maximum((h - pc).abs(), (l - pc).abs()))
    atr = float(tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().iloc[-1])

    window = min(250, len(c_valid))
    hi52 = float(h.iloc[-window:].max())
    lo52 = float(l.iloc[-window:].min())
    position = (close - lo52) / (hi52 - lo52) * 100 if hi52 > lo52 else None

    vol = v.fillna(0.0)
    v5 = float(vol.iloc[-5:].mean())
    v60 = float(vol.iloc[-60:].mean()) if len(vol) >= 20 else None
    vol_ratio = v5 / v60 if v60 else None
    vol_state = _vol_state(vol_ratio)

    dev25 = (close / ma25 - 1) * 100 if ma25 else None
    dev75 = (close / ma75 - 1) * 100 if ma75 else None

    highs, lows = pivots(h, l)
    res = sorted(p for _, p in highs if p > close * 1.005)
    sup = sorted((p for _, p in lows if p < close * 0.995), reverse=True)
    resistance = res[0] if res else None
    support = sup[0] if sup else None
    upside = (resistance / close - 1) * 100 if resistance else None
    downside = (support / close - 1) * 100 if support else None
    rr = (upside / abs(downside)) if upside is not None and downside else None

    phase = _phase(tf, metrics, dev25, ma25, close)
    alerts = _alerts(metrics, dev25, ma75, close, vol_ratio)

    levels = []
    if resistance:
        levels.append({"key": "resistance", "label": "戻り高値", "price": round(resistance, 2),
                       "note": "直近で上げが止まった水準。終値で超えると上値が軽くなりやすい"})
    if support:
        levels.append({"key": "support", "label": "押し安値", "price": round(support, 2),
                       "note": "直近で下げが止まった水準。終値で割り込むと上昇の形が崩れる"})
    if ma25:
        levels.append({"key": "ma25", "label": "25日線", "price": round(ma25, 2),
                       "note": "約1か月の平均コスト。短期の上昇トレンドはこの上で推移する"})
    if ma75:
        levels.append({"key": "ma75", "label": "75日線", "price": round(ma75, 2),
                       "note": "約3か月の平均コスト。中期トレンドの分かれ目"})
    levels.append({"key": "high52", "label": f"{'52週' if window >= 240 else f'{window}日'}高値",
                   "price": round(hi52, 2), "note": "期間中の最高値"})

    return {
        "available": True,
        "timeframes": tf,
        "alignment": _alignment(tf),
        "phase": phase,
        "background": {
            "position": None if position is None else round(position, 1),
            "position_window": window,
            "high": round(hi52, 2), "low": round(lo52, 2),
            "vol_ratio": None if vol_ratio is None else round(vol_ratio, 2),
            "vol_state": vol_state,
            "dev25": None if dev25 is None else round(dev25, 1),
            "dev75": None if dev75 is None else round(dev75, 1),
            "atr": round(atr, 2),
            "atr_pct": round(atr / close * 100, 2),
        },
        "levels": levels,
        "range": {
            "resistance": None if resistance is None else round(resistance, 2),
            "support": None if support is None else round(support, 2),
            "upside_pct": None if upside is None else round(upside, 1),
            "downside_pct": None if downside is None else round(downside, 1),
            "ratio": None if rr is None else round(rr, 2),
        },
        "alerts": alerts,
        "conclusion": _conclusion(tf, phase, resistance, support, metrics),
    }


def _vol_state(r: float | None) -> str | None:
    if r is None:
        return None
    if r >= 2.0:
        return "急増"
    if r >= 1.3:
        return "増加"
    if r >= 0.8:
        return "平常"
    return "減少"


def _label(tf: dict, key: str) -> str | None:
    t = tf.get(key)
    return t["label"] if t else None


def _alignment(tf: dict) -> str:
    labels = [_label(tf, k) for k in ("monthly", "weekly", "daily")]
    known = [x for x in labels if x]
    if len(known) < 2:
        return "判定に必要な本数が足りません"
    if all(x == "上昇" for x in known):
        return "すべての時間軸が上向きで揃っている"
    if all(x == "下降" for x in known):
        return "すべての時間軸が下向きで揃っている"
    if labels[1] == "上昇" and labels[2] != "上昇":
        return "上位足は上向き、日足は一服"
    if labels[1] == "下降" and labels[2] == "上昇":
        return "上位足は下向き、日足だけ戻している"
    return "時間軸ごとに向きがばらばら"


def _phase(tf, m, dev25, ma25, close) -> dict:
    d, w = _label(tf, "daily"), _label(tf, "weekly")
    rsi = m.get("rsi")
    if (rsi is not None and rsi >= 75) or (dev25 is not None and dev25 >= 20):
        return {"label": "過熱", "text": "短期間で上げすぎた状態。勢いは強いが、反落の値幅も大きくなりやすい"}
    if d == "上昇" and w == "上昇":
        return {"label": "上昇継続", "text": "日足・週足とも上向き。25日線の上を保てているかを見る"}
    if w == "上昇" and d != "上昇":
        near = ma25 is not None and abs(close / ma25 - 1) <= 0.03
        if near:
            return {"label": "押し目", "text": "週足は上向きのまま、日足が25日線付近まで調整している"}
        return {"label": "調整", "text": "週足は上向きだが、日足は一服・下向き"}
    if d == "上昇" and w == "下降":
        return {"label": "反発", "text": "週足は下向きのまま、日足だけ戻している。戻り売りに押されやすい"}
    if d == "上昇":
        return {"label": "上昇初動", "text": "日足が上向きに転じた。週足が追随するかが焦点"}
    if d == "下降" and w == "下降":
        return {"label": "下落", "text": "日足・週足とも下向き"}
    if d == "レンジ" and w in ("レンジ", None):
        return {"label": "もみ合い", "text": "方向感が乏しく、上下どちらに抜けるか待ちの状態"}
    return {"label": "方向感なし", "text": "時間軸ごとの向きが揃っていない"}


def _alerts(m, dev25, ma75, close, vol_ratio) -> list[dict]:
    out = []
    rsi = m.get("rsi")
    if rsi is not None and rsi >= 80:
        out.append({"level": "warn", "text": f"RSI {rsi:.0f}。買われすぎの水準で、短期の反落に注意"})
    elif rsi is not None and rsi >= 70:
        out.append({"level": "info", "text": f"RSI {rsi:.0f}。買われすぎの目安（70）を超えている"})
    elif rsi is not None and rsi <= 30:
        out.append({"level": "info", "text": f"RSI {rsi:.0f}。売られすぎの目安（30）を下回っている"})
    if dev25 is not None and dev25 >= 20:
        out.append({"level": "warn", "text": f"25日線から +{dev25:.0f}% 離れている。平均回帰の下げが大きくなりやすい"})
    elif dev25 is not None and dev25 <= -20:
        out.append({"level": "info", "text": f"25日線から {dev25:.0f}% 離れている（売られすぎ）"})
    stab = m.get("stab")
    if stab is not None and stab <= 20:
        out.append({"level": "warn", "text": f"値動きが過去1年でも荒い水準（安定度 {stab:.0f}）。変動拡大に注意"})
    if vol_ratio is not None and vol_ratio >= 3:
        out.append({"level": "info", "text": f"直近5日の出来高が普段の {vol_ratio:.1f} 倍。材料や需給の変化を確認"})
    if ma75 is not None and close < ma75 and (m.get("score") or 0) < 40:
        out.append({"level": "info", "text": "75日線の下にあり、中期トレンドは下向き"})
    d5 = m.get("score_delta5")
    if d5 is not None and d5 <= -15:
        out.append({"level": "warn", "text": f"モメンタム度が5日で {d5:.0f}pt 低下。勢いが失速している"})
    turn20 = m.get("turnover20")
    if turn20 is not None and turn20 < 5e7:
        out.append({"level": "warn",
                    "text": f"売買代金が少ない（20日平均 {turn20 / 1e6:.0f}百万円）。値が飛びやすく、実績の集計からも除外"})
    if m.get("adjusted"):
        out.append({"level": "info", "text": "株式分割などによる価格の段差を補正して計算している"})
    return out


def _yen(x: float) -> str:
    return f"¥{x:,.0f}" if x >= 100 else f"¥{x:,.1f}"


def _conclusion(tf, phase, resistance, support, m) -> str:
    parts = []
    names = {"monthly": "月足", "weekly": "週足", "daily": "日足"}
    seq = [f"{names[k]}は{_label(tf, k)}" for k in ("monthly", "weekly", "daily") if _label(tf, k)]
    if seq:
        parts.append("、".join(seq) + "。")
    parts.append(f"局面は「{phase['label']}」。")
    if support and resistance:
        parts.append(f"{_yen(support)}（押し安値）を割らずに、{_yen(resistance)}（戻り高値）を"
                     "終値で超えられるかが焦点。")
    elif resistance:
        parts.append(f"{_yen(resistance)}（戻り高値）を終値で超えられるかが焦点。")
    elif support:
        parts.append(f"上に目立った節目は無い（高値圏）。{_yen(support)}（押し安値）を割らないかが焦点。")
    stab = m.get("stab")
    if stab is not None and stab <= 20:
        parts.append("値動きは普段より大きい。")
    return "".join(parts)
