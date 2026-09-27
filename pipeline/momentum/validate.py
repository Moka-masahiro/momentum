"""指標が「その後のリターン」を説明できていたかの検証。

アプリが出す数字をそのまま信じないための画面の裏側。毎日の再計算で更新される。

- **IC（情報係数）**: その日の全銘柄について「指標の順位」と「その後の超過リターンの順位」の
  相関（スピアマン）を取り、日ごとに平均したもの。0なら無関係、+0.05 でも株式では強い部類。
- **ランク別**: モメンタム度のランクごとに、その後の超過リターンの平均と勝率。
- **前半・後半**: 期間を半分に割って、同じ傾向が続いているか（局面が変わると逆転しうる）。

初回の実測（2025-11〜2026-09）: どの指標も |t| < 2 で有意ではなかった。
モメンタムは前半（〜2026-02）に効き、後半に逆転している（README 参照）。
"""
import math

import numpy as np
import pandas as pd

from . import indicators as ind
from .signals import clustered_t

IC_HORIZONS = (5, 20, 60)
MIN_NAMES = 200           # この銘柄数に満たない日は IC を計算しない
ROLLING_DAYS = 60         # IC の移動平均（局面の変化を見る）


def _ranks(frame: pd.DataFrame, mask: pd.DataFrame) -> np.ndarray:
    """その日の母集団（mask）の中での順位。母集団の外は NaN。"""
    return frame.where(mask).rank(axis=1).to_numpy()


