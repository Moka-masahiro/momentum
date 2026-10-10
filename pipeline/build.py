"""毎日の処理の入口: 取得 → 計算 → 暗号化してデータファイルを書き出す。

    python pipeline/build.py --out web/public/data                 # 本番（GitHub Actions）
    python pipeline/build.py --out web/public/data --limit 300     # 動作確認（銘柄数を絞る）
    python pipeline/build.py --out web/public/data --cache cache/bars.pkl
                                                                   # 取得結果を保存して再利用（開発用）
    python pipeline/build.py --out web/public/data --keep cache/kept.bin    # 本番: 取得結果を暗号化して残す
    python pipeline/build.py --out web/public/data --light cache/kept.bin   # 開示だけ取り直して作り直す

合言葉は環境変数 MOMENTUM_PASSPHRASE（GitHub では Actions の secret）。
取れた銘柄が少なすぎる・日付が古すぎるときは失敗で終える。そうすれば公開は行われず、
前日のデータが残る（壊れたデータで上書きしない）。

値動きの理由の材料（適時開示・空売り残高・日々公表銘柄・逆日歩・全銘柄の信用残）も取るが、
こちらは取れなくても失敗にしない。取れなかったものは画面に「取得できず」と出る。
--cache を付けたときは、材料も同じフォルダーの extras.pkl に保存して使い回す。

## 開示だけの更新（--keep と --light）

夕方の更新（17:17）のあとにも会社の開示は出る（実測 2026-09-08〜10-09: 定例を除く開示の 5.7% が 17:17 以降、
2.6% が翌朝の寄り付き前）。それを夜と翌朝に拾うために、株価は取り直さず、開示だけ取り直して作り直す。

- --keep: 大引け後の更新で取得したもの（日足・銘柄一覧・材料）を、画面のデータと同じ鍵で暗号化して保存する。
  GitHub では Actions のキャッシュに置く（公開されない場所だが、株価そのものなので暗号化しておく）
- --light: それを読み、開示だけ取り直して、指標の計算から書き出しまでを同じ処理でやり直す。
  画面のデータを部分的に書き換える方法にしなかったのは、同じ内容を作る処理を2つ持つと食い違うため
  （計算と書き出しは2分ほど。Yahoo にはアクセスしない）
- 取り直せなかったとき・保存した結果を使えないときは、失敗で終える（公開せず、夕方のデータが残る）
"""
import argparse
import base64
import gzip
import json
import logging
import os
import pickle
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch  # noqa: E402
import market_days  # noqa: E402
import secure  # noqa: E402
import should_build  # noqa: E402
from momentum import data, export, reasons, themes  # noqa: E402
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

KEPT_VERSION = 1       # --keep で保存する取得結果の形式。取得するものや列を変えたら上げる
                       # （形式の違う保存結果は --light で使わず、次の全体の更新で作り直す）
MAX_LOST_SHARE = 0.1   # 開示を取り直したら、前に取れていた開示がこれより多く消えていたときは、取得がおかしいとみる


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


def stale_reason(now: datetime, latest_day, share: float) -> str | None:
    """取引日の大引け後の実行なのに当日の日足がそろっていなければ、その理由（公開しない）。そろっていれば None。

    Yahoo が当日分をまだ返さないと、前日のデータを「大引け後」として出してしまう（古さの検査は連休に備えて
    6日前まで通すので、そこでは止まらない）。公開せずに終われば、予備の回がもう一度取りに行く。
    休場日と、大引け前（朝・夜中に前の取引日の分を作るとき）は対象外。
    """
    if not market_days.is_trading_day(now.date()) or now.hour * 60 + now.minute < SESSION_CLOSE_FROM:
        return None
    if latest_day != now.date():
        return f"取引日の大引け後なのに、当日の日足がまだありません（最新は {latest_day}）"
    if share < MIN_TODAY_SHARE:
        return f"当日の値が付いた銘柄が少なすぎます（{share * 100:.1f}%）"
    return None


def _today_share(bars: pd.DataFrame) -> float:
    """前の取引日に売買のあった銘柄のうち、最新の日にも値が付いた割合。"""
    b = bars[bars["volume"] > 0]
    days = sorted(b["date"].unique())
    if len(days) < 2:
        return 1.0
    had = set(b.loc[b["date"] == days[-2], "code"])
    return len(had & set(b.loc[b["date"] == days[-1], "code"])) / max(len(had), 1)


