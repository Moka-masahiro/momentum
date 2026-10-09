"""計算結果を、画面が読むデータ（JSON）に組み立てる。

サーバーが無いので、画面が必要とするものはすべて前もってファイルにしておく。

    home      ホーム（地合いの要約・ランキング上位・当日のシグナル数・値動きの理由の取得状況）
    latest    全銘柄の最新の値と値動きの理由（ランキングの絞り込み・検索・ウォッチリスト・
              「動いた銘柄」の一覧は画面側でここから作る）
    market    地合いの推移（日経平均・市場区分の中央値・ランクB以上の比率）
    signals   直近20営業日のシグナル（その日の値動きの理由付き）と、種別ごとの過去の実績
    verify    検証（IC・ランク別・十分位・シグナル実績・分割補正の記録）
    margin    制度信用倍率（制度信用の買い残÷売り残）の一覧と、全銘柄の合計
    disclosures  開示の一覧（定例を除く）: これからの材料と、最新日に効いた開示
    stocks/<code>  1銘柄の詳細（チャート・指標・5角形・シグナル履歴・テクニカル整理・
                   値動きの理由・直近30日の開示）
"""
import math
from datetime import datetime, timedelta, timezone
from typing import Iterator

import pandas as pd

from . import data, indicators as ind, report, signals as sig
from .compute import State

CHART_DAYS = 250           # 詳細画面のチャートの本数（約1年）
SIGNAL_DAYS = 20           # シグナル一覧で遡れる営業日数
JST = timezone(timedelta(hours=9))

LATEST_COLUMNS = (
    "code", "name", "segment", "sector33", "close", "chg1", "chg5", "chg20", "chg60",
    "score", "rank", "score_d1", "score_d5", "score_d20", "position", "turnover20",
    "liquid", "base", "traded_today", "last_date", "signals_today", "t",
    "why", "why_text", "idio", "vr", "disc", "disc_text",
)
# 開示の一覧の列（reasons.compute の feed）。pending が next / pm のものは、まだ値動きに効いていない
DISCLOSURE_COLUMNS = ("code", "time", "category", "kind", "title", "url", "pending", "day", "ret", "idio")
# 制度信用倍率の一覧の列（残高は制度信用の分だけ。reasons._std_margin）
MARGIN_COLUMNS = ("code", "loan", "buy", "buy_chg", "sell", "sell_chg", "ratio", "ratio_prev",
                  "buy_days", "sell_days")


def _r(x, nd: int = 1):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else round(f, nd)


def _str(x):
    """文字列でなければ None。pandas 3 の文字列列は欠損を NaN で持つので、そのままだと
    JSON に NaN が出てしまう（上場直後でランクの無い銘柄で実際に起きた）。"""
    return x if isinstance(x, str) else None


def _series(s: pd.Series, nd: int = 1) -> dict:
    s = s.dropna()
    return {"dates": [d.strftime("%Y-%m-%d") for d in s.index], "values": [_r(x, nd) for x in s]}


def row(code: str, r: pd.Series) -> dict:
    sigs = r.get("signals_today")
    return {
        "code": code,
        "name": _str(r.get("name")),
        "segment": _str(r.get("segment")),
        "sector33": _str(r.get("sector33")),
        "close": _r(r["close"], 2),
        "chg1": _r(r["chg1"], 2), "chg5": _r(r["chg5"], 2),
        "chg20": _r(r["chg20"], 2), "chg60": _r(r["chg60"], 2),
        "score": _r(r["score"]), "rank": _str(r["rank"]),
        "score_d1": _r(r["score_d1"]), "score_d5": _r(r["score_d5"]), "score_d20": _r(r["score_d20"]),
        "position": None if pd.isna(r["position"]) else int(r["position"]),
        "universe": int(r["universe"]),
        "turnover20": _r(r["turnover20"], 0),
        "liquid": bool(r["liquid"]),
        "base": bool(r["base"]),
        "traded_today": bool(r["traded_today"]),
        "last_date": r["last_date"],
        "signals_today": sigs if isinstance(sigs, list) else [],
        "t": _r(r["t"], 3),
        # 値動きの理由（目立って動いた日だけ。reasons.py）
        "why": _str(r.get("why")),
        "why_text": _str(r.get("why_text")),
        "idio": _r(r.get("idio"), 2),     # 業種の中央値との差（%）
        "vr": _r(r.get("vr"), 1),         # 出来高 ÷ 直前20日平均
        # これからの材料（引け後の開示など）のうち、いちばん効きそうなものの分類と短い文言
        "disc": _str(r.get("disc")),
        "disc_text": _str(r.get("disc_text")),
    }


