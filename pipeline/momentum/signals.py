"""シグナル（その日に起きた「出来事」の検知）と、発動後の値動き。

シグナルは予想ではなく**事実の検知**。発動後にどうなったかは、
**翌営業日の始値で入ったと仮定し、N営業日後の終値まで**で測る。
（当日の終値で判定するので、同じ日の終値では入れない）

成績は素のリターンではなく**市場平均との差（超過リターン）**で評価する。
相場全体が上がった期間は、どんなシグナルでも素のリターンはプラスに見えるため。
実測（2025-09〜2026-09）では、例えば「買い集め」の20日後は素のリターン +2.45% だが、
同じ期間の全銘柄平均を引くと +0.68%、中央値は −0.90% だった。

勝率も「市場平均に勝った割合」で数える。値上がり銘柄の分布は右に歪んでいるので
（少数の大化けが平均を押し上げる）、平均がプラスでも勝率は5割を切ることが多い。
"""
import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from . import indicators as ind

HORIZONS = (5, 10, 20)
COOLDOWN = 10          # 同じ銘柄・同じシグナルは10営業日に1回だけ数える


@dataclass
class Frames:
    """シグナル判定に使う表（行=日付、列=銘柄）。"""

    o: pd.DataFrame
    h: pd.DataFrame
    l: pd.DataFrame
    c: pd.DataFrame
    v: pd.DataFrame
    score: pd.DataFrame
    acc: pd.DataFrame
    rsi: pd.DataFrame

    def __post_init__(self):
        self.cf = self.c.ffill()
        self.ma25 = ind.moving_average(self.c, 25)
        self.ma75 = ind.moving_average(self.c, 75)
        self.ret1 = self.cf / self.cf.shift(1) - 1
        rng = self.h - self.l
        self.clv = (((self.c - self.l) - (self.h - self.c)) / rng.where(rng > 0)).fillna(0.0)
        self.vavg20 = ind.rolling(self.v.fillna(0.0), 20, 15, "mean").shift(1)
        self.hh60 = self.h.rolling(60, min_periods=50).max().shift(1)


@dataclass(frozen=True)
class SignalDef:
    key: str
    label: str
    tone: str      # up: 強さの出来事 / warn: 警戒
    rule: str      # 定義（画面にそのまま出す）
    detect: Callable[[Frames], pd.DataFrame]


def _shift_max(frame: pd.DataFrame, n: int) -> pd.DataFrame:
    """直近 n 本（当日を含む）の最大値。窓が小さいので shift を重ねた方が rolling より速い。"""
    out = frame
    for k in range(1, n):
        out = np.fmax(out, frame.shift(k))
    return out


def _shift_min(frame: pd.DataFrame, n: int) -> pd.DataFrame:
    out = frame
    for k in range(1, n):
        out = np.fmin(out, frame.shift(k))
    return out


def _cooldown(sig: pd.DataFrame, n: int = COOLDOWN) -> pd.DataFrame:
    """直前 n 営業日に条件を満たした日があれば数えない（同じ出来事の重複を避ける）。"""
    x = sig.fillna(False).to_numpy(dtype=bool)
    cs = np.vstack([np.zeros((1, x.shape[1])), np.cumsum(x, axis=0)])
    # 行 i の直前 n 行（i-n 〜 i-1）に True がいくつあったか
    i = np.arange(x.shape[0])
    recent = cs[i] - cs[np.maximum(i - n, 0)]
    return pd.DataFrame(x & (recent == 0), index=sig.index, columns=sig.columns)


