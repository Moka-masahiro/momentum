"""開示への市場の反応: 適時開示（決算・業績修正・配当・自社株買い・増資・M&A・IR …）のあと、株価と売買代金がどう動いたか。

「良い・悪い」の判定や値動きの予測はしない。開示の表題・分類・時刻と株価だけから、市場の反応という事実を並べる。
決算短信の本文（TDnet の PDF・XBRL）は読まない（TDnet は robots.txt で自動取得をすべて禁止している）。

効く取引日（reasons.effective_day と同じ）
- 寄り付き前（pre）  … 当日。寄り付きの窓（前日終値→始値）に反応が出る
- 取引時間中（mid）  … 当日。開示の前の値動きも混ざる（画面に「場中の開示」と出す）
- 引け後・休日（post）… 次の取引日

開示ごとの指標（% は小数2桁）
- r    その日の騰落率 − 市場の中央値（終値100円以上の全銘柄。reasons の「地合い」と同じ母集団）＝ 市場比
- r5   効いた日を含む5取引日（前日終値 → 5日目の終値）の騰落率 − 同じ期間の市場の中央値。5日に満たないうちは
       n5 日目まで（画面に「3日」などと出す）
- gap  寄り付きの窓（前日終値 → 始値）。oc  寄り付きから引けまで（始値 → 終値）。どちらも株価そのもの
- tr   その日の売買代金が普段の何倍か（前250営業日の売買のあった日の中央値。themes.usual_turnover。テーマと同じ定義）

切り分け（開示だけが原因に見えないように）
- with   同じ銘柄・同じ効く日に、ほかの分類の開示がある（同じ分類の重なり＝決算短信と説明資料、は数えない）
- after  5日の間（効いた日の翌日〜5日目）に、ほかの開示が効いている
- theme  その銘柄の入っているテーマが、その日にそろって動いた（themes.day_labels の z が ±3 以上）

種類ごとの傾向（stats）は、分類ごと（細かい種類も）に、市場比の中央値・上がった割合・動きの大きさ（市場比の
絶対値の中央値）・5日の中央値・売買代金の倍率の中央値・件数を出す。数えるのは「寄り付き前か引け後に出て、
同じ日にほかの分類の開示が無く、テーマもそろって動いていない」開示だけ（場中の開示は、開示の前の値動きが混ざるので
除く）。同じ銘柄・同じ日・同じ分類の開示は1件に数える。件数が MIN_N 未満の分類は「参考」とする。
過去の傾向は将来を保証しない。この傾向とその後の値動きの関係は検証していない。
"""
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import reasons as rsn
from . import themes as th

DAYS = 5          # 5取引日（効いた日を含む）
MIN_N = 30        # 傾向でこれ未満の件数は「参考」
TIMING = ("pre", "mid", "post")


@dataclass
class Reaction:
    by_key: dict                    # (コード, "YYYY-MM-DD HH:MM", 表題) → 反応（画面の開示の行に付ける）
    stats: dict                     # 種類ごとの傾向
    events: pd.DataFrame = field(default_factory=pd.DataFrame)   # 開示ごとの表（確認用。公開しない）


def _p(x, nd: int = 2):
    return None if x is None or not np.isfinite(x) else round(float(x) * 100, nd)


def _x(x, nd: int = 1):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def _nanmedian(a: np.ndarray, axis=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)     # すべて欠損の行（売買の無い日など）
        return np.nanmedian(a, axis=axis)


