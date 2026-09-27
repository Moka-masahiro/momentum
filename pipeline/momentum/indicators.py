"""銘柄ごとの指標。行=日付・列=銘柄の表でまとめて計算する。

各指標が「その銘柄自身の過去と比べている」のか「その日の全銘柄と比べている」のかを
区別しておく。画面の説明文もこの区別に合わせてある。

| 指標       | 比べる相手           | 値の範囲 |
|------------|----------------------|----------|
| モメンタム度 | 自分の普段の値動き   | 0〜100   |
| SR          | 自分の値動き         | 実数（年率） |
| POWER       | 自分の普段の値動き   | 実数（σ単位） |
| 買い集め    | その日の全銘柄       | 0〜100（順位） |
| 安定度      | 自分の過去1年       | 0〜100   |
| RSI         | 自分の値動き         | 0〜100   |
"""
import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252

# --- モメンタム度 -----------------------------------------------------------
# 期間ごとの騰落率を「普段の値動きの大きさ（σ）」で割って z 値にし、加重平均する。
# 値動きの荒い銘柄が同じ +10% でも高く出すぎないようにするため。
SIGMA_WINDOW = 60
SIGMA_FLOOR = 0.005          # 日次0.5%。値動きが極端に小さい銘柄で z が暴れないための下限
Z_WEIGHTS = {20: 0.3, 60: 0.4, 120: 0.3}
Z_WEIGHTS_SHORT = {20: 0.3, 60: 0.4}   # 上場から120営業日未満の銘柄用

# 合成した z 値（ランダムウォークなら標準正規）を 0〜100 に写す尺度。
# 1.0 のまま写すと、流動性のある約2,000銘柄の上位50がすべて 97〜100 に
# 張り付いて順位の差が見えない。実測（2025-11〜2026-09、延べ44万銘柄日）で
# 合成 z の上位1%が 2.6 だったので、それが 97.5 になるよう 1.3 で割る。
# この結果、延べでランクSが約12%・Aが19%・Bが21%・Cが20%・Dが28%になる。
SCORE_SCALE = 1.3

# ランク（モメンタム度の下限）。上から順に当てはめる
RANK_THRESHOLDS = (("S", 85.0), ("A", 70.0), ("B", 55.0), ("C", 40.0), ("D", -1.0))

# --- 買い集め --------------------------------------------------------------
ACC_WINDOW = 20
ACC_VOL_BASE = 120           # 出来高が「普段より多いか」を測る基準期間

# --- 安定度 ----------------------------------------------------------------
STAB_VOL_WINDOW = 20
STAB_HISTORY = 250


def norm_cdf(x):
    """標準正規分布の累積分布関数（scipy を入れずに済ませる。誤差 1.5e-7）。"""
    x = np.asarray(x, dtype=float)
    z = np.abs(x) / math.sqrt(2.0)
    t = 1.0 / (1.0 + 0.3275911 * z)
    poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741
                + t * (-1.453152027 + t * 1.061405429))))
    erf = 1.0 - poly * np.exp(-z * z)
    return 0.5 * (1.0 + np.sign(x) * erf)


def rolling(frame: pd.DataFrame, window: int, min_periods: int, stat: str) -> pd.DataFrame:
    """全銘柄まとめての移動平均・移動標準偏差・移動合計（NaN は窓の中で数えない）。

    pandas の rolling は列ごとに回るので、3,700列だと1回0.3秒かかり、指標全体で
    10秒近くになっていた。累積和の差で窓の合計を出せば全列を一度に計算できる。
    標準偏差は pandas と同じ不偏分散（ddof=1）。
    """
    x = frame.to_numpy(dtype=float)
    valid = ~np.isnan(x)
    x0 = np.where(valid, x, 0.0)

    def window_sum(a):
        cs = np.cumsum(a, axis=0)
        out = cs.copy()
        out[window:] = cs[window:] - cs[:-window]
        return out

    n = window_sum(valid.astype(float))
    s = window_sum(x0)
    with np.errstate(invalid="ignore", divide="ignore"):
        if stat == "sum":
            res = s
        elif stat == "mean":
            res = s / n
        elif stat == "std":
            s2 = window_sum(x0 * x0)
            var = (s2 - s * s / n) / (n - 1)
            res = np.sqrt(np.clip(var, 0.0, None))
        else:
            raise ValueError(stat)
    res = np.where(n >= max(min_periods, 2 if stat == "std" else 1), res, np.nan)
    return pd.DataFrame(res, index=frame.index, columns=frame.columns)


def rw_sd(weights: dict[int, float]) -> float:
    """z 値の加重和の標準偏差（ランダムウォークの場合）。

    期間 a と b の騰落率の z 値は、重なりの分だけ相関する（相関 = √(短い方/長い方)）。
    """
    var = 0.0
    for a, wa in weights.items():
        for b, wb in weights.items():
            var += wa * wb * math.sqrt(min(a, b) / max(a, b))
    return math.sqrt(var)


def log_returns(close: pd.DataFrame) -> pd.DataFrame:
    """日次の対数リターン。売買の無かった日は 0（直前の値を引き継ぐ）。"""
    return np.log(close.ffill()).diff()


