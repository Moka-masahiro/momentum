"""信用残の履歴（JPX「銘柄別信用取引残高」を、申込日ごとに1ファイルでリポジトリに残す）。

JPX に置かれている PDF は直近5営業日分だけで、それより古いものは取れない（fetch.margin_links）。
倍率の推移を見せる・売り長の銘柄がその後どうなったかを後で確かめるには、自分で残すしかない。

    pipeline/margin_history/2026-11-02.bin   申込日ごとに1つ。中身は読めた全行（ETF・REIT も含む）の
                                             残高・前日比・上場比・貸借の印。画面のデータと同じ鍵で暗号化

- 書き足すのは大引け後の全体の更新だけ（build.py --record）。開示だけの更新・昼の更新は読むだけ
- 冪等: ファイル名が申込日なので、同じ日を二度書かない（あれば触らない）。読めなかった日・行が少なすぎた日は
  書かない（fetch.fetch_margin_pdf が例外にする）。書くときは一時ファイルに書いてから名前を変える
- 取り逃しに強い: 記録するたびに JPX に置かれている5営業日分を見て、まだ無い日を取って埋める。
  1回の取り逃し（実行の失敗・コミットの失敗）は、5営業日以内に全体の更新が1回成功すれば埋まる
- 公開リポジトリに置くので暗号化する。合言葉を変えると、それまでのファイルは読めなくなる（読めないものは飛ばす）
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import fetch
import secure

logger = logging.getLogger(__name__)

DIR = Path(__file__).resolve().parent / "margin_history"
VERSION = 1
# fetch.parse_margin_lines の列（code を除く）。残高・前日比は株数、*_ratio は上場株式数に対する%
COLUMNS = ("sell", "sell_chg", "sell_ratio", "buy", "buy_chg", "buy_ratio",
           "std_sell", "std_sell_chg", "std_buy", "std_buy_chg", "loan")
JST = timezone(timedelta(hours=9))


def _cell(col: str, v):
    """JSON に書ける値にする（欠損は None。残高と前日比は整数、上場比は小数、貸借の印は真偽値）。"""
    if v is None or (not isinstance(v, (str, bool, np.bool_)) and pd.isna(v)):
        return None
    if col == "loan":
        return bool(v)
    if col.endswith("_ratio"):
        return round(float(v), 4)
    return int(v)


def pack(df: pd.DataFrame, day: str, source: str | None = None) -> dict:
    """1日分の表を、ファイルに書く形（列名と行の配列）にする。"""
    cols = [c for c in COLUMNS if c in df.columns]
    rows = [[str(r["code"])] + [_cell(c, r[c]) for c in cols] for _, r in df.iterrows()]
    return {"v": VERSION, "date": day, "source": source,
            "saved": datetime.now(JST).strftime("%Y-%m-%d %H:%M"), "columns": ["code", *cols], "rows": rows}


def unpack(doc: dict) -> pd.DataFrame:
    """pack を戻す（index = code）。"""
    df = pd.DataFrame(doc["rows"], columns=doc["columns"]).set_index("code")
    return df


def path_of(folder: Path, day: str) -> Path:
    return Path(folder) / f"{day}.bin"


def days(folder: Path) -> list[str]:
    """残っている申込日（古い順）。"""
    folder = Path(folder)
    if not folder.exists():
        return []
    return sorted(p.stem for p in folder.glob("????-??-??.bin"))


def save(folder: Path, day: str, df: pd.DataFrame, key: bytes, source: str | None = None) -> bool:
    """1日分を書く。もうあれば何もせず False（同じ日を二度書かない）。"""
    path = path_of(folder, day)
    if path.exists():
        return False
    if len(df) < fetch.MIN_MARGIN_ROWS:
        raise ValueError(f"{day}: {len(df)} 行しかないので残しません")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(secure.seal(pack(df, day, source), key))
    os.replace(tmp, path)
    logger.info("margin history: saved %s (%d rows, %.0f KB)", day, len(df), path.stat().st_size / 1e3)
    return True


def load(folder: Path, key: bytes) -> dict[str, pd.DataFrame]:
    """残っている全日分 {申込日: 表}。読めないファイル（合言葉を変えた前のもの・壊れたもの）は飛ばす。"""
    out = {}
    for day in days(folder):
        try:
            doc = secure.open_sealed(path_of(folder, day).read_bytes(), key)
            if doc.get("v") != VERSION or doc.get("date") != day:
                raise ValueError(f"形式が違います（v={doc.get('v')}, date={doc.get('date')}）")
            out[day] = unpack(doc)
        except Exception as e:
            logger.warning("margin history: %s を読めませんでした（%s: %s）。飛ばします", day, type(e).__name__, e)
    return out


def record(folder: Path, key: bytes, current: pd.DataFrame | None, current_day: str | None,
           backfill: bool = True) -> dict:
    """その日の取得分を残し、JPX に置かれている5営業日分のうち、まだ無い日を取って埋める。

    戻り値は実行記録用の要約（saved = 新しく書いた日、failed = 取れなかった日とその理由）。
    ここで失敗しても公開は止めない（呼ぶ側で例外を拾う）。
    """
    have = set(days(folder))
    saved, failed = [], {}
    if current is not None and current_day and current_day not in have:
        if save(folder, current_day, current, key):
            saved.append(current_day)
            have.add(current_day)
    if backfill:
        try:
            links = fetch.margin_links()
        except Exception as e:
            links = []
            failed["list"] = str(e)
        for url in links:
            day = fetch._file_date(url)
            if not day or day in have:
                continue
            try:
                df, d = fetch.fetch_margin_pdf(url)
                if d != day:
                    raise ValueError(f"申込日が合いません（{d}）")
                if save(folder, day, df, key, url):
                    saved.append(day)
                    have.add(day)
            except Exception as e:
                failed[day] = str(e)
                logger.warning("margin history: %s を取れませんでした（%s）", day, e)
    return {"saved": sorted(saved), "failed": failed, "days": len(have),
            "first": min(have) if have else None, "last": max(have) if have else None}


def merge(hist: dict[str, pd.DataFrame], current: pd.DataFrame | None, current_day: str | None) -> dict[str, pd.DataFrame]:
    """残っている履歴に、その回に取得した分を足す（開示だけの更新・昼の更新・記録の前でも、最新日が抜けないように）。"""
    out = dict(hist)
    if current is not None and current_day and current_day not in out and len(current):
        out[current_day] = current.set_index("code") if "code" in current.columns else current
    return dict(sorted(out.items()))


def reseal(folder: Path, old_key: bytes, new_key: bytes) -> int:
    """合言葉を変えるときに、残っている履歴を新しい鍵で暗号化し直す（戻り値は直したファイルの数）。

    全部を古い鍵で開けることを先に確かめてから書き換える（途中で失敗して、新旧の鍵が混ざらないように）。
    """
    blobs = {day: secure.open_bytes(path_of(folder, day).read_bytes(), old_key) for day in days(folder)}
    for day, raw in blobs.items():
        tmp = path_of(folder, day).with_suffix(".tmp")
        tmp.write_bytes(secure.seal_bytes(raw, new_key))
        os.replace(tmp, path_of(folder, day))
    return len(blobs)


if __name__ == "__main__":
    # 合言葉を変えるとき（手元で1回だけ）:
    #   MOMENTUM_PASSPHRASE_OLD=古い合言葉 MOMENTUM_PASSPHRASE=新しい合言葉 python pipeline/margin_history.py --reseal
    import sys
    if sys.argv[1:] != ["--reseal"]:
        sys.exit("使い方: python pipeline/margin_history.py --reseal（環境変数 MOMENTUM_PASSPHRASE_OLD と MOMENTUM_PASSPHRASE）")
    cfg = secure.load_config()
    n = reseal(DIR, secure.derive_key(os.environ["MOMENTUM_PASSPHRASE_OLD"], cfg),
               secure.derive_key(os.environ["MOMENTUM_PASSPHRASE"], cfg))
    print(f"{n} 日分を新しい合言葉で暗号化し直しました。コミットして push してください")
