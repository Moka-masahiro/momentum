"""データの取得。どれも登録・APIキー不要。

- 銘柄一覧: JPX の「東証上場銘柄一覧」（Excel）。銘柄名・市場区分・33業種
- 日足: yfinance（Yahoo Finance の非公式API）。**毎回2年分を取り直す**
- 値動きの理由の手がかり（取れなくても本体は公開する。下の節を参照）

毎回取り直すのは、差分だけ足していくと株式分割の調整が取得の時期ごとにずれて
価格に段差が残るため（Stock Advisor で実際に起きた）。取得時間はリクエストの回数で
決まり、期間の長さではほとんど変わらない（200銘柄で 1か月分 8.7秒、1年分 6.6秒）。
2年分あると、検証（指標がその後のリターンを説明できたか）の期間を1年半取れる。

Yahoo はクラウドからの大量アクセスを一時的に断ることがある（HTTP 429）。
その場合は時間を置いてやり直し、それでも取れなかった銘柄は諦めて記録する。
"""
import html
import io
import json
import logging
import re
import time
import urllib.request
from datetime import date, timedelta

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


# --- 値動きの理由の手がかり ------------------------------------------------------
# どれも取れなかったら無しで続ける（株価と指標は公開する）。画面には「取得できず」と出す。
#
# 適時開示: 東証の TDnet は robots.txt で自動取得をすべて禁止しているので、直接は取りに行かない。
# 「やのしん TDnet WEB-API」（個人運営の無料API。情報収集・分析目的の利用を想定している）から取る。
# 期間をまとめて頼むと、件数が多いとき（決算期の1か月など）に空の結果が返るので、1日ずつ取る。
# 1日の件数は多い日でも3,000件弱（2026-02-13 で 2,694件）。
TDNET_API = "https://webapi.yanoshin.jp/webapi/tdnet/list/{day}.json?limit=5000"
TDNET_PAUSE = 0.3
TDNET_PDF = "https://www.release.tdnet.info/inbs/"

# JPX の公表ファイル（どれも Excel。ページからその時点のリンクを探す）
SHORT_PAGE = "https://www.jpx.co.jp/markets/public/short-selling/index.html"       # 空売り残高（毎日）
FLAGS_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/margin/index.html"  # 日々公表銘柄等（毎日）
PREMIUM_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/margin/01.html"   # 品貸料＝逆日歩（毎日）
SHORT_FILES = 5    # 空売り残高は「その日に届いた報告」だけが載るので、数日分を合わせて見る


def code4(v) -> str | None:
    """証券コードを4文字にそろえる（TDnet・JPX の5桁 "72030"・"464A0" → "7203"・"464A"）。"""
    if v is None:
        return None
    s = str(v).strip().upper()
    if s.endswith(".0"):
        s = s[:-2]
    if len(s) == 5 and s.endswith("0"):
        s = s[:4]
    return s if re.fullmatch(r"\d{3}[0-9A-Z]", s) else None


def fetch_disclosures(start: date, end: date, timeout: int = 60) -> tuple[pd.DataFrame, set[date]]:
    """start〜end（暦日）の適時開示。戻り値は (開示の一覧, 取得できた日の集合)。

    一覧の列: time（日本時間）, code, title, url（TDnet の PDF。無ければ None）
    """
    rows: list[dict] = []
    ok: set[date] = set()
    day = start
    while day <= end:
        url = TDNET_API.format(day=day.strftime("%Y%m%d"))
        for attempt in range(2):
            try:
                rows += parse_disclosures(json.loads(_get(url, timeout)))
                ok.add(day)
                break
            except Exception as e:  # その日だけ諦める（その日を含む判定は「未判定」になる）
                if attempt:
                    logger.warning("disclosures %s failed: %s", day, e)
                else:
                    time.sleep(5)
        time.sleep(TDNET_PAUSE)
        day += timedelta(days=1)
    logger.info("disclosures: %d items, %d/%d days", len(rows), len(ok), (end - start).days + 1)
    return pd.DataFrame(rows, columns=["time", "code", "title", "url"]), ok


