"""取得した日足を、指標計算用の「日付×銘柄」の表に整える。

毎回すべての銘柄の日足を取り直すので、株式分割の調整は1回の取得の中で一貫している
（Stock Advisor 版のように、取得の合間の分割で古い行と新しい行の境目に段差が残ることは無い）。
それでも次の2つは起きるので、ここで直す。

## ゴミ値

出来高0の行に、実在しない価格が入っていることがある
（SBI新生銀行の再上場前日に 553億円、日本ドライケミカルに 162億円）。
出来高0は「売買が成立しなかった日」なので、価格に情報が無い。行ごと捨てる。

## 値幅制限を超える段差

東証には値幅制限があるので、1日の値動きには上限がある。**制限値幅を超える段差は
実際の値動きではありえない**ので、分割（または取得の不具合）とみなして過去側を掛け直す。
分割比率（1/2, 1/3 …）に近ければその比率で直し、当日の値動きは残す。
比率に当てはまらない段差は「その日の値動きは不明」として段差そのものを消す
（実例: Hamee 2025-10-30 の −58% はスピンオフによる理論価格の切り下げ）。

判定には落とし穴が3つある（Stock Advisor で実データを使って直した経緯がある）。

- **値幅制限は拡大されることがある。** ストップ高（安）で比例配分が続くと、翌日の
  制限値幅は通常の4倍になる（地盤ネット 328→648→1048円、岡本硝子 601→1001円は本物）。
  前日が一本値（始値＝高値＝安値＝終値）なら4倍まで本物として扱う。
- **ストップ高の値段は呼値の単位に丸まる**（さくらインターネット 2808+500=3308 → 3310円）。
- **分割調整後の価格は当時の実際の価格と違う**ので、当てはめる値幅の段がずれる
  （BCC 611→744.33円は、実際には 1833→2233円で値幅400円の範囲内）。

そこで「比率が 0.55 未満か 1.82 超」かつ「制限値幅の1.5倍を超える」ものだけを段差とする。
1株→1.5株の分割（比率0.67）は拾えないが、まれなので許容する。
"""
import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 東証の制限値幅。基準値段（前日終値）がこの値「未満」の最初の行が当てはまる。
_LIMIT_TABLE = [
    (100, 30), (200, 50), (500, 80), (700, 100), (1_000, 150), (1_500, 300),
    (2_000, 400), (3_000, 500), (5_000, 700), (7_000, 1_000), (10_000, 1_500),
    (15_000, 3_000), (20_000, 4_000), (30_000, 5_000), (50_000, 7_000),
    (70_000, 10_000), (100_000, 15_000), (150_000, 30_000), (200_000, 40_000),
    (300_000, 50_000), (500_000, 70_000), (700_000, 100_000), (1_000_000, 150_000),
]
_LIMIT_BOUNDS = np.array([b for b, _ in _LIMIT_TABLE], dtype=float)
_LIMIT_VALUES = np.array([v for _, v in _LIMIT_TABLE] + [300_000], dtype=float)

# 分割・併合でよく使われる比率。これに近い段差は分割とみなし、当日の値動きを残す
_SPLIT_RATIOS = (1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 20, 50, 100)
_SPLIT_TOL = 0.04
# 段差とみなす条件（理由はモジュールの説明を参照）
_JUMP_RATIO_LOW = 0.55
_JUMP_RATIO_HIGH = 1.82
_LIMIT_SLACK = 1.5

# 市場区分の表示名（JPXの「プライム（内国株式）」などを短くする）
SEGMENTS = ("プライム", "スタンダード", "グロース")


def price_limit(base: np.ndarray) -> np.ndarray:
    """前日終値に対する制限値幅（円）。"""
    idx = np.searchsorted(_LIMIT_BOUNDS, base, side="right")
    return _LIMIT_VALUES[idx]


@dataclass
class Panel:
    """全銘柄の日足（調整済み）。行=日付、列=銘柄コード。"""

    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame          # 売買が無かった日は NaN
    volume: pd.DataFrame
    master: pd.DataFrame         # index=code: name / market / segment / sector33 / scale
    adjustments: list[dict] = field(default_factory=list)

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.close.index

    @property
    def codes(self) -> pd.Index:
        return self.close.columns


