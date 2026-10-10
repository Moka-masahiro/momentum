"""テーマ（サイバーセキュリティ・自動運転 …）ごとの値動きと売買代金。資金が集まっているテーマを探す。

テーマと銘柄の対応は pipeline/themes.txt（手作りの表）。株探などのテーマ一覧は、利用規約が複製・加工・蓄積を
禁じているので使わない。表は網羅ではなく、誤りもありうる。表に無い銘柄は、どのテーマにも数えない。

テーマごとに、流動性のある銘柄だけで次を出す（期間は 1日・5日・20日・60日）。

- rel   銘柄の騰落率から市場の中央値（流動性のある全銘柄）を引いたものの、テーマ内の中央値
- up    市場の中央値を上回った銘柄の割合
- z     テーマの銘柄の騰落率が、ほかの銘柄より高い方に偏っている度合い（順位和検定の z）
- tr    売買代金が普段の何倍か。銘柄ごとに「期間の1日平均 ÷ その前250営業日の中央値」を出し、テーマ内の
        中央値を取る（合計どうしの比にすると、売買代金の大きい1〜2銘柄で決まってしまう）
- trx   tr を、市場全体（流動性のある全銘柄）の同じ倍率の中央値で割ったもの

判定は2段にしている。

1. そろって上げている（hot）: rel が「全銘柄の上位1割に入る上がり方」以上で、z が 2 以上。
   テーマの真ん中の銘柄でも全銘柄の上位1割に入るほど上げていて、一部の銘柄だけの動きではない、
   という意味。5日で当たれば「5日で急騰」、20日だけなら「20日で上昇」、60日だけなら「60日で上昇」
   （60日だけのテーマは、上げたあと足踏みしていることが多い）
2. そのうえで売買代金も膨らんでいる（flow）: trx が 1.5 以上。画面で「資金が集まっているかもしれません」と
   出すのは、こちらも満たすテーマだけ。満たさなければ「そろって上昇」とだけ出す

売買代金の条件を別にしたのは、半導体製造装置のような大型株のテーマが、20日で市場より 22% 上げていても
売買代金は普段の 1.3倍（もともと商いが大きい）で、条件を1つにすると何も出なくなったため（2026-10-09 の実測）。

同じ業種の銘柄はもともと一緒に動くので、業種ごと動いた日にもテーマは当たる。原因の証明ではなく、
「まとまって買われている」という観察にすぎない。
"""
import math
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

TABLE = Path(__file__).resolve().parent.parent / "themes.txt"

WINDOWS = (1, 5, 20, 60)   # 営業日
BASE_DAYS = 250            # 売買代金の「普段」（期間の前の250営業日の中央値）
MIN_BASE = 20              # 普段を測るのに要る、売買のあった日数（上場直後の銘柄は測らない）
MIN_MEMBERS = 4            # 流動性のある銘柄がこれ未満のテーマは、判定しない
HOT_PCT = 90               # そろって上げている: テーマの中央値が、全銘柄の上位1割に入る上がり方で、
HOT_Z = 2.0                #   銘柄の順位も高い方に偏っている
FLOW = 1.5                 # 売買代金も膨らんでいる: 市場全体の倍率の 1.5倍以上
DAY_Z = 3.0                # その日の値動きの理由に使う偏り（上げ・下げとも）
AM_SHARE = 0.48            # 前場の売買は1日の約半分（reasons.AM_SHARE と同じ実測）。昼の実行では最新日を割り戻す
STATES = (("surge", "5"), ("rise", "20"), ("hold", "60"))   # 5日で急騰 / 20日で上昇 / 60日で上昇（短い期間を優先）


@dataclass
class Theme:
    name: str
    desc: str = ""
    members: dict = field(default_factory=dict)     # コード → 表に書いてある銘柄名（読む人のためのもの）


def parse(text: str) -> list[Theme]:
    """themes.txt を読む。

        [テーマ名]
        説明: 1行の説明（無くてもよい）
        4704 トレンドマイクロ      # 以降はメモ

    最初の [テーマ名] より前の行と、空行・# で始まる行は読み飛ばす。形式に合わない行は例外にする
    （黙って読み飛ばすと、書き間違えた銘柄が抜けたまま気づかない）。
    """
    themes: list[Theme] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.fullmatch(r"\[(.+)\]", line)
        if m:
            name = m.group(1).strip()
            if any(t.name == name for t in themes):
                raise ValueError(f"themes.txt {n}行目: テーマ「{name}」が2回あります")
            themes.append(Theme(name))
            continue
        if not themes:
            continue
        if line.startswith(("説明:", "説明：")):
            themes[-1].desc = line[3:].strip()
            continue
        m = re.fullmatch(r"(\d{3}[0-9A-Z])(?:\s+(.*))?", line)
        if not m:
            raise ValueError(f"themes.txt {n}行目を読めません: {raw!r}")
        themes[-1].members.setdefault(m.group(1), (m.group(2) or "").strip())
    return themes