class KeptError(Exception):
    """保存した取得結果を使えない（開示だけの更新をやめる理由）。"""


def pack_kept(status: dict, fetched: bytes, extras: bytes, key: bytes) -> bytes:
    """大引け後に取得したもの（pickle 済みの日足などと材料）と、そのときの実行記録を、暗号化してまとめる。"""
    raw = pickle.dumps({"v": KEPT_VERSION, "status": status, "fetched": fetched, "extras": extras},
                       protocol=pickle.HIGHEST_PROTOCOL)
    return secure.seal_bytes(gzip.compress(raw, compresslevel=3, mtime=0), key)


def open_kept(blob: bytes, key: bytes) -> dict:
    try:
        raw = secure.open_bytes(blob, key)
    except Exception:
        raise KeptError("保存した取得結果を開けません（合言葉が変わった可能性）") from None
    # pickle は読むだけでコードを実行できる形式。ここまで来るのは認証付きの暗号（AES-GCM）を通ったもの、
    # つまり合言葉を知っている者（このビルド自身）が作ったものだけ
    kept = pickle.loads(gzip.decompress(raw))
    if not isinstance(kept, dict) or kept.get("v") != KEPT_VERSION:
        raise KeptError("保存した取得結果の形式が今のコードと違います（次の全体の更新で作り直されます）")
    return kept


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="データの出力先（web/public/data）")
    ap.add_argument("--limit", type=int, help="銘柄数を絞る（動作確認用）")
    ap.add_argument("--cache", help="取得結果の保存先。あれば取得せずに読む（開発用）")
    ap.add_argument("--session", choices=("auto", "close", "am", "intraday"), default="auto",
                    help="いつ時点のデータか。auto は実行した時刻から決める（手元で昼の表示を確かめるときは am）")
    ap.add_argument("--keep", help="大引け後の取得結果を暗号化して保存する先（開示だけの更新 --light で使い回す）")
    ap.add_argument("--light", help="--keep で保存した取得結果を読み、開示だけ取り直して作り直す（株価は取得しない）")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    passphrase = os.environ.get("MOMENTUM_PASSPHRASE", "")
    if len(passphrase) < 8:
        logger.error("MOMENTUM_PASSPHRASE が未設定か短すぎます（8文字以上）")
        return 2
    cfg = secure.load_config()
    key = secure.derive_key(passphrase, cfg)

    started = time.monotonic()
    kept = None
    if args.light:
        try:
            kept = open_kept(Path(args.light).read_bytes(), key)
        except (OSError, KeptError) as e:
            logger.error("%s。公開しません", e)
            return 1
        try:
            fetched = pickle.loads(kept["fetched"])
            bars, index, master, failed = (fetched[k] for k in ("bars", "index", "master", "failed"))
        except Exception:   # 保存したときと pandas の版が違うなど。次の全体の更新で作り直される
            logger.exception("保存した取得結果を読めませんでした。公開しません")
            return 1
        logger.info("light: reusing the data fetched at %s", kept["status"].get("built"))
    else:
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
    if kept:
        session = kept["status"].get("session")      # 取得したときに決めたまま（時刻から決め直さない）
        if session != "close":
            logger.error("保存した取得結果が大引け後のものではありません（%s）。公開しません", session)
            return 1
    else:
        session = args.session if args.session != "auto" else session_of(datetime.now(JST), latest.date())
        if session != "close":
            share = _today_share(bars)
            logger.info("session %s: %.1f%% of stocks have today's bar", session, share * 100)
            if share < MIN_TODAY_SHARE and not args.limit:
                logger.error("取引時間中なのに当日の値が付いた銘柄が少なすぎます（%.1f%%）。公開しません", share * 100)
                return 1
        elif args.session == "auto" and not args.cache and not args.limit:   # 手元の確認（古いキャッシュ）では止めない
            stale = stale_reason(datetime.now(JST), latest.date(), _today_share(bars))
            if stale:
                logger.error("%s。公開しません", stale)
                return 1
    # 残すのは大引け後の取得結果だけ（開示だけの更新は、大引けのデータにしか行わない）。計算に渡す前の状態を残す
    keeping = bool(args.keep) and not kept and session == "close"
    fetched_blob = pickle.dumps({"bars": bars, "index": index, "master": master, "failed": failed},
                                protocol=pickle.HIGHEST_PROTOCOL) if keeping else None

    panel = data.make_panel(bars, master)
    st = compute(panel, index)
    st.session = session
    st.themes, theme_moves = _themes(st)
    now = pd.Timestamp(datetime.now(JST).replace(tzinfo=None))
    extras_blob = None
    if kept:
        st.prices_at = kept["status"].get("built")
        try:
            ex = pickle.loads(kept["extras"])
            refresh_disclosures(ex, st.panel.dates, now)
            st.reasons = reasons.compute(st.panel, st.base, ex, now, session=session, theme_moves=theme_moves)
        except Exception:   # この更新は開示のためだけなので、取り直せなければ公開しない（夕方のデータが残る）
            logger.exception("開示を取り直せませんでした。公開しません")
            return 1
        logger.info("reasons: %s", json.dumps(reasons.brief(st.reasons.status), ensure_ascii=False))
    else:
        st.reasons, extras_blob = _reasons(args, st, now, keeping, theme_moves)

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
        # 次に全体の更新が公開される予定（画面が「更新が届いていない」と気づくため。休場日は飛ばす）
        "next": market_days.next_update(datetime.now(JST)).strftime("%Y-%m-%d %H:%M"),
        "salt": cfg["salt"],
        "iterations": cfg["iterations"],
        # 合言葉が正しいかを画面側で確かめるための小さな暗号文
        "check": base64.b64encode(secure.seal({"ok": True, "as_of": st.as_of}, key)).decode(),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")

    elapsed = round(time.monotonic() - started, 1)
    if kept:
        # 実行記録は全体の更新のときのまま（built は「株価を取得した時刻」として should_build.py が見る）。
        # 開示だけの更新の分は refreshed に足す: 時刻・最も新しい開示の時刻・見つかった新着の件数
        ds = st.reasons.status["disclosures"]
        status = {**kept["status"], "reasons": reasons.brief(st.reasons.status),
                  "refreshed": {"at": built, "latest": ds["latest"],
                                "new": sum(bool(x.get("late")) for x in st.reasons.feed), "elapsed_sec": elapsed}}
    else:
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
            "elapsed_sec": elapsed,
            "reasons": reasons.brief(st.reasons.status if st.reasons else None),
        }
    if fetched_blob and extras_blob:
        # 残した取得結果の名前（Actions のキャッシュに置くときの名前）を実行記録に書く。
        # should_build.py は、これがある大引けのデータにだけ開示だけの更新を行う
        status["kept"] = should_build.kept_key(built)
        path = Path(args.keep)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pack_kept(status, fetched_blob, extras_blob, key))
        logger.info("kept: %s (%.1f MB)", path, path.stat().st_size / 1e6)
        _output("kept", status["kept"])
    STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    logger.info("done: %s", json.dumps(status, ensure_ascii=False))
    return 0