def make_panel(bars: pd.DataFrame, master: pd.DataFrame) -> Panel:
    """縦持ちの日足（date, code, open, high, low, close, volume）から Panel を作る。"""
    df = bars[(bars["close"] > 0) & (bars["volume"] > 0)].copy()   # 出来高0は捨てる（上記）
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates(["date", "code"], keep="last")
    wide = df.pivot(index="date", columns="code",
                    values=["open", "high", "low", "close", "volume"]).sort_index()
    c = wide["close"].astype(float)
    o = wide["open"].astype(float).fillna(c)
    h = wide["high"].astype(float).fillna(c)
    l = wide["low"].astype(float).fillna(c)
    v = wide["volume"].astype(float)
    # 高値・安値が終値と矛盾する行（まれに取得側の不具合で起きる）は終値で挟み直す
    h = np.maximum(h, np.maximum(o, c))
    l = np.minimum(l, np.minimum(o, c))

    o, h, l, c, v, adjustments = _adjust_discontinuities(o, h, l, c, v)

    m = master.set_index("code") if "code" in master.columns else master.copy()
    m["segment"] = m["market"].map(_segment)
    logger.info("panel: %d days x %d codes, %d adjustments", c.shape[0], c.shape[1], len(adjustments))
    return Panel(o, h, l, c, v, m, adjustments)


def _segment(market) -> str | None:
    if not isinstance(market, str):
        return None
    for s in SEGMENTS:
        if market.startswith(s):
            return s
    return None


def _adjust_discontinuities(o, h, l, c, v):
    """値幅制限を超える段差を分割（または取得不具合）とみなし、過去側を掛け直す。"""
    C = c.to_numpy()
    n, m = C.shape
    valid = ~np.isnan(C)
    rowpos = np.arange(n, dtype=float)[:, None]
    # 直前に売買があった行の位置・終値・値幅（間に売買の無い日を挟んでもよい）
    last_pos = pd.DataFrame(np.where(valid, rowpos, np.nan)).ffill().shift(1).to_numpy()
    prev = pd.DataFrame(C).ffill().shift(1).to_numpy()
    prev_range = (h - l).ffill().shift(1).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        gap = rowpos - last_pos                      # 経過した営業日数
        ratio = C / prev
        move = np.abs(C - prev)
        lim = price_limit(np.nan_to_num(prev, nan=0.0))
        # 前日が一本値（ストップ高・安の比例配分）なら値幅は4倍まで拡大されうる。
        # 売買の無い日を挟んだ場合も、その間に拡大が起きうるので同じく4倍で見る。
        expanded = (np.nan_to_num(prev_range, nan=1.0) <= 1e-9) | (np.nan_to_num(gap, nan=1.0) > 1)
        allowed = np.where(expanded, 4.0, 1.0) * lim * np.nan_to_num(gap, nan=1.0)
        big = (ratio < _JUMP_RATIO_LOW) | (ratio > _JUMP_RATIO_HIGH)
        impossible = valid & ~np.isnan(prev) & big & (move > allowed * _LIMIT_SLACK)

        split = np.full(C.shape, np.nan)             # 分割なら 1/k、併合なら k
        for k in _SPLIT_RATIOS:
            down = np.abs(ratio * k - 1) < _SPLIT_TOL
            up = np.abs(ratio / k - 1) < _SPLIT_TOL
            split = np.where(np.isnan(split) & down, 1.0 / k, split)
            split = np.where(np.isnan(split) & up, float(k), split)

    flag = impossible
    if not flag.any():
        return o, h, l, c, v, []

    factor = np.where(flag, np.where(np.isnan(split), ratio, split), 1.0)
    # 各行に掛ける倍率 = その行より「後」に起きた段差の倍率の積
    after = np.cumprod(factor[::-1], axis=0)[::-1]
    mult = np.vstack([after[1:], np.ones((1, m))])

    adjustments = []
    for i, j in zip(*np.nonzero(flag)):
        adjustments.append({
            "date": c.index[i].strftime("%Y-%m-%d"),
            "code": c.columns[j],
            "prev_close": round(float(prev[i, j]), 2),
            "close": round(float(C[i, j]), 2),
            "ratio": round(float(ratio[i, j]), 4),
            "kind": "split" if not np.isnan(split[i, j]) else "jump",
        })

    mult_df = pd.DataFrame(mult, index=c.index, columns=c.columns)
    return (o * mult_df, h * mult_df, l * mult_df, c * mult_df, v / mult_df, adjustments)