def load(path: Path = TABLE) -> list[Theme]:
    return parse(path.read_text(encoding="utf-8"))


def rank_z(values: np.ndarray, member: np.ndarray) -> float | None:
    """member の values が、それ以外より高い方に偏っている度合い（順位和検定の z。正規近似）。"""
    ok = ~np.isnan(values)
    x, m = values[ok], member[ok]
    n1 = int(m.sum())
    n2 = len(x) - n1
    if n1 < MIN_MEMBERS or n2 < MIN_MEMBERS:
        return None
    ranks = pd.Series(x).rank().to_numpy()
    u = ranks[m].sum() - n1 * (n1 + 1) / 2
    return float((u - n1 * n2 / 2) / math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12))


def turnover_ratio(turnover: pd.DataFrame, i: int, w: int, scale: float = 1.0) -> np.ndarray:
    """銘柄ごとに、i 番目の日までの w 日の売買代金（1日平均）が普段の何倍か。
    普段＝その前 250 営業日のうち、売買のあった日の中央値（過去に急増した日があっても引きずられない）。"""
    recent = turnover.iloc[i - w + 1:i + 1].to_numpy(dtype=float).copy()
    recent[-1] *= scale
    base = turnover.iloc[max(i - w + 1 - BASE_DAYS, 0):i - w + 1].to_numpy(dtype=float)
    if not len(base):
        return np.full(turnover.shape[1], np.nan)
    base = np.where(base > 0, base, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)     # 売買の無い銘柄は全て NaN
        usual = np.nanmedian(base, axis=0)
    enough = (~np.isnan(base)).sum(axis=0) >= MIN_BASE
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(enough & (usual > 0), recent.mean(axis=0) / usual, np.nan)


def _r(x, nd: int = 2):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def stats_at(close: pd.DataFrame, turnover: pd.DataFrame, liquid: pd.Series, themes: list[Theme],
             i: int = -1, session: str = "close") -> dict:
    """i 番目の日（既定は最新日）のテーマごとの値。close は欠損を前の値で埋めた終値、turnover は売買代金
    （どちらも 日付×銘柄）。liquid はその日に流動性のある銘柄（index=コード）。"""
    i = i if i >= 0 else len(close) + i
    codes = close.columns
    liq = liquid.reindex(codes).fillna(False).to_numpy(dtype=bool)
    scale = 1 / AM_SHARE if session == "am" else 1.0       # 昼の実行: 最新日の売買代金は前場の分だけ
    out = {"date": close.index[i].strftime("%Y-%m-%d"), "market": {}, "big": {}, "market_tr": {}, "themes": [], "ratios": {}}
    windows = [w for w in WINDOWS if i - w >= 0]
    rets, big, usual = {}, {}, {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)     # 流動性のある銘柄が無い日（合成データなど）
        for w in windows:
            with np.errstate(invalid="ignore", divide="ignore"):
                r = (close.iloc[i] / close.iloc[i - w] - 1).to_numpy(dtype=float) * 100
            market = float(np.nanmedian(r[liq])) if liq.any() else float("nan")
            rets[w] = np.where(liq, r - market, np.nan)          # 流動性のある銘柄の、市場の中央値との差
            big[w] = float(np.nanpercentile(rets[w], HOT_PCT)) if liq.any() else float("nan")
            out["ratios"][w] = turnover_ratio(turnover, i, w, scale)
            usual[w] = float(np.nanmedian(out["ratios"][w][liq])) if liq.any() else float("nan")
            out["market"][str(w)], out["big"][str(w)], out["market_tr"][str(w)] = _r(market), _r(big[w]), _r(usual[w])
    pos = {c: k for k, c in enumerate(codes)}
    for t in themes:
        idx = np.array([pos[c] for c in t.members if c in pos], dtype=int)
        member = np.zeros(len(codes), dtype=bool)
        member[idx] = True
        member &= liq
        n = int(member.sum())
        item = {"name": t.name, "desc": t.desc, "codes": [codes[k] for k in idx], "n": n, "w": {}}
        for w in windows:
            x = rets[w][member]
            x = x[~np.isnan(x)]
            rel = float(np.median(x)) if len(x) else None
            z = rank_z(rets[w], member)
            tr = out["ratios"][w][member]
            tr = float(np.median(tr[~np.isnan(tr)])) if (~np.isnan(tr)).sum() >= MIN_MEMBERS else None
            trx = tr / usual[w] if tr is not None and usual[w] > 0 else None
            item["w"][str(w)] = {
                "rel": _r(rel), "up": _r((x > 0).mean() * 100, 0) if len(x) else None, "z": _r(z, 1),
                "tr": _r(tr), "trx": _r(trx),
                # そろって上げている / そのうえで売買代金も膨らんでいる
                "hot": bool(n >= MIN_MEMBERS and rel is not None and z is not None and rel >= big[w] and z >= HOT_Z),
                "flow": bool(trx is not None and trx >= FLOW),
            }
        key = next(((name, k) for name, k in STATES if item["w"].get(k, {}).get("hot")), None)
        item["state"] = key[0] if key else None
        item["flow"] = bool(key and item["w"][key[1]]["flow"])     # 状態を決めた期間で、売買代金も膨らんでいるか
        out["themes"].append(item)
    return out


