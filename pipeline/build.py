"""毎日の処理の入口: 取得 → 計算 → 暗号化してデータファイルを書き出す。

    python pipeline/build.py --out web/public/data                 # 本番（GitHub Actions）
    python pipeline/build.py --out web/public/data --limit 300     # 動作確認（銘柄数を絞る）
    python pipeline/build.py --out web/public/data --cache cache/bars.pkl
                                                                   # 取得結果を保存して再利用（開発用）

合言葉は環境変数 MOMENTUM_PASSPHRASE（GitHub では Actions の secret）。
取れた銘柄が少なすぎる・日付が古すぎるときは失敗で終える。そうすれば公開は行われず、
前日のデータが残る（壊れたデータで上書きしない）。

値動きの理由の材料（適時開示・空売り残高・日々公表銘柄・逆日歩・全銘柄の信用残）も取るが、
こちらは取れなくても失敗にしない。取れなかったものは画面に「取得できず」と出る。
--cache を付けたときは、材料も同じフォルダーの extras.pkl に保存して使い回す。
"""
import argparse
import base64
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch  # noqa: E402
import secure  # noqa: E402
from momentum import data, export, reasons  # noqa: E402
from momentum.compute import compute  # noqa: E402

logger = logging.getLogger("build")
JST = timezone(timedelta(hours=9))
STATUS = Path(__file__).resolve().parent / "last_run.json"

MIN_COVERAGE = 0.9     # 銘柄一覧のうち、これ以上の日足が取れなければ失敗にする
MAX_STALE_DAYS = 6     # 最新の日足がこれより古ければ失敗にする（連休でも5日程度）

# データがいつの時点のものか（session）。昼の実行（前場の引け後）と夕方の実行で同じ処理を使い、
# 昼は当日の日足が「前場の終値まで」の途中経過になる。Yahoo の値は20分ほど遅れて届く
SESSION_AM = (11 * 60 + 30, 12 * 60 + 30)   # 昼休み。前場の値がそろっている
SESSION_CLOSE_FROM = 15 * 60 + 50           # 大引け（15:30）の値がそろうころ
MIN_TODAY_SHARE = 0.5  # 取引時間中の実行で、前の取引日に売買のあった銘柄のうち当日の値が付いた割合が
                       # これ未満なら、取得がおかしいとみて公開しない（夕方の実行に任せる）


def session_of(now: datetime, latest_day) -> str:
    """close = 大引け後・寄り付き前・休日（最新の日足はその日の終値）、am = 昼休み（当日は前場の値まで）、
    intraday = 取引時間中（当日は途中の値）。祝日など当日の日足が無い日は close。"""
    if latest_day != now.date() or now.weekday() >= 5:
        return "close"
    t = now.hour * 60 + now.minute
    if SESSION_AM[0] <= t < SESSION_AM[1]:
        return "am"
    if 9 * 60 <= t < SESSION_CLOSE_FROM:
        return "intraday"
    return "close"