def documents(st: State) -> Iterator[tuple[str, dict]]:
    """(ファイル名, 中身) を順に返す。"""
    built_at = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    latest = st.latest if st.reasons is None else st.latest.join(st.reasons.latest)
    rows = {code: row(code, r) for code, r in latest.iterrows()}
    market = _market(st)
    margin = _margin(st)
    yield "home", _home(st, rows, market, built_at, margin)
    yield "latest", _latest(st, rows)
    yield "market", {"as_of": st.as_of, **market}
    yield "margin", margin
    yield "disclosures", _disclosures(st)
    yield "signals", _signals(st)
    yield "verify", {"as_of": st.as_of, "computed_at": built_at, "signal_stats": st.stats,
                     "signal_defs": signal_defs(), "adjustments": st.panel.adjustments, **st.validation}
    base_last = st.base.iloc[-1]
    pct = {k: _percentiles(st.frames[k].iloc[-1], base_last) for k in ("sr", "power")}
    ranks = {x["rank"]: x for x in st.validation["ranks"]}
    by_code = dict(tuple(st.events.groupby("code"))) if len(st.events) else {}
    for code in st.panel.codes:
        yield f"stocks/{code}", stock(st, code, rows[code], pct, ranks, by_code.get(code))


def signal_defs() -> list[dict]:
    return [{"key": s.key, "label": s.label, "tone": s.tone, "rule": s.rule} for s in sig.SIGNALS]


def _home(st: State, rows: dict, market: dict, built_at: str, margin: dict) -> dict:
    ev_today = st.events[st.events["date"] == st.panel.dates[-1]]
    counts = ev_today.groupby("key").size().to_dict()
    df = st.latest
    m = df["base"] & df["score"].notna() & (df["turnover20"] >= 50_000_000)
    top = df[m].sort_values("t", ascending=False).head(5)

    def h20(key, field):
        return ((st.stats.get(key) or {}).get("horizons", {}).get("20") or {}).get(field)

    return {
        "as_of": st.as_of,
        "session": st.session,     # am = 前場の引け後の途中経過（夕方の実行で大引けに置き換わる）
        "computed_at": built_at,
        "universe": int(df["universe"].iloc[0]) if len(df) else 0,
        "market": {
            "nikkei": {k: v for k, v in (market["nikkei"] or {}).items()
                       if k not in ("series", "close_series")} or None,
            "segments": [{k: v for k, v in s.items() if k != "series"} for s in market["segments"]],
            "breadth": {k: v for k, v in market["breadth"].items()
                        if k not in ("b_plus_series", "s_share_series")},
            "breadth_spark": {k: v[-60:] for k, v in market["breadth"]["b_plus_series"].items()},
        },
        "ranking": [rows[code] for code in top.index],
        "verify_summary": _verify_summary(st),
        # 値動きの理由の材料の取得状況（None = 理由を作れなかった）
        "reasons": _finite(st.reasons.status) if st.reasons else None,
        # 全銘柄を合計した制度信用倍率と、売り長の銘柄数（None = 信用残を取れなかった）
        "margin": {"date": margin["date"], **margin["summary"]} if margin["summary"] else None,
        "signals": {
            "total": int(len(ev_today)),
            "liquid": int(ev_today["liquid"].sum()) if len(ev_today) else 0,
            "by_type": [{"key": s.key, "label": s.label, "tone": s.tone,
                         "count": int(counts.get(s.key, 0)),
                         "excess20": h20(s.key, "excess_mean"), "win20": h20(s.key, "win_rate")}
                        for s in sig.SIGNALS],
        },
    }


def _verify_summary(st: State) -> dict:
    """ホームに出す検証の要約。文面を固定で書くと、データが変わったときに嘘になるので数で渡す。"""
    v = st.validation

    def significant(h):
        return bool(h) and h.get("t") is not None and abs(h["t"]) >= 2

    metrics = [r["key"] for r in v["ic"] if any(significant(h) for h in r["horizons"].values())]
    signals = [k for k, s in st.stats.items() if any(h and h.get("significant") for h in s["horizons"].values())]
    return {"from": v.get("ic_first_date"), "to": v.get("ic_last_date"), "days": v.get("ic_days"),
            "metrics": len(v["ic"]), "metrics_significant": len(metrics),
            "signals": len(st.stats), "signals_significant": len(signals)}