def day_labels(close: pd.DataFrame, liquid: pd.DataFrame, themes: list[Theme], days: int) -> dict:
    """直近 days 日について、まとまって動いたテーマの銘柄に付ける文言。{(日付, コード): (向き, 文言)}。

    その日のテーマの z が ±3 以上（そろって上げた・下げた）なら、テーマの銘柄すべてに付ける。値動きの理由
    （reasons.py）が、開示の無い目立った動きに「地合い」として使う（向きが同じ銘柄だけ）。
    1つの銘柄が複数のテーマで当たったら、偏りの大きい方を採る。
    """
    codes = close.columns
    pos = {c: k for k, c in enumerate(codes)}
    index = [(t, np.array([pos[c] for c in t.members if c in pos], dtype=int)) for t in themes]
    out: dict = {}
    best: dict = {}
    for i in range(max(len(close) - days, 1), len(close)):
        liq = liquid.iloc[i].reindex(codes).fillna(False).to_numpy(dtype=bool)
        if not liq.any():
            continue
        with np.errstate(invalid="ignore", divide="ignore"):
            r = (close.iloc[i] / close.iloc[i - 1] - 1).to_numpy(dtype=float)
        rel = np.where(liq, r - np.nanmedian(r[liq]), np.nan)
        day = close.index[i].strftime("%Y-%m-%d")
        for t, idx in index:
            member = np.zeros(len(codes), dtype=bool)
            member[idx] = True
            z = rank_z(rel, member & liq)
            if z is None or abs(z) < DAY_Z:
                continue
            text = f"テーマ「{t.name}」がそろって{'上昇' if z > 0 else '下落'}"
            for k in idx:
                key = (day, codes[k])
                if abs(z) > best.get(key, 0):
                    best[key] = abs(z)
                    out[key] = (1 if z > 0 else -1, text)
    return out


def compute(panel, liquid: pd.DataFrame, session: str = "close", table: list[Theme] | None = None) -> dict:
    """最新日のテーマの一覧（画面用）。そろって上げているテーマを先に（売買代金も膨らんでいるものが最初。
    その中は 5日 → 20日 → 60日 の順）、あとは5日の偏りの大きい順。"""
    table = load() if table is None else table
    close = panel.close.ffill()
    turnover = (panel.close * panel.volume).fillna(0.0)
    s = stats_at(close, turnover, liquid.iloc[-1], table, session=session)
    order = {name: k for k, (name, _) in enumerate(STATES)}
    liq = liquid.iloc[-1]
    with np.errstate(invalid="ignore", divide="ignore"):
        chg5 = (close.iloc[-1] / close.iloc[-6] - 1) if len(close) > 5 else pd.Series(np.nan, index=close.columns)
    for t in s["themes"]:
        live = [c for c in t["codes"] if bool(liq.get(c, False)) and np.isfinite(chg5.get(c, np.nan))]
        t["lead"] = sorted(live, key=lambda c: -chg5[c])[:3]        # 5日の上昇が大きい銘柄（見出しに出す）
    s["themes"].sort(key=lambda t: (t["state"] is None, not t["flow"], order.get(t["state"], len(order)),
                                    -(t["w"].get("5", {}).get("z") or -99)))
    members = sorted({c for t in s["themes"] for c in t["codes"]})
    pos = {c: k for k, c in enumerate(close.columns)}
    ratios = s.pop("ratios")
    known = set(close.columns)
    return {
        **s,
        "session": session,
        "windows": [w for w in WINDOWS if str(w) in s["market"]],
        # テーマの銘柄ごとの、売買代金が普段の何倍か（5日・20日）。一覧に出す
        "turnover": {c: [_r(ratios[w][pos[c]], 1) if w in ratios else None for w in (5, 20)] for c in members},
        "missing": sorted({c for t in table for c in t.members if c not in known}),   # 表にあるが日足の無いコード
    }


def by_code(result: dict) -> dict:
    """コード → その銘柄が入っているテーマ名（一覧の並びの順）。"""
    out: dict = {}
    for t in result["themes"]:
        for c in t["codes"]:
            out.setdefault(c, []).append(t["name"])
    return out


def hot_tag(result: dict) -> dict:
    """コード → (そろって上げているテーマの名前, 売買代金も膨らんでいるか)。その銘柄が入っているうち、並びが先のもの。"""
    out: dict = {}
    for t in result["themes"]:
        if t["state"]:
            for c in t["codes"]:
                out.setdefault(c, (t["name"], t["flow"]))
    return out
