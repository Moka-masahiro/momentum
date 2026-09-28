"""全銘柄・全期間の指標をまとめて計算する。

母集団は3段階ある。

- active  … その日に売買が成立した銘柄
- base    … active のうち終値100円以上。順位・地合いの母集団
            （株価2桁以下は1円動くだけで数%になり、判断材料としてノイズにしかならない）
- liquid  … base のうち売買代金20日平均5000万円以上。実績・検証の集計はここだけで行う
            （薄商いの銘柄は実際には約定できない値動きで成績が良く見えるため）
"""
import logging
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import data, indicators as ind, reasons as rsn, signals as sig, validate

logger = logging.getLogger(__name__)

MIN_CLOSE = 100
MIN_TURNOVER = 50_000_000


@dataclass
class State:
    panel: data.Panel
    index: pd.Series                      # 日経平均の終値
    frames: dict[str, pd.DataFrame]
    base: pd.DataFrame
    liquid: pd.DataFrame
    events: pd.DataFrame                  # date, code, key, liquid
    bench: dict[int, pd.Series]           # 期間ごとの市場平均リターン（シグナル成績の基準）
    stats: dict
    validation: dict
    latest: pd.DataFrame                  # 最新日の銘柄ごとの値（index=code）
    elapsed_sec: float = 0.0
    adjusted: set = field(default_factory=set)
    reasons: rsn.Reasons | None = None    # 値動きの理由（build.py が後から入れる。作れなければ None）
    session: str = "close"                # close = 大引け後 / am = 前場の引け後（当日は途中経過）/ intraday

    @property
    def as_of(self) -> str:
        return self.panel.dates[-1].strftime("%Y-%m-%d")


def compute(p: data.Panel, index: pd.Series) -> State:
    started = time.monotonic()
    o, h, l, c, v = p.open, p.high, p.low, p.close, p.volume
    dates = p.dates
    cf = c.ffill()
    turnover20 = ind.rolling((c * v).fillna(0.0).where(cf.notna()), 20, 15, "mean")
    active = c.notna()
    base = active & (c >= MIN_CLOSE)
    liquid = base & (turnover20 >= MIN_TURNOVER)

    mom = ind.momentum(c)
    score, power = mom["score"], mom["z20"]
    sr = ind.sharpe(c)
    rsi = ind.rsi(c)
    acc_raw, relvol = ind.accumulation_raw(o, h, l, c, v)
    acc = ind.cross_percentile(acc_raw, base)
    stab = ind.stability(c)

    frames = sig.Frames(o, h, l, c, v, score, acc, rsi)
    detected = sig.detect_all(frames, base)
    fwd = sig.forward_returns(frames, liquid)
    stats = sig.signal_stats(detected, fwd, liquid, dates)
    validation = validate.run(
        {"score": mom["t"], "sr": sr, "power": power, "acc": acc, "stab": stab, "rsi": rsi},
        score, fwd, liquid, dates,
    )
    events = event_table(detected, liquid)
    bench = {h_: fwd[h_]["bench"] for h_ in sig.HORIZONS}
    del fwd, detected, frames

    kept = {
        "score": score, "t": mom["t"], "power": power, "sr": sr, "rsi": rsi,
        "acc": acc, "stab": stab, "turnover20": turnover20, "relvol": relvol,
    }
    latest = latest_table(p, kept, base, liquid, events)
    elapsed = round(time.monotonic() - started, 1)
    logger.info("computed: as_of=%s, %d codes, %d events (%.1fs)",
                dates[-1].date(), c.shape[1], len(events), elapsed)
    return State(p, index, kept, base, liquid, events, bench, stats, validation, latest,
                 elapsed, {a["code"] for a in p.adjustments})


def event_table(detected: dict[str, pd.DataFrame], liquid: pd.DataFrame) -> pd.DataFrame:
    """発動したシグナルを (日付, 銘柄, 種別, 流動性あり) の縦持ちにする。"""
    liq = liquid.to_numpy(dtype=bool)
    parts = []
    for key, ev in detected.items():
        rows, cols = np.nonzero(ev.to_numpy(dtype=bool))
        if not len(rows):
            continue
        parts.append(pd.DataFrame({
            "date": ev.index[rows], "code": ev.columns[cols], "key": key, "liquid": liq[rows, cols],
        }))
    if not parts:
        return pd.DataFrame(columns=["date", "code", "key", "liquid"])
    return pd.concat(parts, ignore_index=True).sort_values(["date", "code"]).reset_index(drop=True)


def latest_table(p: data.Panel, f: dict, base, liquid, events) -> pd.DataFrame:
    """最新日の銘柄ごとの値。ランキング・検索・ウォッチリストはここから引く。"""
    c = p.close
    cf = c.ffill()
    last = c.index[-1]
    score = f["score"]
    sf = score.ffill()

    def chg(n):
        return (cf.iloc[-1] / cf.iloc[-1 - n] - 1) * 100 if len(cf) > n else np.nan

    df = pd.DataFrame({
        "close": cf.iloc[-1],
        "traded_today": c.iloc[-1].notna(),
        "chg1": chg(1), "chg5": chg(5), "chg20": chg(20), "chg60": chg(60),
        "score": score.iloc[-1],
        "score_d1": sf.iloc[-1] - sf.iloc[-2],
        "score_d5": sf.iloc[-1] - sf.iloc[-6],
        "score_d20": sf.iloc[-1] - sf.iloc[-21],
        "t": f["t"].iloc[-1],
        "power": f["power"].iloc[-1],
        "sr": f["sr"].iloc[-1],
        "rsi": f["rsi"].iloc[-1],
        "acc": f["acc"].iloc[-1],
        "stab": f["stab"].iloc[-1],
        "turnover20": f["turnover20"].iloc[-1],
        "relvol": f["relvol"].iloc[-1],
        "base": base.iloc[-1],
        "liquid": liquid.iloc[-1],
    })
    # 売買の無かった銘柄は、直近に売買があった日の値で表示する（ランキングには入れない）
    last_date = c.apply(lambda s: s.last_valid_index())
    df["last_date"] = [d.strftime("%Y-%m-%d") if isinstance(d, pd.Timestamp) else None for d in last_date]
    df["rank"] = [ind.rank_letter(x) for x in df["score"]]
    # 順位は流動性のある銘柄の中で数える（ランキング画面の既定と揃える）
    ranked = df[df["liquid"] & df["score"].notna()].sort_values("t", ascending=False)
    df["position"] = pd.Series(np.arange(1, len(ranked) + 1), index=ranked.index)
    df["universe"] = len(ranked)
    m = p.master.reindex(df.index)
    df["name"] = m["name"]
    df["segment"] = m["segment"]
    df["sector33"] = m["sector33"]
    today = events[events["date"] == last]
    df["signals_today"] = today.groupby("code")["key"].apply(list).reindex(df.index)
    return df