def _latest(st: State, rows: dict) -> dict:
    """全銘柄の最新の値を、列名＋行の配列で持つ（オブジェクトの配列より半分ほど小さい）。"""
    master = st.panel.master
    missing = [[code, _str(r.get("name")), data._segment(r.get("market"))]
               for code, r in master.iterrows() if code not in rows]
    return {
        "as_of": st.as_of,
        "session": st.session,
        "universe": int(st.latest["universe"].iloc[0]) if len(st.latest) else 0,
        "columns": list(LATEST_COLUMNS),
        "rows": [[x[c] for c in LATEST_COLUMNS] for x in rows.values()],
        "missing": missing,   # 銘柄マスタにはあるが日足が取れなかった銘柄（検索には出す）
    }


def _margin(st: State) -> dict:
    """制度信用の残高と倍率の一覧（JPX「銘柄別信用取引残高」のうち制度信用の分）。

    date は申込日（公表は次の営業日の16時ごろなので、最新日の前の取引日になる）。
    信用残を取れなかった日は rows が空で summary が None。
    """
    rs = st.reasons
    rows = []
    for code, d in (rs.detail.items() if rs else ()):
        m = d.get("margin")
        if m and "std_buy" in m:
            rows.append([code, m["loan"], m["std_buy"], m["std_buy_chg"], m["std_sell"], m["std_sell_chg"],
                         m["std_ratio"], m["std_ratio_prev"], m["std_buy_days"], m["std_sell_days"]])
    return _finite({
        "as_of": st.as_of,
        "date": rs.status["margin"]["date"] if rs else None,
        "summary": margin_summary(rows),
        "columns": list(MARGIN_COLUMNS),
        "rows": rows,
    })


def _disclosures(st: State) -> dict:
    """開示の一覧（定例を除く）。前半が「これからの材料」（day が無い。引け後の開示＝次の取引日、
    昼の実行では 11:30 以降＝後場）、後半が「最新日に効いた開示」（その日の騰落率と業種との差つき）。

    銘柄は売買代金（20日平均）の大きい順に並べる。最初は分類の優先順にしていたが、小さな会社の
    子会社異動が大型株の業績修正より前に来た（2026-10-08: カヤバの子会社異動がテルモの業績修正より上）。
    同じ銘柄の開示は続けて置き、その中は判定に効く順（先頭が見出し）。
    """
    rs = st.reasons
    turnover = st.latest["turnover20"].fillna(0.0).to_dict()
    parts = []
    for upcoming in (True, False):
        by_code: dict = {}
        for x in (rs.feed if rs else []):
            if (x["day"] is None) == upcoming:
                by_code.setdefault(x["code"], []).append(x)
        for code in sorted(by_code, key=lambda c: (-turnover.get(c, 0.0), c)):
            parts += by_code[code]
    return _finite({
        "as_of": st.as_of,
        "session": st.session,
        "ok": bool(rs and rs.status["disclosures"]["ok"]),
        "latest": rs.status["disclosures"]["latest"] if rs else None,   # 取得できた最も新しい開示の時刻
        "columns": list(DISCLOSURE_COLUMNS),
        "rows": [[x.get(c) for c in DISCLOSURE_COLUMNS] for x in parts],
    })


def margin_summary(rows: list[list]) -> dict | None:
    """全銘柄を合計した制度信用倍率（一覧の銘柄の残高の合計どうしの比。ETF・REIT は対象外）と、売り長の銘柄数。

    前日の倍率は、前日比のある銘柄の「残高−前日比」の合計で出す（前日比の無い上場直後の銘柄は、前日の残高が無い）。
    """
    if not rows:
        return None
    buy, sell = sum(r[2] for r in rows), sum(r[4] for r in rows)
    known = [r for r in rows if r[3] is not None and r[5] is not None]
    prev_buy, prev_sell = sum(r[2] - r[3] for r in known), sum(r[4] - r[5] for r in known)
    rated = [r[6] for r in rows if r[6] is not None]
    return {
        "stocks": len(rows),                    # 信用残を読めた銘柄
        "rated": len(rated),                    # うち制度信用の売り残があり、倍率を出せる銘柄
        "short": sum(x < 1 for x in rated),     # うち1倍未満（売り長）
        "buy": buy, "sell": sell,
        "ratio": _r(buy / sell, 2) if sell else None,
        "ratio_prev": _r(prev_buy / prev_sell, 2) if prev_sell else None,
    }


