"""値動きの理由の手がかり: ニュース（会社の開示）／需給／地合い／材料不明。

その日に**目立って動いた**銘柄にだけ付ける。目立った動き＝業種の中央値との差（その銘柄だけの
動き）が普段の3倍以上、または出来高が20日平均の3倍以上。
実測（流動性のある銘柄・2026-08-04〜09-25 の35営業日）では、業種との差が普段の3〜4倍の日の36%、
4〜6倍の61%、6倍以上の76%に会社の開示があった（普通の日は4%）。裏を返すと、大きく動いた
銘柄でも2〜6割には開示が無い。

判定は上から順に当てはめる。

1. 地合い   … 業種全体が同じ向きに大きく動き、この銘柄だけの動きは目立たない
2. ニュース … 前に売買が成立した日の引け（15:30）から当日の引けまでに、会社の開示がある。
               増資・自社株買いのように株の需給に関わる開示だけなら「需給」にする
               （実例: 清水建設 2026-09-25 の −6% は転換社債の発行）
   地合い   … 開示は無いが、同じ業種の他の銘柄もそろって同じ向きに大きく動いた（テーマ・連れ高）
3. 需給     … 開示は無いが、需給の手がかりがある
               ・出来高が急増したのに値動きは小さい（指数の入れ替え・大口の売買で起きやすい形）
               ・信用取引の規制・日々公表の対象（過熱のサイン。最新日だけ）
               ・機関の空売り残高が、値動きと同じ向きに大きく増減した（最新日だけ）
               ・信用残が重く、値動きを強める向きにある（下げた日の買い残・上げた日の売り残。最新日だけ）
               ・3月末・9月末の権利落ち日の下げ
4. 材料不明 … どれにも当たらない

限界
- ニュースは**会社の適時開示だけ**。新聞報道・アナリストの格付け・テーマ買いは拾えない
  （報道を無料で自動取得してよい入手先が無い）。会社が「一部報道について」を出したときだけ、
  報道が理由だとわかる
- 需給の手がかりは状況証拠で、原因の証明ではない
- 逆日歩は、権利取りの時期に優待目当てのつなぎ売りでも付くので、判定には使わず表示だけにする
- 開示が取れなかった日を含むときは判定しない（開示があったのに「材料不明」と出さないため）
"""
import re
import unicodedata
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import indicators as ind

# --- 目立った動き --------------------------------------------------------------
NOTABLE_Z = 3.0            # 業種との差が普段（直近60日の業種との差のばらつき）の3倍以上
NOTABLE_VR = 3.0           # 出来高が直前20日平均の3倍以上
# 昼の実行（前場の引け後）は、当日の出来高が前場の分だけ。実測（流動性のある200銘柄×18日、2026-08-31〜09-28）で
# 前場は1日の出来高の中央値48%（4分の1〜4分の3の範囲で40〜56%）だったので、前場だけで1日平均の1.5倍＝
# ふだんのペースの約3倍を同じ目安にする。取引時間中の途中の値（intraday）は割合が決まらないので出来高では見ない
NOTABLE_VR_AM = 1.5
AM_SHARE = 0.48
AM_CLOSE = pd.Timedelta(hours=11, minutes=30)   # 前場の引け。昼の実行では、これ以降の開示は後場の材料
NOTABLE_IDIO = 0.07        # 上場直後などで普段の値動きが測れないときは、業種との差7%以上
SIGMA_DAYS = 60
SIGMA_MIN = 40
SIGMA_FLOOR = 0.005        # 値動きが極端に小さい銘柄で倍率が暴れないための下限（日次0.5%）
MIN_SECTOR = 5             # 業種の銘柄がこれ未満の日は、市場全体の中央値と比べる

# --- 地合い --------------------------------------------------------------------
MARKET_RET = 0.03          # 当日の騰落率が±3%以上で、
MARKET_SECTOR = 0.015      # 業種全体も同じ向きに±1.5%以上動き、この銘柄だけの動きは目立たない
# 業種の一部がまとめて動いた日（テーマ・連れ高）。業種全体の中央値は動かないので上の条件には当たらない。
# 実例: 2026-09-18 は銀行業の中央値が +0.2% なのに、地銀11行が普段の2倍以上そろって上げた。
# 同じ業種で、普段の2倍以上を同じ向きに動いた銘柄が「3銘柄以上かつ業種の1割以上」いれば連れとみなす
# （偶然に同じ向きへ2倍以上動くのは1銘柄あたり2%ほどなので、1割はまず偶然では届かない）
GROUP_Z = 2.0
GROUP_MIN = 3
GROUP_SHARE = 0.10