def _output(name: str, value: str) -> None:
    """GitHub Actions の後続のステップに値を渡す（手元では何もしない）。"""
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def _themes(st):
    """テーマごとの値動き（画面用）と、日ごとの「テーマがそろって動いた」印（値動きの理由用）。
    手作りの表から作る補助の情報なので、作れなくても株価と指標の公開は止めない。"""
    try:
        table = themes.load()
        result = themes.compute(st.panel, st.liquid, st.session, table)
        moves = themes.day_labels(st.panel.close.ffill(), st.liquid, table, reasons.WINDOW_DAYS)
        if result["missing"]:
            logger.warning("themes: %d codes in themes.txt have no bars: %s", len(result["missing"]), " ".join(result["missing"]))
        hot = [f"{t['name']}:{t['state']}{'$' if t['flow'] else ''}" for t in result["themes"] if t["state"]]
        logger.info("themes: %d themes, hot: %s", len(result["themes"]), " / ".join(hot) or "-")
        return result, moves
    except Exception:
        logger.exception("テーマを作れませんでした（テーマなしで公開します）")
        return None, None


def _reasons(args, st, now: pd.Timestamp, keeping: bool = False, theme_moves: dict | None = None):
    """値動きの理由。材料が取れなくても、株価と指標の公開は止めない。

    戻り値は (理由, 取得した材料の pickle)。pickle は --keep 用で、計算に渡す前の状態を残す。
    """
    try:
        ex = _load_extras(args, st.panel.dates, now)
    except Exception:
        logger.exception("値動きの理由の材料を取得できませんでした（理由なしで公開します）")
        return None, None
    snapshot = pickle.dumps(ex, protocol=pickle.HIGHEST_PROTOCOL) if keeping else None
    try:
        rs = reasons.compute(st.panel, st.base, ex, now, session=st.session, theme_moves=theme_moves)
        logger.info("reasons: %s", json.dumps(reasons.brief(rs.status), ensure_ascii=False))
        return rs, snapshot
    except Exception:
        logger.exception("値動きの理由を作れませんでした（理由なしで公開します）")
        return None, snapshot