def _signals(st: State) -> dict:
    ev = st.events
    recent = sorted(ev["date"].unique())[-SIGNAL_DAYS:]
    rs = st.reasons
    events = {}
    for d in recent:
        day = ev[ev["date"] == d]
        ds = pd.Timestamp(d).strftime("%Y-%m-%d")
        # [銘柄, シグナル, 流動性あり, その日の値動きの理由, 短い文言]
        events[ds] = [
            [code, key, bool(liq), *(rs.label(ds, code) if rs else (None, None))]
            for code, key, liq in zip(day["code"], day["key"], day["liquid"])
        ]
    return {
        "as_of": st.as_of,
        "session": st.session,
        "dates": [pd.Timestamp(d).strftime("%Y-%m-%d") for d in reversed(recent)],
        "events": events,
        "stats": st.stats,
        "defs": signal_defs(),
    }


def _market(st: State) -> dict:
    """地合い: 日経平均そのもののモメンタム度と、市場区分ごとの中央値、ランクB以上の比率。

    TOPIX は yfinance から取れない。代わりに**構成銘柄のモメンタム度の中央値**を
    市場区分ごとに出す。指数（時価総額加重）とは別物なので、画面でも「中央値」と明記する。
    """
    idx = st.index.dropna()
    score = st.frames["score"]
    nikkei = None
    if len(idx) > 130:
        nk = ind.momentum(idx.to_frame("N225"))["score"]["N225"].dropna()
        nikkei = {
            "score": _r(nk.iloc[-1]),
            "rank": ind.rank_letter(float(nk.iloc[-1])),
            "delta5": _r(nk.iloc[-1] - nk.iloc[-6]) if len(nk) > 6 else None,
            "close": _r(float(idx.iloc[-1]), 2),
            "change_pct": _r((idx.iloc[-1] / idx.iloc[-2] - 1) * 100, 2),
            "date": idx.index[-1].strftime("%Y-%m-%d"),
            "series": _series(nk.iloc[-CHART_DAYS:]),
            "close_series": _series(idx.iloc[-CHART_DAYS:], 0),
        }

    s = score.where(st.base)
    seg = st.panel.master["segment"].reindex(score.columns)
    segments = []
    for name in data.SEGMENTS:
        cols = seg.index[seg == name]
        med = s[cols].median(axis=1).dropna()
        if med.empty:
            continue
        segments.append({
            "name": name,
            "median": _r(med.iloc[-1]),
            "rank": ind.rank_letter(float(med.iloc[-1])),
            "delta5": _r(med.iloc[-1] - med.iloc[-6]) if len(med) > 6 else None,
            "count": int(s[cols].iloc[-1].notna().sum()),
            "series": _series(med.iloc[-CHART_DAYS:]),
        })
    n = s.notna().sum(axis=1)
    b_thr = dict(ind.RANK_THRESHOLDS)["B"]
    s_thr = dict(ind.RANK_THRESHOLDS)["S"]
    b_plus = ((s >= b_thr).sum(axis=1) / n.where(n > 0) * 100).dropna()
    s_share = ((s >= s_thr).sum(axis=1) / n.where(n > 0) * 100).dropna()
    return {
        "nikkei": nikkei,
        "segments": segments,
        "breadth": {
            "b_plus": _r(b_plus.iloc[-1]) if len(b_plus) else None,
            "s_share": _r(s_share.iloc[-1]) if len(s_share) else None,
            "count": int(n.iloc[-1]),
            "b_plus_series": _series(b_plus.iloc[-CHART_DAYS:]),
            "s_share_series": _series(s_share.iloc[-CHART_DAYS:]),
            # 過去の分布の中での位置（今の広がりが強い方か弱い方か）
            "b_plus_percentile": _r((b_plus < b_plus.iloc[-1]).mean() * 100) if len(b_plus) else None,
        },
    }


def _percentiles(values: pd.Series, mask: pd.Series) -> pd.Series:
    """その日の母集団の中で「自分より小さい銘柄の割合」（0〜100）。"""
    vals = values.where(mask).dropna()
    if len(vals) < 10:
        return pd.Series(dtype=float)
    return (vals.rank(method="min") - 1) / len(vals) * 100