# --- 需給の手がかり --------------------------------------------------------------
QUIET_Z = 2.0              # 出来高型: 出来高は3倍以上なのに、業種との差は普段の2倍未満で、
QUIET_RET = 0.02           # 騰落率も±2%未満
SHORT_CHANGE = 0.5         # 機関の空売り残高（報告分）の増減（ポイント）
SHORT_RECENT = pd.Timedelta(days=4)   # 手がかりに使う報告の新しさ（報告は計算日の翌営業日ごろ届く）
# 信用残（JPX「銘柄別信用取引残高」。最新の申込日の分だけ）。上位1割に入る重さで、値動きを強める向きのものだけを
# 手がかりにする。実測（2026-09-25 申込み分・流動性のある1,922銘柄）: 買い残÷20日平均出来高は中央値1.1日・
# 上位1割5.7日、売り残÷出来高は中央値0.1日・上位1割1.5日、信用倍率1倍以下（売り長）は12%
MARGIN_LONG_DAYS = 5.0     # 下げた日: 信用買い残が出来高の5日分以上（値下がりで投げ売りが出やすい）
MARGIN_LONG_RATIO = 2.0    #          かつ信用倍率2倍以上（買い長）。売り残も同じくらい多いなら、投げ一方とは言えない
MARGIN_SHORT_DAYS = 1.5    # 上げた日: 信用売り残が出来高の1.5日分以上（値上がりで買い戻し＝踏み上げが入りやすい）
MARGIN_SHORT_RATIO = 1.5   #          かつ信用倍率1.5倍以下（拮抗〜売り長）。アツギ 2026-09-28 は売り残が出来高の
                           #          2.6日分でも買い残がその5.4倍あり（買い長）、踏み上げとは言いにくかった
FLAG_NAMES = {"規": "信用取引の規制", "日": "日々公表銘柄", "株": "日証金の貸株申込制限",
              "喚": "日証金の貸株注意喚起", "監": "売買監理銘柄", "○": "取引所の注意喚起"}
HEAT_FLAGS = "規日株喚"     # 需給の手がかりに使う印（監・○は表示だけ）
EX_RIGHTS_MONTHS = (3, 9)  # 権利落ちで下げる銘柄が多い月（3月・9月決算と中間の基準日）

CLOSE = pd.Timedelta(hours=15, minutes=30)   # 東証の大引け（2024-11-05 から。それ以前は15:00）
WINDOW_DAYS = 20           # 判定する取引日数（シグナル画面と同じ）
LIST_DAYS = 30             # 銘柄詳細に出す開示の日数（暦日。TDnet の PDF は31日で消える）

LABELS = {"news": "ニュース", "supply": "需給", "market": "地合い", "unknown": "材料不明"}

# --- 開示の表題の分類 --------------------------------------------------------------
# (表題の正規表現, 分類, 種類, 一覧に出す短い文言)。上から順に当てはめる（順番に意味がある）。
# 種類: news = 業績・事業のニュース / supply = 株の需給に関わる開示 / routine = 定例（理由にしない）
# 文言が None のものは表題を縮めて出す。表題は NFKC で半角にそろえてから当てる。
_RULES = [
    (r"訂正|差替", "訂正", "routine", None),
    (r"一部報道|報道について|報道に関する|報道の件", "報道への回答", "news", "一部報道について"),
    (r"自己株式.*公開買付", "自社株買い", "supply", "自社株の公開買付け"),
    (r"公開買付|TOB|MBO|マネジメント・バイアウト", "TOB・M&A", "news", "TOB(公開買付け)"),
    (r"^(?!.*(拡大|決定|追加|実施)).*自己株式.*(取得状況|取得結果|買付結果|取得終了|消却)", "定例", "routine", None),
    (r"自己株式.*(取得|買付)|自社株買", "自社株買い", "supply", "自社株買い"),
    # 役員・従業員への報酬としての株の交付。「自己株式の処分」「株式取得」「新株予約権の行使」の言葉を含むので、
    # 後ろの増資・M&A の規則より先に定例にする（2026-09〜10 の実測で157件。うち141件が増資・売出しになっていた）
    # 「持株会社」（再編のニュース）は含めない: 共同持株会社の設立まで定例になった
    (r"株式報酬|譲渡制限付|ストック・?オプション|持株会(?!社)|株式給付|株式交付信託|ESOP|BIP信託", "定例", "routine", None),
    (r"自己株式.*処分", "増資・売出し", "supply", "自己株式の処分"),
    (r"株式交換|株式移転|合併|会社分割|吸収分割|事業譲渡|事業譲受|事業の譲|子会社化|子会社の異動|"
     r"株式の取得|株式取得|持分法|資本業務提携|資本提携|親会社の異動|その他の関係会社の異動|株式併合",
     "TOB・M&A", "news", None),
    (r"転換社債|新株予約権付社債", "増資・売出し", "supply", "転換社債の発行"),
    (r"行使価額修正|MSワラント|MS型|新株予約権.*(行使|第三者割当)|第三者割当.*新株予約権",
     "増資・売出し", "supply", "新株予約権(希薄化)"),
    (r"第三者割当", "増資・売出し", "supply", "第三者割当"),
    (r"公募|新株式発行|新株式の発行|募集株式|増資", "増資・売出し", "supply", "増資"),
    (r"売出|立会外分売", "増資・売出し", "supply", "株式の売出し・分売"),
    (r"上方修正", "業績修正", "news", "業績予想の上方修正"),
    (r"下方修正", "業績修正", "news", "業績予想の下方修正"),
    (r"業績予想|業績見通し|業績目標|業績見込|通期見通し", "業績修正", "news", "業績予想の修正"),
    (r"特別利益|特別損失|減損|営業外", "業績修正", "news", None),
    (r"決算短信|四半期決算|決算説明|決算補足|業績補足|決算発表|決算の概要|決算のお知らせ", "決算", "news", "決算発表"),
    (r"増配|記念配当|特別配当|復配", "配当", "news", "増配"),
    (r"減配|無配", "配当", "news", "減配・無配"),
    (r"剰余金の配当", "定例", "routine", None),
    (r"配当", "配当", "news", "配当予想の修正"),
    (r"株式分割", "株式分割", "news", "株式分割"),
    (r"株主優待", "株主優待", "news", "株主優待の新設・変更"),
    (r"上場廃止|監理銘柄|整理銘柄|特別注意|債務超過|継続企業の前提|不適切|第三者委員会|調査委員会|"
     r"特別調査|延期|提出期限", "上場維持・会計", "news", None),
    (r"訴訟|判決|提訴|仲裁|和解|行政処分|課徴金|事故|火災|不正アクセス|サイバー|ランサム|システム障害|"
     r"リコール|業務停止|破産|民事再生|更生手続", "訴訟・事故等", "news", None),
    (r"主要株主|筆頭株主|大株主", "大株主の異動", "supply", "大株主の異動"),
    (r"市場変更|市場区分|上場市場", "上場市場の変更", "news", "上場市場の変更"),
    (r"代表取締役の異動|社長の異動|代表者の異動|社長交代", "代表の交代", "news", "社長・代表の交代"),
    (r"月次|月度|売上速報|営業概況|営業状況|販売実績|受注状況", "月次", "news", "月次の業績"),
    (r"受注|契約|提携|採択|承認|認可|特許|共同開発|共同研究|新製品|新サービス|発売|提供開始|出店|"
     r"治験|臨床試験|協定|合意", "受注・提携等", "news", None),
    # 信用取引で売れる銘柄になる（外れる）知らせ。会社の業績ではなく需給の話
    (r"貸借銘柄|制度信用銘柄", "貸借銘柄", "supply", "貸借銘柄の選定・解除"),
    (r"コーポレート・ガバナンス|独立役員|招集|定款|株主総会|支配株主等に関する事項|親会社等の決算|内部統制|"
     r"有価証券報告書|半期報告書|報告書の提出|英文|資本コスト|サステナビリティ|統合報告|ESG|健康経営|"
     r"成長可能性に関する|投資家の皆さま|説明会|ストック・オプション|ストックオプション|株式報酬|"
     r"譲渡制限付株式|資本準備金|役員の異動|執行役員|人事異動|組織変更|機構改革|本店|商号|基準日|行使状況|"
     # 一覧にして分かった定例（2026-09〜10 の「その他」588件のうち約100件）: 説明会の質疑・FAQ、委員会、役員人事
     r"質疑応答|ご質問|FAQ|Q&A|委員会.*(委員|設置|移行)|役員人事|取締役候補|監査役の|補欠監査役|役員退職慰労金|会社説明資料",
     "定例", "routine", None),
]
_COMPILED = [(re.compile(p), cat, kind, text) for p, cat, kind, text in _RULES]

