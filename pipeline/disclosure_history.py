"""適時開示の履歴（やのしん TDnet WEB-API の1日分を、公表日ごとに1ファイルでリポジトリに残す）。

「開示への市場の反応」の種類ごとの傾向（momentum/reaction.py）は、過去の開示がたくさん要る。毎回の更新で
取るのは直近30日分だけなので、それより前は自分で残しておく。

    pipeline/disclosure_history/2026-11-05.bin   公表日ごとに1つ。中身はその日の全開示の [時刻, コード, 表題]
                                                 （ETF などコードを読めないものは fetch.parse_disclosures が落とす）。
                                                 PDF のリンクは残さない（TDnet の PDF は31日で消える）。画面のデータと同じ鍵で暗号化

- 書き足すのは大引け後の全体の更新だけ（build.py --record）。開示だけの更新・昼の更新は読むだけ
- 書くのは「今日より前の日」だけ（今日の分は夜まで増える）。その回に取った直近30日分から書くので、取り直しは要らない
- 遡り（backfill）: 株価のある最も古い日まで、まだ無い日を新しい方から1日ずつ取る。1回の更新で使う時間に上限
  （budget 秒）を設けて、数回の更新に分けて埋める。実測（2026-11-06、手元）: 1日あたり 1.5〜5秒（決算期の
  2,000件超の日が遅い）、暗号化後 1日 1〜30KB
- 冪等: ファイル名が公表日なので、同じ日を二度書かない。開示が0件の日（土日など）も空のファイルを書く（取り直さないため）。
  取得できなかった日は書かない（次の回が取り直す）
- 公開リポジトリに置くので暗号化する。合言葉を変えると読めなくなる（読めないものは飛ばす。--reseal で直す）
"""
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import fetch
import secure

logger = logging.getLogger(__name__)

DIR = Path(__file__).resolve().parent / "disclosure_history"
VERSION = 1
BUDGET_SEC = 420            # 1回の全体の更新で遡りに使う時間の上限（2年分は 30分ほどなので、5回ほどで埋まる）
JST = timezone(timedelta(hours=9))
COLUMNS = ["time", "code", "title", "url"]


def path_of(folder: Path, day: str) -> Path:
    return Path(folder) / f"{day}.bin"


def days(folder: Path) -> list[str]:
    """残っている公表日（古い順）。"""
    folder = Path(folder)
    return sorted(p.stem for p in folder.glob("????-??-??.bin")) if folder.exists() else []


def pack(df: pd.DataFrame, day: str) -> dict:
    t = pd.to_datetime(df["time"]) if len(df) else pd.Series([], dtype="datetime64[ns]")
    rows = [[x.strftime("%H:%M:%S"), str(c), str(ti)] for x, c, ti in zip(t, df["code"], df["title"])]
    rows.sort()
    return {"v": VERSION, "date": day, "saved": datetime.now(JST).strftime("%Y-%m-%d %H:%M"), "rows": rows}


def unpack(doc: dict) -> pd.DataFrame:
    day = doc["date"]
    rows = doc["rows"]
    return pd.DataFrame({
        "time": pd.to_datetime([f"{day} {r[0]}" for r in rows]) if rows else pd.to_datetime([]),
        "code": [r[1] for r in rows], "title": [r[2] for r in rows], "url": [None] * len(rows),
    }, columns=COLUMNS)


def save(folder: Path, day: str, df: pd.DataFrame, key: bytes) -> bool:
    """1日分を書く。もうあれば何もせず False。"""
    path = path_of(folder, day)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(secure.seal(pack(df, day), key))
    os.replace(tmp, path)
    return True


def load(folder: Path, key: bytes, since: date | None = None) -> tuple[pd.DataFrame, set[date]]:
    """残っている全日分（since 以降）の開示と、残っている日の集合。読めないファイルは飛ばす。"""
    parts, got = [], set()
    for day in days(folder):
        d = date.fromisoformat(day)
        if since and d < since:
            continue
        try:
            doc = secure.open_sealed(path_of(folder, day).read_bytes(), key)
            if doc.get("v") != VERSION or doc.get("date") != day:
                raise ValueError(f"形式が違います（v={doc.get('v')}, date={doc.get('date')}）")
            parts.append(unpack(doc))
            got.add(d)
        except Exception as e:
            logger.warning("disclosure history: %s を読めませんでした（%s: %s）。飛ばします", day, type(e).__name__, e)
    df = pd.concat([p for p in parts if len(p)], ignore_index=True) if any(len(p) for p in parts) else pd.DataFrame(columns=COLUMNS)
    return df, got