SIGNALS: tuple[SignalDef, ...] = (
    SignalDef(
        "accumulation", "買い集め", "up",
        "買い集め指数が90以上に上がった日（全銘柄の上位10%入り）で、終値が25日線より上",
        lambda f: (f.acc >= 90) & (f.acc.shift(1) < 90) & (f.c > f.ma25),
    ),
    SignalDef(
        "volume_spike", "出来高急増", "up",
        "出来高が直前20日平均の3倍以上、前日比+2%超、かつ高値寄りで引けた日",
        lambda f: (f.v >= 3 * f.vavg20) & (f.ret1 > 0.02) & (f.clv > 0),
    ),
    SignalDef(
        "breakout", "高値ブレイク", "up",
        "終値が直前60営業日（約3か月）の高値を超え、出来高が20日平均の1.5倍以上",
        lambda f: (f.c > f.hh60) & (f.v >= 1.5 * f.vavg20),
    ),
    SignalDef(
        "rank_s", "ランクS入り", "up",
        "モメンタム度が85以上（ランクS）に上がった日",
        lambda f: (f.score >= 85) & (f.score.shift(1) < 85),
    ),
    SignalDef(
        "pullback", "押し目反発", "up",
        "上昇トレンド中（25日線>75日線・モメンタム度55以上）に25日線付近まで下げ、"
        "陽線で25日線の上に戻した日",
        lambda f: ((f.ma25 > f.ma75) & (f.score >= 55)
                   & (_shift_min(f.l, 3) <= f.ma25 * 1.01)
                   & (f.c > f.ma25) & (f.c > f.o) & (f.ret1 > 0)),
    ),
    SignalDef(
        "breakdown", "トレンド崩れ", "warn",
        "直近5日にモメンタム度70以上だった銘柄が、2%超下げて25日線を割り込んだ日",
        lambda f: ((_shift_max(f.score.shift(1), 5) >= 70)
                   & (f.c < f.ma25) & (f.cf.shift(1) >= f.ma25.shift(1)) & (f.ret1 < -0.02)),
    ),
)
SIGNAL_BY_KEY = {s.key: s for s in SIGNALS}


def detect_all(f: Frames, active: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """シグナルごとの発動日（True/False の表）。売買の無かった日は数えない。"""
    return {s.key: _cooldown(s.detect(f)) & active for s in SIGNALS}


def forward_returns(f: Frames, liquid: pd.DataFrame) -> dict[int, dict[str, pd.DataFrame]]:
    """翌営業日の始値から N営業日後の終値までのリターンと、市場平均との差。

    市場平均は「その日に流動性の基準を満たした全銘柄」の単純平均（同じ期間・同じ計り方）。
    """
    entry = f.o.shift(-1)
    out = {}
    for h in HORIZONS + (60,):
        fwd = f.cf.shift(-h) / entry - 1
        ok = liquid & fwd.notna()
        bench = fwd.where(ok).mean(axis=1)
        out[h] = {"ret": fwd, "excess": fwd.sub(bench, axis=0), "bench": bench}
    return out


def clustered_t(per_date: pd.Series, horizon: int) -> float | None:
    """日付ごとの平均を1標本とみなした t 値。保有期間の重なりの分だけ標本数を割り引く。

    同じ日に発動した銘柄どうしは相場の影響をまとめて受けるので、銘柄数を標本数にすると
    有意に見えすぎる（スコアカードで「行数」を標本数にして失敗したのと同じ理由）。
    """
    per_date = per_date.dropna()
    n = len(per_date)
    if n < 5 or per_date.std() == 0:
        return None
    return float(per_date.mean() / per_date.std() * math.sqrt(n / horizon))


def signal_stats(events: dict[str, pd.DataFrame], fwd: dict, liquid: pd.DataFrame,
                 dates: pd.DatetimeIndex) -> dict[str, dict]:
    """シグナル種別ごとの過去実績（流動性のある銘柄の発動分のみ）。"""
    half = dates[len(dates) // 2]
    liq = liquid.to_numpy(dtype=bool)
    out = {}
    for key, ev in events.items():
        evm = ev.to_numpy(dtype=bool) & liq
        row: dict = {"events": int(evm.sum()), "horizons": {}}
        for h in HORIZONS:
            ret = fwd[h]["ret"].to_numpy()
            exc = fwd[h]["excess"].to_numpy()
            m = evm & ~np.isnan(exc)
            if not m.any():
                row["horizons"][str(h)] = None
                continue
            vals = exc[m]
            per_date = pd.Series(
                np.where(m, exc, 0.0).sum(axis=1) / np.where(m.sum(axis=1) > 0, m.sum(axis=1), np.nan),
                index=dates,
            )
            t = clustered_t(per_date, h)
            first = per_date[per_date.index < half].dropna()
            second = per_date[per_date.index >= half].dropna()
            row["horizons"][str(h)] = {
                "n": int(m.sum()),
                "ret_mean": _pct(float(np.mean(ret[m]))),
                "excess_mean": _pct(float(np.mean(vals))),
                "excess_median": _pct(float(np.median(vals))),
                "win_rate": round(float((vals > 0).mean()) * 100, 1),
                "t": None if t is None else round(t, 2),
                "significant": t is not None and abs(t) >= 2,
                "first_half": _pct(first.mean()) if len(first) else None,
                "second_half": _pct(second.mean()) if len(second) else None,
            }
        out[key] = row
    return out


def _pct(x) -> float | None:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return round(float(x) * 100, 2)