def momentum(close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """モメンタム度（0〜100）と、その材料の z 値。

    z_w = ln(今日の終値 / w日前の終値) ÷ (日次σ × √w)
    合成 z = 0.3・z20 + 0.4・z60 + 0.3・z120 を、ランダムウォークでの標準偏差で割って
    標準化し、SCORE_SCALE で割って正規分布の累積確率に写す。

    **その銘柄自身の値動きと比べた絶対的な値**なので、相場全体が弱い日は
    全銘柄の値が下がる（上位の順位ではない）。地合いの判定にもそのまま使える。
    """
    cf = close.ffill()
    lr = np.log(cf).diff()
    sigma = rolling(lr, SIGMA_WINDOW, 40, "std").clip(lower=SIGMA_FLOOR)
    z = {}
    for w in (20, 60, 120):
        z[w] = np.log(cf / cf.shift(w)) / (sigma * math.sqrt(w))

    full = sum(wt * z[w] for w, wt in Z_WEIGHTS.items()) / rw_sd(Z_WEIGHTS)
    short = sum(wt * z[w] for w, wt in Z_WEIGHTS_SHORT.items()) / rw_sd(Z_WEIGHTS_SHORT)
    t = full.fillna(short)
    score = pd.DataFrame(
        norm_cdf(t.to_numpy() / SCORE_SCALE) * 100.0, index=t.index, columns=t.columns
    ).where(t.notna())
    return {"t": t, "score": score, "z20": z[20], "z60": z[60], "z120": z[120], "sigma": sigma}


def rank_letter(score: float | None) -> str | None:
    if score is None or (isinstance(score, float) and math.isnan(score)):
        return None
    for letter, lo in RANK_THRESHOLDS:
        if score >= lo:
            return letter
    return "D"


def rank_frame(score: pd.DataFrame) -> pd.DataFrame:
    """ランクの境界に対応する整数（S=4 … D=0）。シグナル判定で使う。"""
    out = pd.DataFrame(np.nan, index=score.index, columns=score.columns)
    for i, (_, lo) in enumerate(reversed(RANK_THRESHOLDS)):
        out = out.mask(score >= lo, float(i))
    return out.where(score.notna())


def rsi(close: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """RSI（ワイルダー方式）。70以上で買われすぎ、30以下で売られすぎが目安。"""
    d = close.ffill().diff()
    up = d.clip(lower=0)
    dn = (-d).clip(lower=0)
    au = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100 - 100 / (1 + au / ad)
    return out.mask((ad == 0) & au.notna(), 100.0)


def sharpe(close: pd.DataFrame, n: int = 60) -> pd.DataFrame:
    """直近 n 日のシャープレシオ（年率）。平均リターン ÷ リターンのばらつき × √252。

    無リスク金利は差し引かない（日本の短期金利は 0.5% 前後で、日次では無視できる）。
    """
    lr = log_returns(close)
    mu = rolling(lr, n, int(n * 2 / 3), "mean")
    sd = rolling(lr, n, int(n * 2 / 3), "std")
    return (mu / sd.where(sd > 0)) * math.sqrt(TRADING_DAYS)


def accumulation_raw(o, h, l, c, v) -> tuple[pd.DataFrame, pd.DataFrame]:
    """買い集めの素点（-1〜+1 に出来高の増え方を掛けたもの）と、出来高の倍率。

    その日の出来高を「前日より上げたか（符号）」と「引けにかけて買われたか（CLV）」で
    半分ずつ振り分け、直近20日で「買い側に振られた出来高の割合」を取る。
    CLV = ((終値−安値) − (高値−終値)) ÷ (高値−安値)。高値引けで+1、安値引けで−1。
    さらに出来高が普段（120日平均）より膨らんでいるほど強める。
    """
    cf = c.ffill()
    rng = (h - l)
    clv = (((c - l) - (h - c)) / rng.where(rng > 0)).fillna(0.0)
    direction = np.sign(cf - cf.shift(1)).fillna(0.0)
    vol = v.fillna(0.0)
    flow = vol * (0.5 * direction + 0.5 * clv)
    num = rolling(flow, ACC_WINDOW, 15, "sum")
    den = rolling(vol, ACC_WINDOW, 15, "sum")
    acc = num / den.where(den > 0)
    base = rolling(vol, ACC_VOL_BASE, 60, "mean")
    relvol = rolling(vol, ACC_WINDOW, 15, "mean") / base.where(base > 0)
    return acc * np.sqrt(relvol.clip(0.25, 4.0)), relvol


def cross_percentile(frame: pd.DataFrame, mask: pd.DataFrame | None = None) -> pd.DataFrame:
    """その日の全銘柄の中での位置（0〜100）。mask が False の銘柄は順位に入れない。"""
    f = frame.where(mask) if mask is not None else frame
    return f.rank(axis=1, pct=True) * 100.0


def stability(close: pd.DataFrame) -> pd.DataFrame:
    """安定度（0〜100）。直近20日の値動きの大きさが、自分の過去1年の中で穏やかな方か。

    100 = 過去1年でいちばん落ち着いている、0 = いちばん荒れている。
    対数ボラティリティの z 値を正規分布で写す（順位の移動計算より速く、ほぼ同じ結果）。
    """
    lr = log_returns(close)
    vol = rolling(lr, STAB_VOL_WINDOW, 15, "std")
    lv = np.log(vol.where(vol > 0))
    mu = rolling(lv, STAB_HISTORY, 120, "mean")
    sd = rolling(lv, STAB_HISTORY, 120, "std")
    z = (lv - mu) / sd.where(sd > 0)
    return pd.DataFrame(
        (1.0 - norm_cdf(z.to_numpy())) * 100.0, index=z.index, columns=z.columns
    ).where(z.notna())


def moving_average(close: pd.DataFrame, n: int) -> pd.DataFrame:
    return rolling(close.ffill(), n, n, "mean")


def atr(h: pd.DataFrame, l: pd.DataFrame, c: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """ATR（平均的な1日の値幅）。前日終値からの窓も含める。"""
    pc = c.ffill().shift(1)
    tr = np.maximum(h - l, np.maximum((h - pc).abs(), (l - pc).abs()))
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