def table(p, base: pd.DataFrame, liquid: pd.DataFrame, disc: pd.DataFrame | None, theme_moves: dict | None = None,
          session: str = "close") -> pd.DataFrame:
    """開示ごとの反応の表（定例を除く・効く日がデータにあるものだけ）。disc は time, code, title の表。"""
    dates, codes = p.dates, p.codes
    if disc is not None and "url" not in disc.columns:
        disc = disc.assign(url=None)
    d = rsn._prepare(disc, dates, set(codes))
    d = d[(d["kind"] != "routine") & d["day"].notna()].copy()
    cols = ["time", "code", "title", "category", "kind", "sub", "day", "timing", "k", "liquid", "r", "ret", "r5", "n5",
            "gap", "oc", "tr", "with", "after", "theme", "partial"]
    if d.empty:
        return pd.DataFrame(columns=cols)
    d["sub"] = d["title"].map(rsn.subtype)
    d["timing"] = rsn.timing(d["time"], dates).to_numpy()
    k = dates.get_indexer(pd.DatetimeIndex(d["day"]))
    j = codes.get_indexer(d["code"])
    d["k"] = k
    d = d[(k >= 1) & (j >= 0)].copy()
    k, j = d["k"].to_numpy(), codes.get_indexer(d["code"])
    last = len(dates) - 1

    C = p.close.to_numpy(dtype=float)
    CF = p.close.ffill().to_numpy(dtype=float)
    O = p.open.to_numpy(dtype=float)
    B = base.reindex(index=dates, columns=codes).fillna(False).to_numpy(dtype=bool)
    L = liquid.reindex(index=dates, columns=codes).fillna(False).to_numpy(dtype=bool)
    turnover = (p.close * p.volume).fillna(0.0)
    TR = (turnover / th.usual_turnover(turnover)).to_numpy(dtype=float)   # 売買代金が普段の何倍か（themes と同じ定義）

    prev = CF[k - 1, j]
    with np.errstate(invalid="ignore", divide="ignore"):
        ret = C[k, j] / prev - 1
        gap = O[k, j] / prev - 1
        oc = C[k, j] / O[k, j] - 1
    # 日ごとの市場の中央値（その日・5日）は、開示のあった日だけ計算する
    kk = np.minimum(k + DAYS - 1, last)
    mkt1, mkt5 = {}, {}
    for day in np.unique(k):
        e = min(day + DAYS - 1, last)
        with np.errstate(invalid="ignore", divide="ignore"):
            r1 = np.where(B[day], C[day] / CF[day - 1] - 1, np.nan)
            r5 = np.where(B[day], CF[e] / CF[day - 1] - 1, np.nan)
        mkt1[day], mkt5[day] = _nanmedian(r1), _nanmedian(r5)
    with np.errstate(invalid="ignore", divide="ignore"):
        ret5 = CF[kk, j] / prev - 1
    d["ret"] = ret
    d["r"] = ret - np.array([mkt1[x] for x in k])
    d["r5"] = ret5 - np.array([mkt5[x] for x in k])
    d["n5"] = kk - k + 1
    d["gap"], d["oc"] = gap, oc
    d["tr"] = TR[k, j]
    if session == "am":
        d.loc[k == last, "tr"] = TR[last, j[k == last]] / th.AM_SHARE   # 昼の実行: 最新日は前場の分だけ（themes と同じ割り戻し）
    if session == "intraday":
        d.loc[k == last, "tr"] = np.nan          # 取引時間中の途中の売買代金は、1日のどこまでか決まらない
    d["liquid"] = L[k, j]
    d["partial"] = np.where((k == last) & (session != "close"), session, None)
    traded = ~np.isnan(C[k, j]) & ~np.isnan(prev)
    d = d[traded].copy()

    # --- 切り分け ---
    cats = d.drop_duplicates(["code", "day", "category"]).groupby(["code", "day"])["category"].apply(sorted).to_dict()
    d["with"] = [[c for c in cats[(cd, dy)] if c != own] for cd, dy, own in zip(d["code"], d["day"], d["category"])]
    by_code = {cd: np.unique(g["k"].to_numpy()) for cd, g in d.groupby("code")}     # 開示の効いた日（重なりなし）
    d["after"] = [int(((by_code[cd] > x) & (by_code[cd] <= x + DAYS - 1)).sum()) for cd, x in zip(d["code"], d["k"])]
    tm = theme_moves or {}
    d["theme"] = [(tm.get((dy, cd)) or (None, None))[1] for cd, dy in zip(d["code"], d["day"].dt.strftime("%Y-%m-%d"))]
    return d[cols].reset_index(drop=True)