def parse_disclosures(doc: dict) -> list[dict]:
    """やのしん API の応答を行のリストにする。

    - 各行が {"Tdnet": {...}} で包まれている日と、包まれていない日がある（2026-08-06 は後者）
    - 件数が多すぎると total_count=1 で items が空になる。件数が合わなければ失敗にする
    """
    items = doc.get("items") or []
    total = doc.get("total_count")
    if total is not None and int(total) != len(items):
        raise ValueError(f"件数が合いません（total_count={total}, items={len(items)}）")
    out = []
    for x in items:
        t = x.get("Tdnet", x) if isinstance(x, dict) else None
        if not isinstance(t, dict):
            continue
        code = code4(t.get("company_code"))     # ETF・ETN（末尾が0以外の5桁）はここで落ちる
        title = html.unescape(str(t.get("title") or "")).strip()   # "S&amp;P500" のような表記を戻す
        when = pd.to_datetime(t.get("pubdate"), errors="coerce")
        if code and title and not pd.isna(when):
            out.append({"time": when, "code": code, "title": title, "url": _tdnet_url(t.get("document_url"))})
    return out


def _tdnet_url(u) -> str | None:
    """PDF のリンク。API の転送用URL（rd.php?…）は外して TDnet を直接指す。TDnet 以外は使わない。"""
    if not isinstance(u, str):
        return None
    u = u.split("rd.php?", 1)[-1]
    return u if u.startswith(TDNET_PDF) else None


def _jpx_links(page: str, pattern: str, timeout: int) -> list[str]:
    text = _get(page, timeout).decode("utf-8", "replace")
    links = dict.fromkeys(re.findall(rf'href="([^"]*{pattern})"', text))
    return [h if h.startswith("http") else "https://www.jpx.co.jp" + h for h in links]


def _excel(url: str, timeout: int) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(_get(url, timeout)), header=None, dtype=str)


def _header_row(raw: pd.DataFrame, *names: str) -> tuple[int, dict[str, int]]:
    """見出しの行を探し、{見出し（空白を除いたもの）: 列番号} を返す。形式が変わったら例外。"""
    for i in range(min(len(raw), 30)):
        cells = {re.sub(r"\s+", "", str(v)): j for j, v in enumerate(raw.iloc[i]) if isinstance(v, str)}
        if all(any(n in k for k in cells) for n in names):
            return i, cells
    raise RuntimeError(f"見出しが見つかりません（形式が変わった可能性）: {names}")


def _col(cells: dict[str, int], name: str, exact: bool = False) -> int:
    for k, j in cells.items():
        if (k == name) if exact else (name in k):
            return j
    raise RuntimeError(f"列が見つかりません: {name}")


def fetch_short_positions(timeout: int = 60) -> pd.DataFrame:
    """直近数日分の空売り残高の報告（発行済株式の0.5%以上の空売りをしている機関ごと）。"""
    links = _jpx_links(SHORT_PAGE, r"\d{8}_Short_Positions\.xlsx?", timeout)
    links = sorted(links, key=lambda u: re.search(r"(\d{8})_Short", u).group(1), reverse=True)[:SHORT_FILES]
    if not links:
        raise RuntimeError("空売り残高のファイルが見つかりません")
    parts = [parse_short_positions(_excel(u, timeout)) for u in links]
    df = pd.concat(parts, ignore_index=True).drop_duplicates(["code", "holder", "calc_date"])
    logger.info("short positions: %d reports from %d files", len(df), len(links))
    return df


def parse_short_positions(raw: pd.DataFrame) -> pd.DataFrame:
    """列: code, holder, calc_date, ratio, prev_ratio（割合は小数。0.0498 = 4.98%）"""
    i, cells = _header_row(raw, "銘柄コード", "空売り残高割合", "直近空売り残高割合")
    cols = {
        "calc_date": _col(cells, "計算年月日", exact=True),
        "code": _col(cells, "銘柄コード"),
        "holder": _col(cells, "商号・名称・氏名", exact=True),
        "ratio": _col(cells, "空売り残高割合", exact=True),
        "prev_ratio": _col(cells, "直近空売り残高割合", exact=True),
    }
    body = raw.iloc[i + 1:, list(cols.values())]
    body.columns = list(cols)
    body = body.assign(code=body["code"].map(code4)).dropna(subset=["code", "holder"])
    return pd.DataFrame({
        "code": body["code"],
        "holder": body["holder"].str.strip(),
        "calc_date": pd.to_datetime(body["calc_date"], errors="coerce"),
        "ratio": pd.to_numeric(body["ratio"], errors="coerce"),
        "prev_ratio": pd.to_numeric(body["prev_ratio"], errors="coerce"),
    }).dropna(subset=["calc_date", "ratio"]).reset_index(drop=True)