# 同じ窓に複数の開示があるとき、一覧に出す見出しをどれにするか（前ほど優先）
_PRIORITY = ["TOB・M&A", "業績修正", "決算", "報道への回答", "上場維持・会計", "訴訟・事故等", "配当",
             "受注・提携等", "株式分割", "株主優待", "上場市場の変更", "代表の交代", "月次", "その他",
             "増資・売出し", "自社株買い", "大株主の異動", "貸借銘柄"]


def classify(title: str) -> tuple[str, str, str]:
    """開示の表題 → (分類, 種類, 一覧に出す短い文言)。"""
    t = unicodedata.normalize("NFKC", title)
    for rx, cat, kind, text in _COMPILED:
        if rx.search(t):
            return cat, kind, text or short_title(title)
    return "その他", "news", short_title(title)


def short_title(t: str) -> str:
    """表題を一覧向けに縮める（「〜に関するお知らせ」や決算期などを落とす）。"""
    s = re.sub(r"^[（(【〈][^）)】〉]{1,15}[）)】〉]\s*", "", t.strip())
    s = re.sub(r"^\d{4}\s*年\s*[0-9０-９]{1,2}\s*月期\s*", "", s)
    s = re.sub(r"(に関する|についての|に係る|に関しての)?(お知らせ|ご案内)$", "", s)
    s = re.sub(r"(について|の件)$", "", s)
    return s.strip(" 　") or t


def effective_day(times: pd.Series, dates: pd.DatetimeIndex) -> pd.Series:
    """開示が効く取引日。引け（15:30）以降・休日の開示は次の取引日。その日がまだ来ていなければ NaT。"""
    t = pd.to_datetime(times)
    day = t.dt.normalize() + pd.to_timedelta((t - t.dt.normalize() >= CLOSE).astype(int), unit="D")
    pos = dates.searchsorted(pd.DatetimeIndex(day))
    out = pd.Series(pd.NaT, index=times.index, dtype=dates.dtype)
    ok = pos < len(dates)
    out[ok] = dates[pos[ok]]
    return out