def daily_ic(metric_ranks: np.ndarray, excess_ranks: np.ndarray, dates) -> pd.Series:
    """日ごとのスピアマン順位相関（順位は事前に計算したものを使う）。

    指標の順位は期間ごとに計算し直さない。期間によって違うのは将来リターンが
    まだ無い最後の数日と、途中で売買が止まった少数の銘柄だけで、結果はほぼ変わらない
    （18回の順位付けが9回になり、計算時間が半分になる）。
    """
    ok = ~np.isnan(metric_ranks) & ~np.isnan(excess_ranks)
    a = np.where(ok, metric_ranks, 0.0)
    b = np.where(ok, excess_ranks, 0.0)
    n = ok.sum(axis=1)
    # 共通部分だけで平均を取り直す
    a = a - np.where(ok, (a.sum(axis=1) / np.maximum(n, 1))[:, None], 0.0)
    b = b - np.where(ok, (b.sum(axis=1) / np.maximum(n, 1))[:, None], 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        ic = (a * b).sum(axis=1) / np.sqrt((a * a).sum(axis=1) * (b * b).sum(axis=1))
    s = pd.Series(ic, index=dates)
    return s[(n >= MIN_NAMES)].dropna()


def run(metrics: dict[str, pd.DataFrame], score: pd.DataFrame, fwd: dict,
        liquid: pd.DataFrame, dates: pd.DatetimeIndex) -> dict:
    half = dates[len(dates) // 2]
    exc_ranks = {h: _ranks(fwd[h]["excess"], liquid) for h in IC_HORIZONS}
    ic_rows = []
    rolling = {}
    ic_range = None   # 20日後の IC が計算できた期間（指標の立ち上がりと、将来リターン待ちの分だけ短い）
    for key, frame in metrics.items():
        m_ranks = _ranks(frame, liquid)
        row = {"key": key, "horizons": {}}
        for h in IC_HORIZONS:
            ic = daily_ic(m_ranks, exc_ranks[h], dates)
            if len(ic) < 5:
                row["horizons"][str(h)] = None
                continue
            t = clustered_t(ic, h)
            row["horizons"][str(h)] = {
                "days": int(len(ic)),
                "ic": round(float(ic.mean()), 4),
                "t": None if t is None else round(t, 2),
                "positive_share": round(float((ic > 0).mean()) * 100, 1),
                "first_half": round(float(ic[ic.index < half].mean()), 4) if (ic.index < half).any() else None,
                "second_half": round(float(ic[ic.index >= half].mean()), 4) if (ic.index >= half).any() else None,
            }
            if h == 20:
                rolling[key] = ic.rolling(ROLLING_DAYS, min_periods=20).mean()
                if key == "score":
                    ic_range = (ic.index[0].strftime("%Y-%m-%d"), ic.index[-1].strftime("%Y-%m-%d"), int(len(ic)))
        ic_rows.append(row)

    ranks = _rank_buckets(score, fwd, liquid, half)
    deciles = _deciles(score, fwd[20]["excess"], liquid, half)
    roll = pd.DataFrame(rolling)
    return {
        "first_date": dates[0].strftime("%Y-%m-%d"),
        "last_date": dates[-1].strftime("%Y-%m-%d"),
        "half_date": half.strftime("%Y-%m-%d"),
        "ic_first_date": ic_range[0] if ic_range else None,
        "ic_last_date": ic_range[1] if ic_range else None,
        "ic_days": ic_range[2] if ic_range else None,
        "ic": ic_rows,
        "ranks": ranks,
        "deciles": deciles,
        "rolling_ic": {
            "dates": [d.strftime("%Y-%m-%d") for d in roll.index],
            "series": {k: [None if pd.isna(x) else round(float(x), 4) for x in roll[k]] for k in roll},
        },
    }


def _rank_buckets(score, fwd, liquid, half) -> list[dict]:
    out = []
    bounds = list(ind.RANK_THRESHOLDS)
    sc = score.to_numpy()
    liq = liquid.to_numpy(dtype=bool)
    # 比率の分母は「モメンタム度が出ている銘柄」。立ち上がりの約60日は全銘柄が未計算なので除く
    n_scored = (liq & ~np.isnan(sc)).sum(axis=1)
    for i, (letter, lo) in enumerate(bounds):
        hi = bounds[i - 1][1] if i > 0 else 1e9
        with np.errstate(invalid="ignore"):
            m = liq & (sc >= lo) & (sc < hi)
        share = np.nanmean(m.sum(axis=1) / np.where(n_scored > 0, n_scored, np.nan))
        row = {"rank": letter, "share": round(float(share) * 100, 1), "horizons": {}}
        for h in (5, 20, 60):
            exc = fwd[h]["excess"].to_numpy()
            mm = m & ~np.isnan(exc)
            if not mm.any():
                row["horizons"][str(h)] = None
                continue
            cnt = mm.sum(axis=1)
            per_date = pd.Series(np.where(mm, exc, 0.0).sum(axis=1) / np.where(cnt > 0, cnt, np.nan),
                                 index=score.index)
            vals = exc[mm]
            t = clustered_t(per_date, h)
            row["horizons"][str(h)] = {
                "n": int(mm.sum()),
                "excess_mean": _mean_pct(per_date),
                "win_rate": round(float((vals > 0).mean()) * 100, 1),
                "t": None if t is None else round(t, 2),
                "first_half": _mean_pct(per_date[per_date.index < half]),
                "second_half": _mean_pct(per_date[per_date.index >= half]),
            }
        out.append(row)
    return out


def _deciles(score, excess, liquid, half) -> list[dict]:
    ok = liquid & score.notna() & excess.notna()
    dec = np.ceil(score.where(ok).rank(axis=1, pct=True) * 10).clip(1, 10)
    out = []
    for d in range(1, 11):
        per_date = excess.where(dec == d).mean(axis=1).dropna()
        out.append({
            "decile": d,
            "excess_mean": _mean_pct(per_date),
            "first_half": _mean_pct(per_date[per_date.index < half]),
            "second_half": _mean_pct(per_date[per_date.index >= half]),
        })
    return out


def _mean_pct(s: pd.Series) -> float | None:
    s = s.dropna()
    if not len(s):
        return None
    v = float(s.mean())
    return None if math.isnan(v) else round(v * 100, 2)