def _today_share(bars: pd.DataFrame) -> float:
    """前の取引日に売買のあった銘柄のうち、最新の日にも値が付いた割合。"""
    b = bars[bars["volume"] > 0]
    days = sorted(b["date"].unique())
    if len(days) < 2:
        return 1.0
    had = set(b.loc[b["date"] == days[-2], "code"])
    return len(had & set(b.loc[b["date"] == days[-1], "code"])) / max(len(had), 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="データの出力先（web/public/data）")
    ap.add_argument("--limit", type=int, help="銘柄数を絞る（動作確認用）")
    ap.add_argument("--cache", help="取得結果の保存先。あれば取得せずに読む（開発用）")
    ap.add_argument("--session", choices=("auto", "close", "am", "intraday"), default="auto",
                    help="いつ時点のデータか。auto は実行した時刻から決める（手元で昼の表示を確かめるときは am）")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    passphrase = os.environ.get("MOMENTUM_PASSPHRASE", "")
    if len(passphrase) < 8:
        logger.error("MOMENTUM_PASSPHRASE が未設定か短すぎます（8文字以上）")
        return 2

    started = time.monotonic()
    bars, index, master, failed = _load(args)
    coverage = bars["code"].nunique() / max(len(master), 1)
    latest = pd.to_datetime(bars["date"]).max()
    logger.info("bars: %d rows, %d codes (%.1f%%), latest %s, failed %d",
                len(bars), bars["code"].nunique(), coverage * 100, latest.date(), len(failed))
    if coverage < MIN_COVERAGE and not args.limit:
        logger.error("取れた銘柄が少なすぎます（%.1f%%）。公開しません", coverage * 100)
        return 1
    if (datetime.now(JST).date() - latest.date()).days > MAX_STALE_DAYS:
        logger.error("最新の日足が古すぎます（%s）。公開しません", latest.date())
        return 1
    session = args.session if args.session != "auto" else session_of(datetime.now(JST), latest.date())
    if session != "close":
        share = _today_share(bars)
        logger.info("session %s: %.1f%% of stocks have today's bar", session, share * 100)
        if share < MIN_TODAY_SHARE and not args.limit:
            logger.error("取引時間中なのに当日の値が付いた銘柄が少なすぎます（%.1f%%）。公開しません", share * 100)
            return 1

    panel = data.make_panel(bars, master)
    st = compute(panel, index)
    st.session = session
    st.reasons = _reasons(args, st)

    cfg = secure.load_config()
    key = secure.derive_key(passphrase, cfg)
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "stocks").mkdir(parents=True)
    n_files = 0
    size = 0
    for name, doc in export.documents(st):
        blob = secure.seal(doc, key)
        (out / f"{name}.bin").write_bytes(blob)
        n_files += 1
        size += len(blob)

    built = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    meta = {
        "v": 1,
        "built": built,
        "salt": cfg["salt"],
        "iterations": cfg["iterations"],
        # 合言葉が正しいかを画面側で確かめるための小さな暗号文
        "check": base64.b64encode(secure.seal({"ok": True, "as_of": st.as_of}, key)).decode(),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")

    status = {
        "built": built,
        "as_of": st.as_of,
        "session": session,
        "stocks_listed": len(master),
        "stocks_fetched": int(bars["code"].nunique()),
        "stocks_failed": len(failed),
        "adjustments": len(panel.adjustments),
        "files": n_files,
        "size_mb": round(size / 1e6, 1),
        "elapsed_sec": round(time.monotonic() - started, 1),
        "reasons": reasons.brief(st.reasons.status if st.reasons else None),
    }
    STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    logger.info("done: %s", json.dumps(status, ensure_ascii=False))
    return 0


def _reasons(args, st):
    """値動きの理由。材料が取れなくても、株価と指標の公開は止めない。"""
    now = pd.Timestamp(datetime.now(JST).replace(tzinfo=None))
    try:
        ex = _load_extras(args, st.panel.dates, now)
        rs = reasons.compute(st.panel, st.base, ex, now, session=st.session)
        logger.info("reasons: %s", json.dumps(reasons.brief(rs.status), ensure_ascii=False))
        return rs
    except Exception:
        logger.exception("値動きの理由を作れませんでした（理由なしで公開します）")
        return None


def _load_extras(args, dates: pd.DatetimeIndex, now: pd.Timestamp) -> reasons.Extras:
    cache = Path(args.cache).with_name("extras.pkl") if args.cache else None
    if cache and cache.exists():
        logger.info("loading cache %s", cache)
        return pd.read_pickle(cache)
    ex = reasons.Extras()
    # 判定する最も古い日の、前の取引日の引け後から（銘柄詳細の一覧用に30日前からも）
    start = min(dates[-reasons.WINDOW_DAYS - 1].date(), (now - pd.Timedelta(days=reasons.LIST_DAYS)).date())
    try:
        ex.disclosures, ex.disclosure_days = fetch.fetch_disclosures(start, now.date())
    except Exception as e:
        ex.errors["disclosures"] = str(e)
    try:
        ex.short = fetch.fetch_short_positions()
    except Exception as e:
        ex.errors["short"] = str(e)
    try:
        ex.flags, ex.flags_date = fetch.fetch_margin_flags()
    except Exception as e:
        ex.errors["flags"] = str(e)
    try:
        ex.premium = fetch.fetch_premium()
    except Exception as e:
        ex.errors["premium"] = str(e)
    try:
        ex.margin, ex.margin_date = fetch.fetch_margin_all()
    except Exception as e:
        ex.errors["margin"] = str(e)
    for k, v in ex.errors.items():
        logger.warning("%s: 取得できませんでした（%s）", k, v)
    if cache:
        pd.to_pickle(ex, cache)
    return ex


def _load(args):
    if args.cache and Path(args.cache).exists():
        logger.info("loading cache %s", args.cache)
        cached = pd.read_pickle(args.cache)
        return cached["bars"], cached["index"], cached["master"], cached["failed"]
    master = fetch.fetch_master()
    if args.limit:
        master = master.head(args.limit)
    bars, failed = fetch.fetch_bars(master["code"].tolist())
    index = fetch.fetch_index("^N225")
    if args.cache:
        Path(args.cache).parent.mkdir(parents=True, exist_ok=True)
        pd.to_pickle({"bars": bars, "index": index, "master": master, "failed": failed}, args.cache)
    return bars, index, master, failed


if __name__ == "__main__":
    sys.exit(main())