def item(x) -> dict:
    """1件の反応（画面の開示の行に付ける）。"""
    return {
        "t": x.timing, "r": _p(x.r), "r5": _p(x.r5), "n5": int(x.n5), "gap": _p(x.gap), "oc": _p(x.oc),
        "tr": _x(x.tr), "liq": bool(x.liquid),
        **({"with": list(x.with_)} if x.with_ else {}),
        **({"after": int(x.after)} if x.after else {}),
        **({"theme": x.theme} if isinstance(x.theme, str) else {}),
        **({"partial": x.partial} if isinstance(x.partial, str) else {}),
    }


def _summary(g: pd.DataFrame) -> dict:
    r, r5, tr = g["r"].to_numpy(float), g["r5"].to_numpy(float), g["tr"].to_numpy(float)
    full = g["n5"].to_numpy() >= DAYS
    r = r[np.isfinite(r)]
    r5 = r5[full & np.isfinite(r5)]
    tr = tr[np.isfinite(tr)]
    return {
        "n": int(len(r)),
        "r": _p(np.median(r)) if len(r) else None,                     # 市場比の中央値
        "up": _x((r > 0).mean() * 100, 0) if len(r) else None,          # 市場比がプラスだった割合
        "abs": _p(np.median(np.abs(r))) if len(r) else None,           # 動きの大きさ（市場比の絶対値の中央値）
        "n5": int(len(r5)), "r5": _p(np.median(r5)) if len(r5) else None,
        "tr": _x(np.median(tr), 2) if len(tr) else None,
        "gap": _p(_nanmedian(g["gap"].to_numpy(float))) if len(g) else None,
    }


def stats(ev: pd.DataFrame, dates: pd.DatetimeIndex) -> dict:
    """種類ごとの傾向。範囲は all（すべての銘柄）と liquid（効いた日に流動性のある銘柄）の2つ。"""
    if ev.empty:
        return {"first": None, "last": None, "min_n": MIN_N, "days": DAYS, "scopes": {}}
    one = ev.sort_values("time").drop_duplicates(["code", "day", "category"], keep="first")
    clean = one[(one["timing"] != "mid") & (one["with"].str.len() == 0) & one["theme"].isna()]
    scopes = {}
    for scope, sel in (("all", clean), ("liquid", clean[clean["liquid"]])):
        groups = []
        for cat, g in sel.groupby("category"):
            row = {"category": cat, **_summary(g), "subs": []}
            subs = g["sub"].dropna()
            if subs.nunique() >= 2:
                row["subs"] = sorted(({"sub": s, **_summary(h)} for s, h in g.groupby("sub")), key=lambda x: -x["n"])
            groups.append(row)
        groups.sort(key=lambda x: -x["n"])
        allone = one if scope == "all" else one[one["liquid"]]
        scopes[scope] = {
            "groups": groups,
            "total": int(len(allone)),          # 数えた開示（同じ日・同じ分類は1件）
            "used": int(len(sel)),              # 傾向に使った開示
            # 傾向から除いた理由ごとの件数（重なりあり）
            "excluded": {"mid": int((allone["timing"] == "mid").sum()),
                         "with": int((allone["with"].str.len() > 0).sum()),
                         "theme": int(allone["theme"].notna().sum())},
        }
    return {"first": one["day"].min().strftime("%Y-%m-%d"), "last": one["day"].max().strftime("%Y-%m-%d"),
            "min_n": MIN_N, "days": DAYS, "scopes": scopes}


def compute(p, base: pd.DataFrame, liquid: pd.DataFrame, disc: pd.DataFrame | None, theme_moves: dict | None = None,
            session: str = "close", list_since: pd.Timestamp | None = None) -> Reaction:
    """開示ごとの反応（画面に付けるのは list_since 以降の開示だけ）と、種類ごとの傾向。"""
    ev = table(p, base, liquid, disc, theme_moves, session)
    by_key = {}
    recent = ev if list_since is None else ev[ev["time"] >= list_since]
    for x in recent.rename(columns={"with": "with_"}).itertuples():
        by_key[(x.code, x.time.strftime("%Y-%m-%d %H:%M"), x.title)] = item(x)
    return Reaction(by_key, stats(ev, p.dates), ev)
