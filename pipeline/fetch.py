"""データの取得。どちらも登録・APIキー不要。

- 銘柄一覧: JPX の「東証上場銘柄一覧」（Excel）。銘柄名・市場区分・33業種
- 日足: yfinance（Yahoo Finance の非公式API）。**毎回2年分を取り直す**

毎回取り直すのは、差分だけ足していくと株式分割の調整が取得の時期ごとにずれて
価格に段差が残るため（Stock Advisor で実際に起きた）。取得時間はリクエストの回数で
決まり、期間の長さではほとんど変わらない（200銘柄で 1か月分 8.7秒、1年分 6.6秒）。
2年分あると、検証（指標がその後のリターンを説明できたか）の期間を1年半取れる。

Yahoo はクラウドからの大量アクセスを一時的に断ることがある（HTTP 429）。
その場合は時間を置いてやり直し、それでも取れなかった銘柄は諦めて記録する。
"""
import io
import logging
import re
import time
import urllib.request

import pandas as pd

logger = logging.getLogger(__name__)

# 銘柄一覧のファイルは置き場所や形式が変わることがある（2026-09 に .xls → .xlsx に変わり、
# 古いURLは 404 になった）。一覧ページからその時点のリンクを探し、見つからなければ既知のURLを使う
JPX_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
JPX_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xlsx"
# ETFやREITなど、個別株でないものは除外する
EXCLUDED_MARKETS = ("ETF", "ETN", "REIT", "出資証券", "インフラファンド", "PRO Market")

PERIOD = "2y"
BATCH_SIZE = 200
RETRY_WAITS = (15, 60, 180)    # 取れなかった分を取り直すまでの待ち時間（秒）
BATCH_PAUSE = 1.0              # バッチの間の小休止（連続アクセスを和らげる）


def fetch_master(timeout: int = 120) -> pd.DataFrame:
    """JPX の銘柄一覧（個別株のみ）。列: code, name, market, sector33, sector17, scale"""
    url = _jpx_file_url(timeout)
    content = _get(url, timeout)
    df = pd.read_excel(io.BytesIO(content), dtype=str)   # .xls / .xlsx は中身から判別される
    required = {"コード", "銘柄名", "市場・商品区分", "33業種区分", "17業種区分"}
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"JPXのファイル形式が変わっています（不足列: {missing}）")

    rows = []
    for d in df.to_dict("records"):
        code = str(d.get("コード") or "").strip()
        market = str(d.get("市場・商品区分") or "").strip()
        if not code or not market or market == "-" or any(x in market for x in EXCLUDED_MARKETS):
            continue
        rows.append({
            "code": code,
            "name": str(d.get("銘柄名") or "").strip(),
            "market": market,
            "sector33": _clean(d.get("33業種区分")),
            "sector17": _clean(d.get("17業種区分")),
            "scale": _clean(d.get("規模区分")),
        })
    logger.info("JPX master: %d stocks", len(rows))
    return pd.DataFrame(rows)


def _get(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _jpx_file_url(timeout: int) -> str:
    try:
        html = _get(JPX_PAGE, timeout).decode("utf-8", "replace")
        m = re.search(r'href="([^"]*data_j\.xlsx?)"', html)
        if m:
            href = m.group(1)
            return href if href.startswith("http") else "https://www.jpx.co.jp" + href
        logger.warning("JPX page has no data_j link; using the known URL")
    except Exception as e:
        logger.warning("JPX page failed (%s); using the known URL", e)
    return JPX_URL


def _clean(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return None if s in ("", "-", "nan") else s


def fetch_bars(codes: list[str], period: str = PERIOD) -> tuple[pd.DataFrame, list[str]]:
    """全銘柄の日足。戻り値は (縦持ちの日足, 取れなかった銘柄)。"""
    parts: list[pd.DataFrame] = []
    pending = list(codes)
    for attempt, wait in enumerate((0,) + RETRY_WAITS):
        if not pending:
            break
        if wait:
            logger.warning("retrying %d stocks after %ds (attempt %d)", len(pending), wait, attempt + 1)
            time.sleep(wait)
        still = []
        for i in range(0, len(pending), BATCH_SIZE):
            batch = pending[i:i + BATCH_SIZE]
            got = _download(batch, period)
            if not got.empty:
                parts.append(got)
            done = set(got["code"].unique()) if not got.empty else set()
            still += [c for c in batch if c not in done]
            time.sleep(BATCH_PAUSE)
        logger.info("fetched %d / %d stocks", len(pending) - len(still), len(pending))
        pending = still
    bars = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(
        columns=["date", "code", "open", "high", "low", "close", "volume"])
    return bars, pending


def _download(codes: list[str], period: str) -> pd.DataFrame:
    import yfinance as yf

    symbols = {f"{c}.T": c for c in codes}
    try:
        df = yf.download(list(symbols), period=period, interval="1d", auto_adjust=False,
                         progress=False, group_by="ticker", threads=True)
    except Exception as e:   # レート制限などはまとめて取り直しに回す
        logger.warning("download failed for %d stocks: %s", len(codes), e)
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    out = []
    for sym, code in symbols.items():
        try:
            sub = df[sym] if isinstance(df.columns, pd.MultiIndex) else df
        except KeyError:
            continue
        sub = sub.dropna(subset=["Close"])
        if sub.empty:
            continue
        out.append(pd.DataFrame({
            "date": sub.index.strftime("%Y-%m-%d"),
            "code": code,
            "open": sub["Open"].to_numpy(dtype=float),
            "high": sub["High"].to_numpy(dtype=float),
            "low": sub["Low"].to_numpy(dtype=float),
            "close": sub["Close"].to_numpy(dtype=float),
            "volume": sub["Volume"].fillna(0).to_numpy(dtype=float),
        }))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def fetch_index(symbol: str = "^N225", period: str = PERIOD) -> pd.Series:
    """指数の終値（日付の昇順）。"""
    import yfinance as yf

    for wait in (0,) + RETRY_WAITS:
        if wait:
            time.sleep(wait)
        try:
            h = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=False)
        except Exception as e:
            logger.warning("index %s failed: %s", symbol, e)
            continue
        if h is not None and not h.empty:
            s = h["Close"].dropna()
            s.index = pd.to_datetime(s.index.strftime("%Y-%m-%d"))
            return s.sort_index()
    logger.warning("index %s: no data", symbol)
    return pd.Series(dtype=float)