def fetch_margin_flags(timeout: int = 60) -> tuple[pd.DataFrame, str | None]:
    """信用取引の規制・日々公表などの対象銘柄（JPX「日々公表銘柄等信用取引残高」）。

    戻り値は (列 code, flags の表, 申込日)。2026-09-28 に表題と形式（.xls → .xlsx）が変わるが、
    データ部分は変わらないと告知されている。列の位置に頼らず、ISIN の手前の列から読む。
    """
    links = _jpx_links(FLAGS_PAGE, r"\.xlsx?", timeout)
    if not links:
        raise RuntimeError("日々公表銘柄等のファイルが見つかりません")
    raw = _excel(links[0], timeout)
    return parse_margin_flags(raw), _as_of(raw)


FLAG_CHARS = set("規日監株喚○")


def parse_margin_flags(raw: pd.DataFrame) -> pd.DataFrame:
    """列: code, flags（"規日" のような文字列）

    各行は [単位, 印, 印, 銘柄名, 市場, 銘柄種別, コード(5桁), ISIN, 残高…]。
    印は「規」規制・「日」日々公表・「監」売買監理・「株」日証金の貸株申込制限・
    「喚」日証金の貸株注意喚起・「○」取引所の注意喚起。銘柄名にも「日」「株」が入るので、
    コードより前の**印と単位の英字だけでできたセル**から拾う。
    """
    rows = []
    for vals in raw.itertuples(index=False):
        cells = ["" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip() for v in vals]
        k = next((j for j, s in enumerate(cells) if re.fullmatch(r"JP[0-9A-Z]{10}", s)), None)
        if k is None or k == 0:
            continue
        code = code4(cells[k - 1])
        if not code:
            continue
        marks = "".join(ch for s in cells[:k - 1]
                        if s and len(s) <= 6 and all(ch in FLAG_CHARS or ch.isascii() for ch in s)
                        for ch in s if ch in FLAG_CHARS)
        rows.append({"code": code, "flags": "".join(dict.fromkeys(marks))})
    if not rows:
        raise RuntimeError("日々公表銘柄等のファイルに銘柄の行がありません（形式が変わった可能性）")
    return pd.DataFrame(rows).drop_duplicates("code")


def fetch_premium(timeout: int = 60) -> pd.DataFrame:
    """品貸料（逆日歩）。列: code, date, rate（1株1日あたりの円）, max_rate"""
    links = _jpx_links(PREMIUM_PAGE, r"Premium_Charges\.xlsx?", timeout)
    if not links:
        raise RuntimeError("品貸料のファイルが見つかりません")
    return parse_premium(_excel(links[0], timeout))


def parse_premium(raw: pd.DataFrame) -> pd.DataFrame:
    i, cells = _header_row(raw, "コード", "品貸料率", "最高料率")
    cols = {
        "date": _col(cells, "約定日"),
        "code": _col(cells, "コード"),
        "max_rate": _col(cells, "最高料率"),
        "rate": next(j for k, j in cells.items() if "品貸料率" in k and "最高" not in k),
    }
    body = raw.iloc[i + 1:, list(cols.values())]
    body.columns = list(cols)
    out = pd.DataFrame({
        "code": body["code"].map(code4),
        "date": pd.to_datetime(body["date"], format="%Y%m%d", errors="coerce"),
        "rate": pd.to_numeric(body["rate"], errors="coerce"),        # "*****" は貸株超過なし
        "max_rate": pd.to_numeric(body["max_rate"], errors="coerce"),
    })
    return out.dropna(subset=["code"]).reset_index(drop=True)


def _as_of(raw: pd.DataFrame) -> str | None:
    """表の上にある申込日（"as of 2026/9/24 application based" / "2026/10/2 申込み現在"）。"""
    for v in raw.iloc[:6].to_numpy().ravel():
        if not isinstance(v, str):
            continue
        m = re.search(r"as of\s*(\d{4})/(\d{1,2})/(\d{1,2})", v) or re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})\s*申込", v)
        if m:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None