def stock(st: State, code: str, r: dict, pct: dict, ranks: dict,
          events: pd.DataFrame | None = None) -> dict:
    """1銘柄の詳細。events はその銘柄のシグナル（全銘柄分を毎回なめると遅いので渡してもらう）。"""
    p = st.panel
    lr = st.latest.loc[code]
    o, h, l, c, v = (p.open[code], p.high[code], p.low[code], p.close[code], p.volume[code])
    f = st.frames

    metrics = {
        "score": _r(lr["score"]), "rank": _str(lr["rank"]), "t": _r(lr["t"], 2),
        "score_d1": _r(lr["score_d1"]), "score_d5": _r(lr["score_d5"]), "score_d20": _r(lr["score_d20"]),
        "sr": _r(lr["sr"], 2), "power": _r(lr["power"], 2), "rsi": _r(lr["rsi"]),
        "acc": _r(lr["acc"]), "stab": _r(lr["stab"]), "relvol": _r(lr["relvol"], 2),
        "turnover20": _r(lr["turnover20"], 0), "adjusted": code in st.adjusted,
    }
    # レーダー: 5項目とも「外側ほど強い」0〜100。SR と POWER は当日の全銘柄の中での位置
    radar = [
        {"key": "score", "label": "モメンタム", "value": metrics["score"]},
        {"key": "sr", "label": "SR", "value": _r(pct["sr"].get(code))},
        {"key": "acc", "label": "買い集め", "value": metrics["acc"]},
        {"key": "power", "label": "POWER", "value": _r(pct["power"].get(code))},
        {"key": "stab", "label": "安定度", "value": metrics["stab"]},
    ]
    rep = report.build(o, h, l, c, v, {**metrics, "score_delta5": metrics["score_d5"]})

    tail = slice(-CHART_DAYS, None)
    cf = c.to_frame()
    chart = {
        "dates": [d.strftime("%Y-%m-%d") for d in c.index[tail]],
        "open": [_r(x, 2) for x in o.iloc[tail]],
        "high": [_r(x, 2) for x in h.iloc[tail]],
        "low": [_r(x, 2) for x in l.iloc[tail]],
        "close": [_r(x, 2) for x in c.iloc[tail]],
        "volume": [_r(x, 0) for x in v.iloc[tail]],
        "score": [_r(x) for x in f["score"][code].iloc[tail]],
        "ma25": [_r(x, 2) for x in ind.moving_average(cf, 25)[code].iloc[tail]],
        "ma75": [_r(x, 2) for x in ind.moving_average(cf, 75)[code].iloc[tail]],
    }
    return {
        **r,
        "as_of": st.as_of,
        "session": st.session,
        "metrics": metrics,
        "radar": radar,
        "rank_history": ranks.get(lr["rank"]) if isinstance(lr["rank"], str) else None,
        "signals": _stock_events(st, code, events),
        "report": rep,
        "chart": chart,
        # 値動きの理由（最新日）と直近30日の開示。理由を作れなかった日は None / []
        "reason": _finite(st.reasons.detail.get(code)) if st.reasons else None,
        "disclosures": _finite(st.reasons.disclosures.get(code, [])) if st.reasons else [],
    }


def _finite(x):
    """NaN・無限大を None にする。暗号化の前の JSON 化は NaN で失敗するので（allow_nan=False）、
    補助的な値動きの理由のせいで毎日の公開全体が止まらないようにする。"""
    if isinstance(x, dict):
        return {k: _finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_finite(v) for v in x]
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def _stock_events(st: State, code: str, ev: pd.DataFrame | None) -> list[dict]:
    """その銘柄のシグナル履歴と、発動後の値動き（翌営業日の始値→N営業日後の終値）。"""
    if ev is None or ev.empty:
        return []
    p = st.panel
    o, cf = p.open[code], p.close[code].ffill()
    dates = p.dates
    pos = {d: i for i, d in enumerate(dates)}
    out = []
    for d, key, liquid in zip(ev["date"], ev["key"], ev["liquid"]):
        i = pos[d]
        s = sig.SIGNAL_BY_KEY[key]
        item = {"date": d.strftime("%Y-%m-%d"), "key": key, "label": s.label, "tone": s.tone,
                "liquid": bool(liquid), "entry_date": None, "entry": None, "now_pct": None,
                "horizons": {}}
        if i + 1 < len(dates) and not math.isnan(o.iloc[i + 1]):
            entry = float(o.iloc[i + 1])
            item["entry_date"] = dates[i + 1].strftime("%Y-%m-%d")
            item["entry"] = _r(entry, 2)
            item["now_pct"] = _r((float(cf.iloc[-1]) / entry - 1) * 100, 2)
            for hz in sig.HORIZONS:
                if i + hz < len(dates):
                    ret = float(cf.iloc[i + hz]) / entry - 1
                    b = st.bench[hz].get(d)
                    item["horizons"][str(hz)] = {
                        "ret": _r(ret * 100, 2),
                        "excess": None if b is None or pd.isna(b) else _r((ret - b) * 100, 2),
                    }
                else:
                    item["horizons"][str(hz)] = None   # 経過待ち
        out.append(item)
    out.reverse()   # 新しい順
    return out