def merge(hist: pd.DataFrame, hist_days: set, current: pd.DataFrame | None, current_days: set) -> tuple[pd.DataFrame, set]:
    """履歴とその回に取得した分を合わせる（同じ開示は1つに。PDF のリンクはその回の取得分を残す）。"""
    parts = [x for x in (current, hist) if x is not None and len(x)]
    if not parts:
        return pd.DataFrame(columns=COLUMNS), set(hist_days) | set(current_days)
    df = pd.concat(parts, ignore_index=True)
    df["time"] = pd.to_datetime(df["time"])
    df = df.drop_duplicates(["time", "code", "title"], keep="first").sort_values("time").reset_index(drop=True)
    return df, set(hist_days) | set(current_days)


def record(folder: Path, key: bytes, current: pd.DataFrame | None, current_days: set, today: date,
           start: date, budget: float = BUDGET_SEC, fetch_day=None, fetched: date | None = None) -> dict:
    """その回に取得した直近の日（今日より前）を残し、start まで遡って、まだ無い日を budget 秒まで取って埋める。

    fetched は current を取得した日（既定は today）。その日より前の日だけを current から書く（取得した日の分は、
    そのあとも開示が増えるので書かない）。戻り値は実行記録用の要約。fetch_day はテスト用（既定は
    fetch.fetch_disclosures で1日ずつ取る）。
    """
    fetched = min(fetched or today, today)
    fetch_day = fetch_day or (lambda d: fetch.fetch_disclosures(d, d))
    have = set(days(folder))
    saved, failed = [], []
    if current is not None:
        t = pd.to_datetime(current["time"]) if len(current) else pd.Series([], dtype="datetime64[ns]")
        for d in sorted(current_days):
            s = d.isoformat()
            if d >= fetched or s in have:
                continue
            if save(folder, s, current[t.dt.date == d] if len(current) else current, key):
                saved.append(s)
                have.add(s)
    began = time.monotonic()
    filled = 0
    d = today - timedelta(days=1)
    while d >= start:
        s = d.isoformat()
        if s not in have:
            if time.monotonic() - began > budget:
                break
            try:
                df, ok = fetch_day(d)
                if d not in ok:
                    raise RuntimeError("取得できませんでした")
                save(folder, s, df, key)
                have.add(s)
                filled += 1
            except Exception as e:
                failed.append(s)
                logger.warning("disclosure history: %s を取れませんでした（%s）", s, e)
        d -= timedelta(days=1)
    missing = sum(1 for k in range((today - start).days) if (start + timedelta(days=k)).isoformat() not in have)
    return {"saved": len(saved), "backfilled": filled, "failed": failed[:10], "days": len(have),
            "first": min(have) if have else None, "last": max(have) if have else None,
            "missing": missing, "elapsed_sec": round(time.monotonic() - began, 1)}


def reseal(folder: Path, old_key: bytes, new_key: bytes) -> int:
    """合言葉を変えるときに、残っている履歴を新しい鍵で暗号化し直す（全部を開けることを先に確かめる）。"""
    blobs = {day: secure.open_bytes(path_of(folder, day).read_bytes(), old_key) for day in days(folder)}
    for day, raw in blobs.items():
        tmp = path_of(folder, day).with_suffix(".tmp")
        tmp.write_bytes(secure.seal_bytes(raw, new_key))
        os.replace(tmp, path_of(folder, day))
    return len(blobs)


if __name__ == "__main__":
    # 合言葉を変えるとき（手元で1回だけ。margin_history.py --reseal と一緒に）:
    #   MOMENTUM_PASSPHRASE_OLD=古い合言葉 MOMENTUM_PASSPHRASE=新しい合言葉 python pipeline/disclosure_history.py --reseal
    import sys
    if sys.argv[1:] != ["--reseal"]:
        sys.exit("使い方: python pipeline/disclosure_history.py --reseal（環境変数 MOMENTUM_PASSPHRASE_OLD と MOMENTUM_PASSPHRASE）")
    cfg = secure.load_config()
    n = reseal(DIR, secure.derive_key(os.environ["MOMENTUM_PASSPHRASE_OLD"], cfg),
               secure.derive_key(os.environ["MOMENTUM_PASSPHRASE"], cfg))
    print(f"{n} 日分を新しい合言葉で暗号化し直しました。コミットして push してください")