def _month_days(d: pd.Timestamp, dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """d の月の取引日。月末までの取引日がまだデータに無いときは、土日だけを休みとして数える
    （3月末・9月末の数日に祝日は来ない）。"""
    end = d + pd.offsets.MonthEnd(0)
    known = dates[(dates >= d.replace(day=1)) & (dates <= end)]
    future = pd.bdate_range(dates[-1] + pd.Timedelta(days=1), end) if dates[-1] < end else pd.DatetimeIndex([])
    return known.union(future)


def is_ex_rights(d: pd.Timestamp, dates: pd.DatetimeIndex) -> bool:
    """3月末・9月末の権利落ち日か（その月の最後から2番目の取引日）。"""
    if d.month not in EX_RIGHTS_MONTHS:
        return False
    days = _month_days(d, dates)
    return len(days) >= 2 and d == days[-2]


def is_last_with_rights(d: pd.Timestamp, dates: pd.DatetimeIndex) -> bool:
    """3月末・9月末の権利付き最終日か（権利落ち日の前の取引日＝最後から3番目の取引日）。
    配当・優待を得るための売買で出来高が膨らむ（2026-09-28 は流動性のある銘柄の70銘柄が出来高急増・値動き小）。"""
    if d.month not in EX_RIGHTS_MONTHS:
        return False
    days = _month_days(d, dates)
    return len(days) >= 3 and d == days[-3]


@dataclass
class Extras:
    """値動きの理由の材料（build.py が取得する。取れなかったものは None）。"""

    disclosures: pd.DataFrame | None = None     # time, code, title, url
    disclosure_days: set = field(default_factory=set)   # 開示を取得できた暦日
    short: pd.DataFrame | None = None           # code, holder, calc_date, ratio, prev_ratio
    flags: pd.DataFrame | None = None           # code, flags
    flags_date: str | None = None
    premium: pd.DataFrame | None = None         # code, date, rate, max_rate
    margin: pd.DataFrame | None = None          # code, sell, sell_chg, sell_ratio, buy, buy_chg, buy_ratio,
                                                # std_sell, std_sell_chg, std_buy, std_buy_chg, loan（fetch_margin_all）
    margin_date: str | None = None              # 信用残の申込日（最新日の前の取引日になる）
    errors: dict = field(default_factory=dict)  # 取得に失敗したもの → 理由


@dataclass
class Reasons:
    labels: dict                  # (日付文字列, code) → (ラベル, 短い文言)。直近 WINDOW_DAYS 日
    latest: pd.DataFrame          # index=code: why, why_text, idio, vr, disc, disc_text（最新日。一覧用）
    detail: dict                  # code → 最新日の説明（銘柄詳細用）
    disclosures: dict             # code → 直近 LIST_DAYS 日の開示（新しい順）
    status: dict                  # 材料ごとの取得状況（設定画面・実行記録用）
    feed: list = field(default_factory=list)   # 開示の一覧（これからの材料と、最新日に効いた開示。定例は除く）

    def label(self, day: str, code: str) -> tuple[str | None, str | None]:
        return self.labels.get((day, code), (None, None))


def _pct(x, nd: int = 2):
    return None if x is None or not np.isfinite(x) else round(float(x) * 100, nd)


def _signed(x: float) -> str:
    s = "+" if x > 0 else "−" if x < 0 else "±"
    return f"{s}{abs(x) * 100:.1f}%"


def _md(day: str | None) -> str:
    """"2026-09-25" → "9/25"。"""
    if not day:
        return ""
    _, m, d = day.split("-")
    return f"{int(m)}/{int(d)}"


def _int_or_none(x):
    return None if x is None or not np.isfinite(x) else int(x)


def _margin_summary(margin: pd.DataFrame | None, day: str | None, vavg: pd.Series) -> dict:
    """銘柄ごとの信用残と、出来高（直前20日平均）の何日分か。"""
    if margin is None or margin.empty:
        return {}
    out = {}
    for r in margin.itertuples():
        va = vavg.get(r.code)
        va = float(va) if va is not None and np.isfinite(va) and va > 0 else None
        out[r.code] = {
            "date": day,
            "buy": int(r.buy), "buy_chg": _int_or_none(r.buy_chg),
            "buy_ratio": None if r.buy_ratio is None or not np.isfinite(r.buy_ratio) else float(r.buy_ratio),
            "sell": int(r.sell), "sell_chg": _int_or_none(r.sell_chg),
            "sell_ratio": None if r.sell_ratio is None or not np.isfinite(r.sell_ratio) else float(r.sell_ratio),
            "ratio": round(r.buy / r.sell, 2) if r.sell > 0 else None,          # 信用倍率（買い残÷売り残）
            "buy_days": round(r.buy / va, 1) if va else None,
            "sell_days": round(r.sell / va, 1) if va else None,
            **_std_margin(r, va),
        }
    return out


def _std_margin(r, va: float | None) -> dict:
    """信用残のうち制度信用の分と、制度信用倍率（制度信用の買い残÷売り残）。

    一般信用（証券会社ごとの無期限・1日信用など）を除いた分。貸借銘柄（loan）でなければ制度信用では
    売れないので、ふつうは売り残が無く倍率も無い（倍率は印ではなく、売り残の有無で出す）。
    前日の倍率は、残高から前日比を引いた前日の残高で出す。
    """
    buy, sell = getattr(r, "std_buy", None), getattr(r, "std_sell", None)
    if buy is None or sell is None or pd.isna(buy) or pd.isna(sell):
        return {}       # 内訳を持たない古い取得結果（手元のキャッシュ）
    buy_chg, sell_chg = _int_or_none(r.std_buy_chg), _int_or_none(r.std_sell_chg)
    loan = getattr(r, "loan", None)
    prev = None
    if buy_chg is not None and sell_chg is not None and sell - sell_chg > 0:
        prev = round((buy - buy_chg) / (sell - sell_chg), 3)
    return {
        "std_buy": int(buy), "std_buy_chg": buy_chg, "std_sell": int(sell), "std_sell_chg": sell_chg,
        "std_ratio": round(buy / sell, 3) if sell > 0 else None,
        "std_ratio_prev": prev,
        "std_buy_days": round(buy / va, 1) if va else None,
        "std_sell_days": round(sell / va, 1) if va else None,
        "loan": None if loan is None or pd.isna(loan) else bool(loan),
    }


def _sector_returns(R: np.ndarray, b: np.ndarray, sectors: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """市場全体と、各銘柄の業種の当日騰落率の中央値（終値100円以上の銘柄で数える）。"""
    Rb = np.where(b, R, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)   # 売買の無い日は全て NaN になる
        market = np.nanmedian(Rb, axis=1)
        S = np.repeat(market[:, None], R.shape[1], axis=1)
        groups = pd.Series(np.arange(len(sectors)), index=sectors.to_numpy()).groupby(level=0)
        for _, idx in groups:
            cols = idx.to_numpy()
            sub = Rb[:, cols]
            enough = (~np.isnan(sub)).sum(axis=1) >= MIN_SECTOR
            S[:, cols] = np.where(enough, np.nanmedian(sub, axis=1), market)[:, None]
    return market, S


def _prepare(disc: pd.DataFrame | None, dates: pd.DatetimeIndex, codes: set) -> pd.DataFrame:
    cols = ["time", "code", "title", "url", "category", "kind", "text", "day", "pending"]
    if disc is None or disc.empty:
        return pd.DataFrame(columns=cols)
    d = disc[disc["code"].isin(codes)].drop_duplicates(["time", "code", "title"]).copy()
    if d.empty:
        return pd.DataFrame(columns=cols)
    d["time"] = pd.to_datetime(d["time"])
    parts = [classify(t) for t in d["title"]]
    d["category"] = [p[0] for p in parts]
    d["kind"] = [p[1] for p in parts]
    d["text"] = [p[2] for p in parts]
    d["day"] = effective_day(d["time"], dates)
    d["pending"] = np.where(d["day"].isna(), "next", "")   # next = 次の取引日の材料 / pm = 後場の材料
    return d[cols].sort_values("time").reset_index(drop=True)


_RANK = {c: i for i, c in enumerate(_PRIORITY)}
_KIND_ORDER = {"news": 0, "supply": 1, "routine": 2}


def _importance(r) -> tuple:
    """並べる順: ニュース → 需給 → 定例、同じ種類なら _PRIORITY の順、同じ分類なら新しい順。"""
    return _KIND_ORDER.get(r.kind, 3), _RANK.get(r.category, len(_RANK)), -r.time.value


def _headline(items: pd.DataFrame) -> str:
    return min(items.itertuples(), key=_importance).text


def _short_summary(short: pd.DataFrame | None, since: pd.Timestamp | None = None) -> dict:
    """機関の空売り残高（報告分）の銘柄ごとの合計と、報告前からの増減（ポイント）。

    空売り残高のファイルには「その日に届いた報告」だけが載る。数日分の報告から、機関ごとに
    最も古い報告の「直近の割合」と最も新しい報告の割合を取り、銘柄ごとに足す。
    0.5%に届いて初めて報告した機関は、前の割合を0とみなす。
    since を渡すと、その日以降に計算された報告だけで数える（値動きの手がかりに使うとき。
    1週間前の買い戻しを当日の急騰の理由にしない: リベルタ 2026-09-25 は 9/18 の報告だった）。
    """
    if short is None or short.empty:
        return {}
    s = short if since is None else short[short["calc_date"] >= since]
    if s.empty:
        return {}
    s = s.sort_values("calc_date")
    key = ["code", "holder"]
    first = s.groupby(key).head(1).set_index(key)            # その機関の、窓の中で最も古い報告
    newest = s.groupby(key).tail(1).set_index(key)            # 最も新しい報告
    per = pd.DataFrame({
        "now": newest["ratio"],
        "prev": first["prev_ratio"].reindex(newest.index).fillna(0.0),
        "date": newest["calc_date"],
    }).reset_index()
    out = {}
    for code, x in per.groupby("code"):
        now, prev = float(x["now"].sum()) * 100, float(x["prev"].sum()) * 100
        out[code] = {"now": round(now, 2), "prev": round(prev, 2), "change": round(now - prev, 2),
                     "holders": int(len(x)), "date": x["date"].max().strftime("%Y-%m-%d")}
    return out


def compute(p, base: pd.DataFrame, ex: Extras, now: pd.Timestamp, session: str = "close") -> Reasons:
    """p は data.Panel、base は「終値100円以上で売買のあった日」の表、now は日本時間の現在時刻。

    session が am（前場の引け後の実行）のときは、最新日の出来高を前場の分として見て、
    11:30 以降の開示はその日の前場の理由にしない（後場の材料として一覧に出す）。
    """
    n = WINDOW_DAYS + SIGMA_DAYS + 25
    c = p.close.iloc[-n:]
    dates, codes = c.index, c.columns
    cf = c.ffill()
    ret = (cf / cf.shift(1) - 1).where(c.notna())
    R = ret.to_numpy(dtype=float)
    B = base.iloc[-n:].reindex(columns=codes).fillna(False).to_numpy(dtype=bool)
    sectors = p.master["sector33"].reindex(codes)
    sec_cols = {name: idx.to_numpy() for name, idx in
                pd.Series(np.arange(len(codes)), index=sectors.to_numpy()).groupby(level=0)}
    market, S = _sector_returns(R, B, sectors)
    I = R - S
    sigma = ind.rolling(pd.DataFrame(I, index=dates, columns=codes), SIGMA_DAYS, SIGMA_MIN, "std")
    with np.errstate(invalid="ignore", divide="ignore"):
        Z = I / sigma.shift(1).clip(lower=SIGMA_FLOOR).to_numpy()
        v = p.volume.iloc[-n:]
        vavg = ind.rolling(v.fillna(0.0), 20, 15, "mean").shift(1)
        VR = (v / vavg.where(vavg > 0)).to_numpy(dtype=float)
    # 直前に売買が成立した日（売買の無い日を挟んだら、その間の開示もまとめて見る）
    valid = c.notna().to_numpy()
    prev_pos = pd.DataFrame(np.where(valid, np.arange(len(dates), dtype=float)[:, None], np.nan)).ffill().shift(1).to_numpy()

    disc = _prepare(ex.disclosures, p.dates, set(codes))
    if session == "am" and len(disc):
        late = (disc["day"] == dates[-1]) & (disc["time"] >= dates[-1] + AM_CLOSE)
        disc.loc[late, "day"] = pd.NaT
        disc.loc[late, "pending"] = "pm"
    by_code = {k: g for k, g in disc.groupby("code")} if len(disc) else {}
    # 最新日の出来高の目安（昼の実行は前場の分だけ・取引時間中の途中は出来高では見ない）
    vr_last = {"am": NOTABLE_VR_AM, "intraday": np.inf}.get(session, NOTABLE_VR)
    short = _short_summary(ex.short)                                    # 表示用（数日分の報告）
    short_recent = _short_summary(ex.short, since=dates[-1] - SHORT_RECENT)   # 手がかり用
    margin = _margin_summary(ex.margin, ex.margin_date, vavg.iloc[-1])
    flags = dict(zip(ex.flags["code"], ex.flags["flags"])) if ex.flags is not None else {}
    premium = {}
    if ex.premium is not None:
        for r in ex.premium.itertuples():
            if r.rate > 0:
                premium[r.code] = {"rate": float(r.rate), "max": float(r.max_rate) if np.isfinite(r.max_rate) else None,
                                   "date": r.date.strftime("%Y-%m-%d") if not pd.isna(r.date) else None}
    got_days = set(ex.disclosure_days) if ex.disclosures is not None else set()
    last = len(dates) - 1
    window = range(max(len(dates) - WINDOW_DAYS, 1), len(dates))
    ex_days = {dates[i] for i in window if is_ex_rights(dates[i], dates)}
    last_rights_days = {dates[i] for i in window if is_last_with_rights(dates[i], dates)}

    def prev_date(i: int, j: int) -> pd.Timestamp:
        k = prev_pos[i, j]
        return dates[int(k)] if not np.isnan(k) else dates[i - 1]

    def in_window(i: int, j: int) -> pd.DataFrame | None:
        g = by_code.get(codes[j])
        if g is None:
            return None
        lo, hi = prev_date(i, j), dates[i]
        return g[(g["day"] > lo) & (g["day"] <= hi)]

    def covered(i: int, j: int) -> bool:
        lo, hi = prev_date(i, j).date(), dates[i].date()
        return all(d.date() in got_days for d in pd.date_range(lo, hi))

    def vol_words(i: int, vr: float) -> str:
        if i == last and session == "am":
            return f"前場だけで出来高が1日平均の{vr:.1f}倍（ふだんのペースの約{vr / AM_SHARE:.0f}倍）"
        return f"出来高が20日平均の{vr:.1f}倍"

    def clues(i: int, j: int) -> list[dict]:
        code, r, z, vr = codes[j], R[i, j], Z[i, j], VR[i, j]
        vr_th = vr_last if i == last else NOTABLE_VR
        out = []
        if vr >= vr_th and abs(r) < QUIET_RET and (np.isnan(z) or abs(z) < QUIET_Z):
            if dates[i] in last_rights_days:
                out.append({"key": "volume", "short": "権利取りの売買",
                            "text": f"{dates[i].month}月末の権利付き最終日（配当・優待の権利を得られる最後の日）。"
                                    f"{vol_words(i, vr)}に増えたのに値動きは小さく、権利取りの売買とみられる"})
            else:
                out.append({"key": "volume", "short": "出来高急増・値動き小",
                            "text": f"{vol_words(i, vr)}に増えたのに、値動きは小さい"
                                    "（指数の入れ替えや大口の売買で起きやすい形）"})
        if i == last:
            heat = [FLAG_NAMES[ch] for ch in flags.get(code, "") if ch in HEAT_FLAGS]
            if heat:
                out.append({"key": "flags", "short": "信用規制・日々公表",
                            "text": f"{'・'.join(heat)}の対象（信用取引が過熱しているサイン）"})
            sh = short_recent.get(code)
            if sh and sh["change"] <= -SHORT_CHANGE and r > 0:
                out.append({"key": "short", "short": "空売りの買い戻し",
                            "text": f"機関の空売り残高（報告分）が {sh['prev']:.2f}% → {sh['now']:.2f}% に減った"
                                    "（買い戻しは株価の押し上げ要因）"})
            if sh and sh["change"] >= SHORT_CHANGE and r < 0:
                out.append({"key": "short", "short": "空売りの増加",
                            "text": f"機関の空売り残高（報告分）が {sh['prev']:.2f}% → {sh['now']:.2f}% に増えた"})
            mg = margin.get(code)
            if (mg and r < 0 and (mg["buy_days"] or 0) >= MARGIN_LONG_DAYS
                    and (mg["ratio"] is None or mg["ratio"] >= MARGIN_LONG_RATIO)):
                parts = ([f"上場株式の{mg['buy_ratio']:.1f}%"] if mg["buy_ratio"] is not None else []) + [
                    f"信用倍率 {mg['ratio']:.2f}倍の買い長" if mg["ratio"] is not None else "売り残なし"]
                out.append({"key": "margin_long", "short": "信用買い残が重い",
                            "text": f"信用買い残が出来高の{mg['buy_days']:.1f}日分と重い（{'・'.join(parts)}）。"
                                    f"値下がりで投げ売りが出やすい（{_md(mg['date'])} 申込み時点）"})
            if (mg and r > 0 and (mg["sell_days"] or 0) >= MARGIN_SHORT_DAYS
                    and mg["ratio"] is not None and mg["ratio"] <= MARGIN_SHORT_RATIO):
                side = "売り長" if mg["ratio"] < 1 else "売り買いが拮抗"
                out.append({"key": "margin_short", "short": "売り残が多い（踏み上げ）",
                            "text": f"信用売り残が出来高の{mg['sell_days']:.1f}日分・信用倍率 {mg['ratio']:.2f}倍（{side}）。"
                                    f"値上がりで買い戻し（踏み上げ）が入りやすい（{_md(mg['date'])} 申込み時点）"})
        if dates[i] in ex_days and r < 0:
            out.append({"key": "ex_rights", "short": "権利落ち日",
                        "text": f"{dates[i].month}月末の権利落ち日。配当・優待の権利が落ちた分だけ下がる銘柄が多い"})
        return out

    def group(i: int, j: int) -> dict | None:
        """同じ業種の他の銘柄も、同じ向きにそろって大きく動いたか（テーマ・連れ高）。"""
        name = sectors.iloc[j]
        if not isinstance(name, str) or np.isnan(Z[i, j]):
            return None
        cols = sec_cols[name]
        with np.errstate(invalid="ignore"):
            ok = B[i, cols] & ~np.isnan(R[i, cols])
            same = ok & (np.sign(I[i, cols]) == np.sign(I[i, j])) & (np.abs(Z[i, cols]) >= GROUP_Z)
        others = int(same.sum()) - int(abs(Z[i, j]) >= GROUP_Z)
        if others < max(GROUP_MIN, GROUP_SHARE * int(ok.sum())):
            return None
        up = I[i, j] > 0
        return {"key": "group", "short": f"同業の{others}銘柄も{'上昇' if up else '下落'}",
                "text": f"同じ業種（{name}）の他の{others}銘柄も、普段の2倍以上そろって{'上げた' if up else '下げた'}"
                        "（業種の一部がまとめて動いた日。テーマ・連れ高の可能性）"}

    def judge(i: int, j: int) -> tuple[str | None, str | None, list[dict], bool]:
        """(ラベル, 短い文言, 手がかり, 判定できたか)"""
        if not covered(i, j):
            return None, None, [], False
        items = in_window(i, j)
        if items is not None and len(items):
            news = items[items["kind"] == "news"]
            if len(news):
                return "news", _headline(news), [], True
            supply = items[items["kind"] == "supply"]
            if len(supply):
                return "supply", _headline(supply), [], True
        g = group(i, j)
        if g:
            return "market", g["short"], [g], True
        cl = clues(i, j)
        if cl:
            return "supply", cl[0]["short"], cl, True
        vr = VR[i, j]
        if i == last and session == "am":
            return "unknown", "開示なし" + (f"・前場の出来高{vr:.1f}倍" if vr >= 1 else ""), [], True
        return "unknown", "開示なし" + (f"・出来高{vr:.1f}倍" if vr >= 2 else ""), [], True

    labels: dict = {}
    unchecked = 0
    last_detail: dict[str, tuple] = {}
    for i in window:
        r, s, z, vr, idio = R[i], S[i], Z[i], VR[i], I[i]
        with np.errstate(invalid="ignore"):
            ok = B[i] & ~np.isnan(r)
            big = np.where(np.isnan(z), np.abs(idio) >= NOTABLE_IDIO, np.abs(z) >= NOTABLE_Z)
            notable = ok & (big | (vr >= (vr_last if i == last else NOTABLE_VR)))
            market_move = (ok & ~big & (np.abs(r) >= MARKET_RET) & (np.abs(s) >= MARKET_SECTOR)
                           & (np.sign(r) == np.sign(s)))
        day = dates[i].strftime("%Y-%m-%d")
        for j in np.nonzero(market_move)[0]:
            name = sectors.iloc[j] if isinstance(sectors.iloc[j], str) else "市場"
            labels[(day, codes[j])] = ("market", f"{name}全体 {_signed(s[j])}")
            if i == last:
                last_detail[codes[j]] = ("market", labels[(day, codes[j])][1], [], True)
        for j in np.nonzero(notable & ~market_move)[0]:
            label, text, cl, checked = judge(i, j)
            if label:
                labels[(day, codes[j])] = (label, text)
            if i == last:
                last_detail[codes[j]] = (label, text, cl, checked)
                unchecked += not checked

    # --- 最新日（一覧・銘柄詳細） ---
    day = dates[last].strftime("%Y-%m-%d")
    latest = pd.DataFrame({
        "why": [labels.get((day, cd), (None, None))[0] for cd in codes],
        "why_text": [labels.get((day, cd), (None, None))[1] for cd in codes],
        "idio": [_pct(x) for x in I[last]],
        "vr": [None if not np.isfinite(x) else round(float(x), 1) for x in VR[last]],
    }, index=codes)

    detail = {}
    for j, code in enumerate(codes):
        items = in_window(last, j)
        label, text, cl, checked = last_detail.get(code, (None, None, [], True))
        detail[code] = {
            "date": day,
            "session": session,
            "label": label, "text": text,
            "notable": code in last_detail,
            "checked": bool(checked) and bool(got_days),
            "ret": _pct(R[last, j]), "idio": _pct(I[last, j]),
            "z": None if not np.isfinite(Z[last, j]) else round(float(Z[last, j]), 1),
            "vr": None if not np.isfinite(VR[last, j]) else round(float(VR[last, j]), 1),
            "sector": sectors.iloc[j] if isinstance(sectors.iloc[j], str) else None,
            "sector_ret": _pct(S[last, j]), "market_ret": _pct(market[last]),
            # 判定に効いた開示を先に（清水建設 9/25 は、本命の転換社債が時刻順だと4番目だった）
            "disclosures": [] if items is None else [_item(x) for x in sorted(items.itertuples(), key=_importance)],
            "clues": [{"key": x["key"], "text": x["text"]} for x in cl],
            "short": short.get(code),
            "premium": premium.get(code),
            "flags": [FLAG_NAMES[ch] for ch in flags.get(code, "")],
            "margin": margin.get(code),
        }

    # --- 銘柄詳細の開示一覧（その開示が効いた日の値動き付き） ---
    pos = {d: k for k, d in enumerate(dates)}
    col = {cd: j for j, cd in enumerate(codes)}
    since = now - pd.Timedelta(days=LIST_DAYS)
    lists = {}
    for code, g in by_code.items():
        g = g[g["time"] >= since]
        out = []
        for x in g.sort_values("time", ascending=False).itertuples():
            item = _item(x)
            k = pos.get(x.day)
            if k is not None:
                item["ret"], item["idio"] = _pct(R[k, col[code]]), _pct(I[k, col[code]])
            out.append(item)
        if out:
            lists[code] = out

    # --- 開示の一覧（定例を除く）: これからの材料（引け後＝次の取引日、昼の実行なら 11:30 以降＝後場）と、
    #     最新日に効いた開示（その日の値動き付き）。銘柄ごとに、判定に効く順で並べる ---
    feed = []
    if len(disc):
        live = disc[(disc["kind"] != "routine") & (disc["day"].isna() | (disc["day"] == dates[last]))]
        for x in sorted(live.itertuples(), key=lambda r: (r.code, _importance(r))):
            item = {"code": x.code, **_item(x), "text": x.text}
            if item["day"]:
                item["ret"], item["idio"] = _pct(R[last, col[x.code]]), _pct(I[last, col[x.code]])
            feed.append(item)
    ahead: dict = {}
    for item in feed:               # 一覧の行に付ける印は、これからの材料の先頭（いちばん効きそうなもの）
        if item["day"] is None:
            ahead.setdefault(item["code"], item)
    latest["disc"] = [ahead[cd]["category"] if cd in ahead else None for cd in codes]
    latest["disc_text"] = [ahead[cd]["text"] if cd in ahead else None for cd in codes]

    counts = pd.Series([v[0] for (d, _), v in labels.items() if d == day]).value_counts().to_dict()
    status = {
        "date": day,
        "session": session,
        "disclosures": {
            "ok": ex.disclosures is not None and bool(got_days),
            "count": int(len(disc)),
            "latest": disc["time"].max().strftime("%Y-%m-%d %H:%M") if len(disc) else None,
            "days_failed": _days_failed(ex, now),
            "error": ex.errors.get("disclosures"),
        },
        "short": {"ok": ex.short is not None, "date": max((v["date"] for v in short.values()), default=None),
                  "error": ex.errors.get("short")},
        "flags": {"ok": ex.flags is not None, "date": ex.flags_date, "error": ex.errors.get("flags")},
        "premium": {"ok": ex.premium is not None,
                    "date": next((v["date"] for v in premium.values() if v["date"]), None),
                    "error": ex.errors.get("premium")},
        "margin": {"ok": ex.margin is not None, "date": ex.margin_date, "error": ex.errors.get("margin")},
        "counts": {k: int(counts.get(k, 0)) for k in LABELS},
        "unchecked": int(unchecked),
    }
    return Reasons(labels, latest, detail, lists, status, feed)


def _item(x) -> dict:
    return {
        "time": x.time.strftime("%Y-%m-%d %H:%M"),
        "title": x.title,
        "category": x.category,
        "kind": x.kind,
        "url": x.url if isinstance(x.url, str) else None,
        "day": None if pd.isna(x.day) else x.day.strftime("%Y-%m-%d"),   # None = まだ来ていない取引日
        "pending": x.pending or None,     # next = 次の取引日の材料 / pm = 後場の材料（昼の実行だけ）
    }


def _days_failed(ex: Extras, now: pd.Timestamp) -> int:
    if ex.disclosures is None:
        return LIST_DAYS
    days = pd.date_range((now - pd.Timedelta(days=LIST_DAYS)).normalize(), now.normalize())
    return int(sum(d.date() not in ex.disclosure_days for d in days))


def brief(status: dict | None) -> dict | None:
    """実行記録（公開される）に残す要約。件数と成否だけ。"""
    if not status:
        return None
    return {
        "disclosures": status["disclosures"]["count"],
        "disclosure_days_failed": status["disclosures"]["days_failed"],
        "short": status["short"]["ok"], "flags": status["flags"]["ok"], "premium": status["premium"]["ok"],
        "margin": status["margin"]["ok"],
        "unchecked": status["unchecked"],
    }