def _disclosure_start(dates: pd.DatetimeIndex, now: pd.Timestamp):
    """開示を取る最初の日: 判定する最も古い日の、前の取引日の引け後から（銘柄詳細の一覧用に30日前からも）。"""
    return min(dates[-reasons.WINDOW_DAYS - 1].date(), (now - pd.Timedelta(days=reasons.LIST_DAYS)).date())


def refresh_disclosures(ex: reasons.Extras, dates: pd.DatetimeIndex, now: pd.Timestamp) -> None:
    """開示だけ取り直す（--light）。

    株価と一緒に取得した開示は、その時刻までの分しか無い。その日から今日までを取り直して入れ替え、前には
    無かったものを新着として見分けられるようにする（ex.seen）。一度も取得できていなければ、全体の更新と同じ
    範囲を取る。取得できない日がある・前に取れていた開示が大きく減っているときは例外にする（公開しない）。
    """
    old = ex.disclosures if ex.disclosures is not None else pd.DataFrame(columns=["time", "code", "title", "url"])
    at = ex.disclosures_at if ex.disclosures is not None else None      # None = 前に取得できていない
    # 前に取得した日から取り直す。日付が変わった直後に取得していたら、前の日も取り直す（API への反映は
    # 数分遅れるので、23時台の終わりに出た開示を取りこぼしているかもしれない）
    since = (at - pd.Timedelta(minutes=30)).date() if at is not None else _disclosure_start(dates, now)
    new, ok = fetch.fetch_disclosures(since, now.date())
    missing = [str(d.date()) for d in pd.date_range(since, now.date()) if d.date() not in ok]
    if missing:
        raise RuntimeError(f"開示を取得できない日があります（{'・'.join(missing)}）")
    recent = pd.to_datetime(old["time"]).dt.date >= since       # 取り直した日の、前の取得分
    again = set(reasons.disclosure_keys(old[recent]))
    lost = again - set(reasons.disclosure_keys(new))
    if len(lost) > max(MAX_LOST_SHARE * len(again), 5):
        raise RuntimeError(f"取り直した開示が前より少なすぎます（前の {len(again)} 件のうち {len(lost)} 件が無い）")
    # 新着を見分けるのは、前に取得できていたときだけ（取得できていなかったら、すべてが新着になってしまう）
    ex.seen, ex.seen_at = (set(reasons.disclosure_keys(old)), at) if at is not None else (None, None)
    parts = [x for x in (old[~recent], new) if len(x)]
    ex.disclosures = pd.concat(parts, ignore_index=True) if parts else new
    ex.disclosure_days = set(ex.disclosure_days) | ok
    ex.disclosures_at = now
    ex.errors.pop("disclosures", None)
    fresh = len(set(reasons.disclosure_keys(new)) - ex.seen) if ex.seen is not None else "-"
    logger.info("disclosures: refetched %s..%s, %d items, new since %s: %s, gone: %d of %d",
                since, now.date(), len(new), at, fresh, len(lost), len(again))


def _load_extras(args, dates: pd.DatetimeIndex, now: pd.Timestamp) -> reasons.Extras:
    cache = Path(args.cache).with_name("extras.pkl") if args.cache else None
    if cache and cache.exists():
        logger.info("loading cache %s", cache)
        return pd.read_pickle(cache)
    ex = reasons.Extras()
    try:
        ex.disclosures, ex.disclosure_days = fetch.fetch_disclosures(_disclosure_start(dates, now), now.date())
        ex.disclosures_at = now
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
