"""回帰テスト（実データで踏んだ罠を合成データで再現する）。

    cd pipeline
    .venv\\Scripts\\python.exe tests\\test_momentum.py      # pytest が無くても動く
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build  # noqa: E402
import fetch  # noqa: E402
import market_days  # noqa: E402
import secure  # noqa: E402
import should_build  # noqa: E402
from momentum import data, export, indicators as ind, reasons as rsn, signals as sig, themes  # noqa: E402


def _frames(closes: list[float], flat_days: set[int] = frozenset()):
    """1銘柄の日足。flat_days の日は一本値（始値=高値=安値=終値）にする。"""
    idx = pd.bdate_range("2026-01-05", periods=len(closes))
    c = pd.DataFrame({"X": closes}, index=idx, dtype=float)
    h = c * 1.01
    l = c * 0.99
    for i in flat_days:
        h.iloc[i] = c.iloc[i]
        l.iloc[i] = c.iloc[i]
    o = c.copy()
    v = pd.DataFrame({"X": [1000.0] * len(closes)}, index=idx)
    return o, h, l, c, v


def test_price_limit_table():
    lim = data.price_limit(np.array([99, 100, 499, 500, 999, 1000, 2808, 3000, 4999, 11040]))
    assert list(lim) == [30, 50, 80, 100, 150, 300, 500, 700, 700, 3000]


def test_split_is_adjusted_and_keeps_the_days_move():
    # 3380 → 1695: 1株→2株の分割（当日の値動きは +0.3%）
    o, h, l, c, v = _frames([3300, 3350, 3380, 1695, 1700])
    o2, h2, l2, c2, v2, adj = data._adjust_discontinuities(o, h, l, c, v)
    assert len(adj) == 1 and adj[0]["kind"] == "split"
    assert abs(c2["X"].iloc[2] - 1690) < 1e-9            # 過去側が 1/2 に
    assert abs(c2["X"].iloc[3] / c2["X"].iloc[2] - 1695 / 1690) < 1e-12
    assert abs(v2["X"].iloc[2] - 2000) < 1e-9            # 出来高は2倍に


def test_expanded_limit_after_limit_up_is_real():
    # 地盤ネット: 248 → 328（ストップ高・一本値）→ 648（4倍に拡大された値幅）→ 1048
    o, h, l, c, v = _frames([198, 248, 328, 648, 1048, 1340], flat_days={1, 2, 3, 4})
    *_, adj = data._adjust_discontinuities(o, h, l, c, v)
    assert adj == []


def test_tick_rounded_limit_up_is_real():
    # さくらインターネット: 2808 + 500 = 3308 が5円刻みに丸まって 3310
    o, h, l, c, v = _frames([2750, 2808, 3310, 3300])
    *_, adj = data._adjust_discontinuities(o, h, l, c, v)
    assert adj == []


def test_spinoff_gap_is_neutralized():
    # Hamee: 1347 → 571（前日は普通の日。分割比率にも当てはまらない）
    o, h, l, c, v = _frames([1340, 1347, 571, 519])
    o2, h2, l2, c2, v2, adj = data._adjust_discontinuities(o, h, l, c, v)
    assert len(adj) == 1 and adj[0]["kind"] == "jump"
    assert abs(c2["X"].iloc[2] / c2["X"].iloc[1] - 1) < 1e-12   # 段差の日のリターンは0


def test_make_panel_drops_zero_volume_garbage():
    bars = pd.DataFrame({
        "date": ["2025-12-16", "2025-12-17", "2025-12-18"],
        "code": ["8303"] * 3,
        "open": [1.0, 5.5e10, 1632.0], "high": [1.0, 5.5e10, 1800.0],
        "low": [1.0, 5.5e10, 1630.0], "close": [0.0, 5.5e10, 1800.0],
        "volume": [0, 0, 79182300],
    })
    master = pd.DataFrame([{"code": "8303", "name": "SBI新生銀行", "market": "プライム（内国株式）",
                            "sector33": "銀行業", "scale": None}])
    p = data.make_panel(bars, master)
    assert p.close["8303"].dropna().tolist() == [1800.0]
    assert p.master.loc["8303", "segment"] == "プライム"


def test_numpy_rolling_matches_pandas():
    rng = np.random.default_rng(0)
    x = pd.DataFrame(rng.normal(size=(120, 6)))
    x.iloc[10:25, 2] = np.nan
    x.iloc[:30, 4] = np.nan
    for stat in ("mean", "std", "sum"):
        ours = ind.rolling(x, 20, 15, stat)
        ref = getattr(x.rolling(20, min_periods=15), stat)()
        pd.testing.assert_frame_equal(ours, ref, atol=1e-9, check_dtype=False)


def test_momentum_score_direction():
    idx = pd.bdate_range("2025-01-01", periods=200)
    rng = np.random.default_rng(1)
    noise = rng.normal(0, 0.01, size=200)
    up = 1000 * np.exp(np.cumsum(noise + 0.004))
    down = 1000 * np.exp(np.cumsum(noise - 0.004))
    flat = 1000 * np.exp(np.cumsum(noise - noise.mean()))
    score = ind.momentum(pd.DataFrame({"up": up, "down": down, "flat": flat}, index=idx))["score"].iloc[-1]
    assert score["up"] >= 85 and score["down"] <= 15 and 15 < score["flat"] < 85


def test_cooldown_counts_one_event_per_episode():
    s = pd.DataFrame({"X": [True, True, True] + [False] * 10 + [True, True]})
    out = [bool(x) for x in sig._cooldown(s, n=10)["X"]]
    # 続いている間は最初の1回だけ。10日空けば再び数える
    assert out == [True, False, False] + [False] * 10 + [True, False]


def test_seal_roundtrip_and_wrong_key():
    cfg = {"salt": "AAAAAAAAAAAAAAAAAAAAAA==", "iterations": 1000}
    key = secure.derive_key("正しい合言葉です", cfg)
    blob = secure.seal({"a": [1, 2.5, None], "名前": "トヨタ"}, key)
    assert secure.open_sealed(blob, key) == {"a": [1, 2.5, None], "名前": "トヨタ"}
    other = secure.derive_key("違う合言葉です", cfg)
    try:
        secure.open_sealed(blob, other)
    except Exception:
        pass
    else:
        raise AssertionError("違う合言葉で復号できてしまった")


# --- 値動きの理由 -------------------------------------------------------------------

def test_parse_disclosures_handles_both_shapes():
    # 2026-08-06 は各行が {"Tdnet": …} で包まれていなかった。ETF の5桁コード（末尾4）は落とす
    doc = {"total_count": 3, "items": [
        {"Tdnet": {"pubdate": "2026-09-25 08:30:00", "company_code": "49670", "title": "当社に関する一部報道について",
                   "document_url": "https://webapi.yanoshin.jp/rd.php?https://www.release.tdnet.info/inbs/1.pdf"}},
        {"pubdate": "2026-09-24 15:40:00", "company_code": "464A0", "title": "S&amp;P との提携",
         "document_url": "https://www.release.tdnet.info/inbs/2.pdf"},
        {"Tdnet": {"pubdate": "2026-09-25 09:00:00", "company_code": "13264", "title": "日々の開示事項",
                   "document_url": None}},
    ]}
    rows = fetch.parse_disclosures(doc)
    assert [r["code"] for r in rows] == ["4967", "464A"]
    assert rows[0]["url"] == "https://www.release.tdnet.info/inbs/1.pdf"   # 転送用URLを外す
    assert rows[1]["title"] == "S&P との提携"


def test_parse_disclosures_rejects_truncated_answer():
    # 件数が多すぎると total_count=1・items 空が返る。「開示なし」と取り違えない
    try:
        fetch.parse_disclosures({"total_count": 1, "items": []})
    except ValueError:
        pass
    else:
        raise AssertionError("件数の合わない応答を受け入れてしまった")
    assert fetch.parse_disclosures({"total_count": 0, "items": []}) == []   # 休日は本当に0件


def test_classify_disclosure_titles():
    cases = {
        "当社に関する一部報道について": ("報道への回答", "news", "一部報道について"),
        "2031年満期ユーロ円建取得条項付転換社債型新株予約権付社債の発行に関するお知らせ":
            ("増資・売出し", "supply", "転換社債の発行"),
        "自己株式の取得枠拡大及び自己株式の取得状況に関するお知らせ": ("自社株買い", "supply", "自社株買い"),
        "自己株式の取得状況に関するお知らせ": ("定例", "routine", "自己株式の取得状況"),
        "（開示事項の経過）大口受注（予定）に関するお知らせ": ("受注・提携等", "news", "大口受注（予定）"),
        "連結業績予想及び配当予想の修正（無配）に関するお知らせ": ("業績修正", "news", "業績予想の修正"),
        "株式会社Ａによる当社株式に対する公開買付けに関する意見表明のお知らせ":
            ("TOB・M&A", "news", "TOB(公開買付け)"),
        "コーポレート・ガバナンスに関する報告書": ("定例", "routine", "コーポレート・ガバナンスに関する報告書"),
        "役員に対する業績連動型株式報酬制度の導入に関するお知らせ": ("定例", "routine", "役員に対する業績連動型株式報酬制度の導入"),
        # 報酬としての株の交付は定例（最初は「自己株式の処分」「株式取得」の言葉で増資・M&A になっていた）
        "譲渡制限付株式報酬としての自己株式の処分に関するお知らせ": ("定例", "routine", "譲渡制限付株式報酬としての自己株式の処分"),
        "株式報酬制度における株式取得に係る事項の決定に関するお知らせ":
            ("定例", "routine", "株式報酬制度における株式取得に係る事項の決定"),
        "従業員持株会設立に関するお知らせ": ("定例", "routine", "従業員持株会設立"),
        # 「持株会社」は再編のニュース。報酬の「持株会」と取り違えない
        "株式会社Ａと株式会社Ｂの共同持株会社設立（共同株式移転）に関する株式移転計画書作成について":
            ("TOB・M&A", "news", "株式会社Ａと株式会社Ｂの共同持株会社設立（共同株式移転）に関する株式移転計画書作成"),
        "第三者割当による自己株式の処分に関するお知らせ": ("増資・売出し", "supply", "自己株式の処分"),
        # 開示の一覧にして分かったもの: 貸借銘柄の選定は需給の話、説明会の質疑や役員人事は定例
        "当社株式の貸借銘柄選定に関するお知らせ": ("貸借銘柄", "supply", "貸借銘柄の選定・解除"),
        "2026年12月期 第2四半期（中間期）決算 質疑応答集": ("定例", "routine", "第2四半期（中間期）決算 質疑応答集"),
        "監査役の辞任及び補欠監査役の監査役就任に関するお知らせ": ("定例", "routine", "監査役の辞任及び補欠監査役の監査役就任"),
        "代表取締役の異動に関するお知らせ": ("代表の交代", "news", "社長・代表の交代"),
        # 表記の揺れ（「子会社等の異動」「株式譲渡」）で「その他」になっていた（2026-10-09 の HOYA）
        "子会社等の異動（株式譲渡）に関するお知らせ": ("TOB・M&A", "news", "子会社等の異動（株式譲渡）"),
    }
    for title, want in cases.items():
        assert rsn.classify(title) == want, (title, rsn.classify(title))


def test_disclosure_after_close_moves_to_next_trading_day():
    dates = pd.DatetimeIndex(["2026-09-17", "2026-09-18", "2026-09-24", "2026-09-25"])   # 9/21〜23 は休場
    times = pd.Series(pd.to_datetime([
        "2026-09-18 15:29", "2026-09-18 15:30", "2026-09-19 10:00", "2026-09-25 16:00", "2026-09-17 08:30",
    ]))
    got = rsn.effective_day(times, dates)
    want = ["2026-09-18", "2026-09-24", "2026-09-24", None, "2026-09-17"]
    assert [None if pd.isna(x) else x.strftime("%Y-%m-%d") for x in got] == want


def test_ex_rights_day_is_second_to_last_trading_day():
    dates = pd.bdate_range("2026-09-01", "2026-09-30")
    assert rsn.is_ex_rights(pd.Timestamp("2026-09-29"), dates)
    assert not rsn.is_ex_rights(pd.Timestamp("2026-09-28"), dates)
    # 月末までのデータがまだ無いときも数えられる（9/25 時点で 9/29 が権利落ち日）
    upto = dates[dates <= "2026-09-25"]
    assert not rsn.is_ex_rights(pd.Timestamp("2026-09-25"), upto)
    assert not rsn.is_ex_rights(pd.Timestamp("2026-08-28"), pd.bdate_range("2026-08-01", "2026-08-31"))
    # 権利付き最終日は権利落ち日の前の取引日（2026-09-28）。9/28 時点では 9/29・9/30 はまだデータに無い
    assert rsn.is_last_with_rights(pd.Timestamp("2026-09-28"), dates[dates <= "2026-09-28"])
    assert not rsn.is_last_with_rights(pd.Timestamp("2026-09-25"), upto)


def test_parse_short_positions_by_header_names():
    nan = np.nan
    raw = pd.DataFrame([
        [nan, "空売り残高に関する情報", nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan],
        [nan, "計算年月日", "銘柄コード", "銘柄名\n（日本語／英語）", nan, "商号・名称・氏名", "住所・所在地",
         "委託者・投資一任契約の相手方の商号・名称・氏名", "委託者・投資一任契約の相手方の住所・所在地",
         "信託財産・運用財産の名称", "空売り残高割合", "空売り残高数量", "空売り残高売買単位数",
         "直近計算年月日", "直近空売り残高割合", "備考"],
        [nan, "Date of Calculation", "Code of Stock", nan, nan, "Name of Short Seller"] + [nan] * 10,
        [nan, "2026-09-24 00:00:00", "604A", "ビーエイブル　普通株式", "beABLE", "モルガン・スタンレーMUFG証券",
         "東京都", nan, nan, nan, "0.0157", "168300", "1683", "2026-09-18 00:00:00", "0.0118", nan],
    ], dtype=object)
    s = fetch.parse_short_positions(raw)
    assert len(s) == 1 and s.iloc[0]["code"] == "604A"
    assert s.iloc[0]["holder"] == "モルガン・スタンレーMUFG証券"
    assert abs(s.iloc[0]["ratio"] - 0.0157) < 1e-12 and abs(s.iloc[0]["prev_ratio"] - 0.0118) < 1e-12


def test_parse_margin_flags_ignores_marks_in_names():
    nan = np.nan
    raw = pd.DataFrame([
        ["B", "規", "株", "ヴィッツ　普通株式", "スタンダード", "貸", "44400", "JP3159930001", "33500"],
        ["B", "日", nan, "日本製鉄　普通株式", "プライム", "貸", "54010", "JP3381000003", "100"],   # 名前に「日」「株」
        ["B", "規株", nan, "株式会社Ｘ　普通株式", "グロース", "制", "336A0", "JP3491920009", "0"],
    ], dtype=object)
    f = fetch.parse_margin_flags(raw).set_index("code")["flags"].to_dict()
    assert f == {"4440": "規株", "5401": "日", "336A": "規株"}


def _reason_panel():
    """業種A 10銘柄・業種B 6銘柄・130営業日の合成データ。最終日にだけ目立つ動きを入れる。
    （業種の銘柄が少ないと、動いた銘柄自身が業種の中央値を引っ張るので、業種Aは多めにする）"""
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2026-03-02", periods=130)
    codes = [f"{1000 + i}" for i in range(16)]
    rets = rng.normal(0, 0.01, size=(130, 16))
    rets[-1, :] = 0.0
    rets[-1, 0] = 0.15      # 1000: 開示ありで +15%
    rets[-1, 1] = 0.15      # 1001: 開示なしで +15%
    rets[-1, 2] = 0.12      # 1002: 第三者割当（需給の開示）で +12%
    rets[-1, 10:16] = 0.04  # 業種Bは全体で +4%（1010〜1015 は地合い）
    close = pd.DataFrame(1000 * np.exp(np.cumsum(rets, axis=0)), index=idx, columns=codes)
    vol = pd.DataFrame(10000.0, index=idx, columns=codes)
    vol.iloc[-1, 3] = 50000.0   # 1003: 出来高5倍・値動きなし
    master = pd.DataFrame({"name": codes, "market": "プライム（内国株式）",
                           "sector33": ["業種A"] * 10 + ["業種B"] * 6, "segment": "プライム"}, index=codes)
    p = data.Panel(close, close, close, close, vol, master)
    base = close.notna()
    last = idx[-1]
    disc = pd.DataFrame([
        {"time": last - pd.Timedelta(days=1) + pd.Timedelta(hours=16), "code": "1000",
         "title": "業績予想の上方修正に関するお知らせ", "url": None},
        {"time": last + pd.Timedelta(hours=11), "code": "1002",
         "title": "第三者割当による新株式発行に関するお知らせ", "url": None},
        {"time": last + pd.Timedelta(hours=16), "code": "1001",          # 引け後 → 次の取引日の材料
         "title": "決算短信", "url": None},
    ])
    days = set(pd.date_range(idx[0], last + pd.Timedelta(days=1)).date)
    return p, base, disc, days, last


def test_reason_labels_on_synthetic_panel():
    p, base, disc, days, last = _reason_panel()
    ex = rsn.Extras(disclosures=disc, disclosure_days=days)
    rs = rsn.compute(p, base, ex, last + pd.Timedelta(hours=17))
    got = rs.latest["why"].to_dict()
    assert got["1000"] == "news" and rs.latest.at["1000", "why_text"] == "業績予想の上方修正"
    assert got["1001"] == "unknown"                  # 引け後の決算短信は当日の理由にしない
    assert got["1002"] == "supply"
    assert got["1003"] == "supply" and rs.latest.at["1003", "why_text"] == "出来高急増・値動き小"
    assert all(got[f"{c}"] == "market" for c in range(1010, 1016))
    assert all(pd.isna(got[f"{c}"]) for c in range(1004, 1010))   # 動かなかった銘柄には付けない
    pending = [x for x in rs.disclosures["1001"] if x["day"] is None]
    assert len(pending) == 1                         # 「次の取引日」として一覧には出る


def test_reason_is_not_given_when_disclosures_are_missing():
    # 開示が取れなかった日を含む判定は「材料不明」にしない（開示があったかもしれないため）
    p, base, disc, days, last = _reason_panel()
    ex = rsn.Extras(disclosures=disc, disclosure_days={d for d in days if d != last.date()})
    rs = rsn.compute(p, base, ex, last + pd.Timedelta(hours=17))
    assert pd.isna(rs.latest.at["1001", "why"]) and rs.status["unchecked"] > 0
    assert rs.latest.at["1010", "why"] == "market"   # 地合いは開示が無くても判定できる


def test_group_move_in_part_of_a_sector_is_market_not_unknown():
    # 2026-09-18: 銀行業の中央値は +0.2% なのに、地銀の一群がそろって上げた。1行ずつ見ると
    # 「開示なし」だが、同業がそろって動いたこと自体がデータから分かるので地合い（連れ高）にする
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2026-03-02", periods=130)
    codes = [f"{2000 + i}" for i in range(20)]
    rets = rng.normal(0, 0.01, size=(130, 20))
    rets[-1, :] = 0.0
    rets[-1, :5] = 0.08                      # 20銘柄のうち5銘柄だけがそろって +8%
    rets[-1, 19] = 0.09                      # 別の業種で1銘柄だけ +9%（こちらは材料不明のまま）
    close = pd.DataFrame(1000 * np.exp(np.cumsum(rets, axis=0)), index=idx, columns=codes)
    vol = pd.DataFrame(10000.0, index=idx, columns=codes)
    sectors = ["銀行業"] * 12 + ["業種X"] * 8
    master = pd.DataFrame({"name": codes, "market": "プライム（内国株式）", "sector33": sectors,
                           "segment": "プライム"}, index=codes)
    p = data.Panel(close, close, close, close, vol, master)
    last = idx[-1]
    days = set(pd.date_range(idx[0], last).date)
    ex = rsn.Extras(disclosures=pd.DataFrame(columns=["time", "code", "title", "url"]), disclosure_days=days)
    rs = rsn.compute(p, close.notna(), ex, last + pd.Timedelta(hours=17))
    assert rs.latest.at["2000", "why"] == "market" and rs.latest.at["2000", "why_text"] == "同業の4銘柄も上昇"
    assert rs.detail["2000"]["clues"][0]["key"] == "group"
    assert rs.latest.at["2019", "why"] == "unknown"


def test_window_disclosures_put_the_main_reason_first():
    # 清水建設 2026-09-25: 時刻順だと本命の転換社債が4番目だった
    titles = [
        ("2026-09-24 16:50", "ユーロ円建転換社債(CB)発行及び自己株式取得に関する補足説明資料"),
        ("2026-09-24 16:50", "自己株式の取得枠拡大及び自己株式の取得状況に関するお知らせ"),
        ("2026-09-24 16:50", "2031年満期ユーロ円建取得条項付転換社債型新株予約権付社債の発行に関するお知らせ"),
        ("2026-09-25 11:00", "自己株式立会外買付取引（ToSTNeT-3）による自己株式の取得結果に関するお知らせ"),
    ]
    rows = []
    for t, title in titles:
        cat, kind, text = rsn.classify(title)
        rows.append({"time": pd.Timestamp(t), "title": title, "category": cat, "kind": kind, "text": text})
    items = pd.DataFrame(rows)
    ordered = sorted(items.itertuples(), key=rsn._importance)
    assert ordered[0].category == "増資・売出し" and ordered[-1].kind == "routine"
    assert rsn._headline(items) == "転換社債の発行"


def test_parse_margin_lines_rejoins_split_numbers():
    # JPX「銘柄別信用取引残高」の PDF から取り出した行（2026-09-25 申込み分の実例）。数字の途中に空白が入る
    lines = [
        # "▲ 2,1 00" は ▲2,100（一般信用の買い残の前日比）
        "B 極洋　普通株式 プライム 貸 13010 JP3257200000 株数 Shs. 9,300 300 0.1% 154,300 ▲ 3,900 1.3% "
        "0 0 9,300 300 35,400 ▲ 2,1 00 118,900 ▲ 1,800",
        # "2 4,900" は 24,900（2 と 4,900 に分けると足し算が合わない）
        "B サカタのタネ　普通株式 プライム 貸 13770 JP3315000004 株数 Shs. 18,600 600 0.0% 43,200 300 0.1% "
        "12,100 0 6,500 600 18,300 400 2 4,900 ▲ 100",
        # 上場直後で前日比が「-」
        "B Ｘ社　普通株式 グロース 制 634A0 JP3000000000 株数 Shs. 0 - 0.0% 272,900 - 9.6% 0 - 0 - 272,900 - 0 -",
        # 小計の行は読まない
        "グロース 小計 597 銘柄 株数 Shs. 37,230,800 ▲ 1,464,700 - 705,563,300 196,200 -",
        # 足し算が合わない行は読まない（買い残 1,000 ≠ 一般 300 + 制度 800）
        "B Ｙ社　普通株式 プライム 貸 99990 JP3999999999 株数 Shs. 0 0 0.0% 1,000 0 0.1% 0 0 0 0 300 0 800 0",
        # 外国企業の株（ISIN が JP 以外）も読む。最初は JP だけにしていて取りこぼした
        "B メディシノバ・インク　普通株式 スタンダード 制 48750 US58468P2065 株数 Shs. 0 ▲ 100 0.0% 129,100 ▲ 5,400 0.3% "
        "0 ▲ 100 0 0 70,000 ▲ 5,000 59,100 ▲ 400",
        # 社債型種類株式（コードの末尾が0以外）は読まない
        "B ソフトバンク株式会社第１回社債型種類株式 プライム 制 94345 JP3732000108 株数 Shs. 0 0 0.0% 0 0 0.0% 0 0 0 0 0 0 0 0",
    ]
    df = fetch.parse_margin_lines(lines).set_index("code")
    assert sorted(df.index) == ["1301", "1377", "4875", "634A"]
    assert (df.at["1301", "buy"], df.at["1301", "buy_chg"], df.at["1301", "buy_ratio"]) == (154300, -3900, 1.3)
    assert (df.at["1377", "buy"], df.at["1377", "buy_chg"]) == (43200, 300)
    assert df.at["634A", "buy"] == 272900 and pd.isna(df.at["634A", "buy_chg"])
    # 制度信用の分（内訳の並びは 一般信用 → 制度信用）と、貸借銘柄の印（貸＝制度信用で売れる）
    assert (df.at["1301", "std_sell"], df.at["1301", "std_sell_chg"]) == (9300, 300)
    assert (df.at["1301", "std_buy"], df.at["1301", "std_buy_chg"]) == (118900, -1800)
    assert (df.at["1377", "std_sell"], df.at["1377", "std_buy"]) == (6500, 24900)
    assert df.at["634A", "std_buy"] == 0 and pd.isna(df.at["634A", "std_buy_chg"])
    assert df["loan"].to_dict() == {"1301": True, "1377": True, "634A": False, "4875": False}


def test_heavy_short_interest_is_a_supply_clue_on_an_up_move():
    p, base, disc, days, last = _reason_panel()
    margin = pd.DataFrame([
        # 1001（開示なしで +15%）: 売り残が出来高（1万株/日）の2日分 → 踏み上げの手がかり
        {"code": "1001", "sell": 20000, "sell_chg": 0, "sell_ratio": 0.1, "buy": 30000, "buy_chg": 0, "buy_ratio": 0.2},
        # 1000（開示ありで +15%）: 信用残が重くても、開示があればニュースのまま
        {"code": "1000", "sell": 50000, "sell_chg": 0, "sell_ratio": 0.3, "buy": 90000, "buy_chg": 0, "buy_ratio": 0.5},
    ])
    ex = rsn.Extras(disclosures=disc, disclosure_days=days, margin=margin, margin_date="2026-08-27")
    rs = rsn.compute(p, base, ex, last + pd.Timedelta(hours=17))
    assert rs.latest.at["1001", "why"] == "supply" and rs.latest.at["1001", "why_text"] == "売り残が多い（踏み上げ）"
    assert rs.latest.at["1000", "why"] == "news"
    assert rs.detail["1001"]["margin"]["sell_days"] == 2.0 and rs.detail["1001"]["margin"]["ratio"] == 1.5
    # 買い残がずっと多い（買い長）なら、売り残が多くても踏み上げとは言わない（アツギ 2026-09-28: 信用倍率5.37倍）
    ex.margin = margin.assign(buy=[110000, 90000])      # 1001 の信用倍率 5.5倍
    rs = rsn.compute(p, base, ex, last + pd.Timedelta(hours=17))
    assert rs.latest.at["1001", "why"] == "unknown"
    assert "std_buy" not in rs.detail["1001"]["margin"]  # 内訳を持たない古い取得結果でも動く


def test_standardized_margin_ratio_excludes_negotiable():
    # 制度信用倍率＝制度信用の買い残÷売り残。一般信用の分は入れない
    p, base, disc, days, last = _reason_panel()
    margin = pd.DataFrame([
        # 極洋 2026-09-25 申込み分: 売り残 9,300 はすべて制度信用、買い残 154,300 のうち制度信用は 118,900
        {"code": "1000", "sell": 9300, "sell_chg": 300, "sell_ratio": 0.1, "buy": 154300, "buy_chg": -3900, "buy_ratio": 1.3,
         "std_sell": 9300, "std_sell_chg": 300, "std_buy": 118900, "std_buy_chg": -1800, "loan": True},
        # ユキグニファクトリー 2026-10-07: 貸借銘柄でなく、売り残 17,900 はすべて一般信用。合計の信用倍率は
        # 3.55倍と出るが、制度信用では売れないので制度信用倍率は無い
        {"code": "1001", "sell": 17900, "sell_chg": 0, "sell_ratio": 0.0, "buy": 63600, "buy_chg": 300, "buy_ratio": 0.2,
         "std_sell": 0, "std_sell_chg": 0, "std_buy": 4300, "std_buy_chg": 100, "loan": False},
        # 上場直後で前日比が無い
        {"code": "1002", "sell": 500, "sell_chg": None, "sell_ratio": 0.0, "buy": 1000, "buy_chg": None, "buy_ratio": 0.0,
         "std_sell": 400, "std_sell_chg": None, "std_buy": 100, "std_buy_chg": None, "loan": True},
    ])
    ex = rsn.Extras(disclosures=disc, disclosure_days=days, margin=margin, margin_date="2026-09-25")
    m = {c: d["margin"] for c, d in rsn.compute(p, base, ex, last + pd.Timedelta(hours=17)).detail.items() if d["margin"]}
    assert (m["1000"]["ratio"], m["1000"]["std_ratio"]) == (16.59, 12.785)      # 合計 154,300÷9,300 と 118,900÷9,300
    assert m["1000"]["std_ratio_prev"] == 13.411                                 # 前日は 120,700÷9,000
    assert (m["1000"]["std_buy_days"], m["1000"]["std_sell_days"], m["1000"]["loan"]) == (11.9, 0.9, True)
    assert (m["1001"]["ratio"], m["1001"]["std_ratio"], m["1001"]["std_ratio_prev"], m["1001"]["loan"]) == (3.55, None, None, False)
    assert (m["1002"]["std_ratio"], m["1002"]["std_ratio_prev"], m["1002"]["std_sell_chg"]) == (0.25, None, None)
    # 一覧の行に付ける「売り長」の印のため、最新値の表にも倍率を持つ（倍率の無い銘柄は欠損）
    latest = rsn.compute(p, base, ex, last + pd.Timedelta(hours=17)).latest
    assert latest.at["1002", "std_ratio"] == 0.25 and pd.isna(latest.at["1001", "std_ratio"]) and pd.isna(latest.at["1005", "std_ratio"])
    # 市場全体は残高の合計どうしの比。前日は、前日比のある銘柄の「残高−前日比」の合計で出す
    rows = [[c, x["loan"], x["std_buy"], x["std_buy_chg"], x["std_sell"], x["std_sell_chg"], x["std_ratio"],
             x["std_ratio_prev"], x["std_buy_days"], x["std_sell_days"], None, None] for c, x in m.items()]
    s = export.margin_summary(rows)
    assert (s["stocks"], s["rated"], s["short"]) == (3, 2, 1)
    assert (s["buy"], s["sell"], s["ratio"]) == (123300, 9700, 12.71)
    assert s["ratio_prev"] == 13.88                                              # (120,700 + 4,200) ÷ (9,000 + 0)
    assert export.margin_summary([]) is None


def test_session_from_time_of_run():
    from datetime import date, datetime
    tue = date(2026, 9, 29)
    at = lambda h, m: datetime(2026, 9, 29, h, m)   # noqa: E731
    assert build.session_of(at(11, 53), tue) == "am"          # 昼の定時実行
    assert build.session_of(at(12, 29), tue) == "am"
    assert build.session_of(at(10, 0), tue) == "intraday"     # 取引時間中の手動実行
    assert build.session_of(at(13, 0), tue) == "intraday"
    assert build.session_of(at(17, 17), tue) == "close"       # 夕方の定時実行
    assert build.session_of(at(8, 0), tue) == "close"
    # 祝日など当日の日足が無い日は、昼でも前の取引日の終値なので close
    assert build.session_of(at(11, 53), date(2026, 9, 28)) == "close"


def test_should_build_by_arrival_time():
    # GitHub の定時実行が6時間あまり遅れて届いた 2026-09-29〜30 の実際の順番で確かめる
    from datetime import datetime
    at = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=should_build.JST)  # noqa: E731
    auto = lambda now, built: should_build.decide(at(now), built, manual=False)[0]  # noqa: E731
    assert not auto("2026-09-29 18:05", "2026-09-29 17:12")   # 11:53 の分: 大引け後の分が公開済み
    assert not auto("2026-09-29 23:50", "2026-09-29 17:12")   # 17:17 の分
    assert not auto("2026-09-30 01:07", "2026-09-29 17:12")   # 18:47 の分: 夜中に前日分を作り直していた
    assert auto("2026-09-30 11:53", "2026-09-29 17:12")       # 前場の引け後
    assert not auto("2026-09-30 12:05", "2026-09-30 11:46")
    assert auto("2026-09-30 17:17", "2026-09-30 11:46")       # 大引け後
    assert auto("2026-09-30 18:05", "2026-09-30 11:46")       # 夕方の回が抜けた日は、遅れて届いた昼の分が代わる
    assert not auto("2026-09-30 18:47", "2026-09-30 17:48")   # 予備
    assert auto("2026-09-30 17:17", "")                        # 記録が読めなければ作る側に倒す
    for now in ("2026-09-30 09:40", "2026-09-30 14:00", "2026-09-30 16:30", "2026-10-03 17:30"):
        assert not auto(now, "2026-09-29 17:12"), now          # 朝・取引時間中・大引け直後・土曜
    assert should_build.decide(at("2026-09-30 01:07"), "2026-09-30 00:50", manual=True)[0]   # 手動はいつでも


def test_market_days_match_the_official_holidays():
    # 内閣府「国民の祝日」の一覧（2026-10-09 に取得した CSV）。振替休日（2025-02-24・2026-05-06・2027-03-22）と
    # 国民の休日（2026-09-22。敬老の日と秋分の日に挟まれた日）を含む
    from datetime import date
    official = {
        2025: "1/1 1/13 2/11 2/23 2/24 3/20 4/29 5/3 5/4 5/5 5/6 7/21 8/11 9/15 9/23 10/13 11/3 11/23 11/24",
        2026: "1/1 1/12 2/11 2/23 3/20 4/29 5/3 5/4 5/5 5/6 7/20 8/11 9/21 9/22 9/23 10/12 11/3 11/23",
        2027: "1/1 1/11 2/11 2/23 3/21 3/22 4/29 5/3 5/4 5/5 7/19 8/11 9/20 9/23 10/11 11/3 11/23",
    }
    for year, days in official.items():
        want = {date(year, *map(int, d.split("/"))) for d in days.split()}
        assert market_days.national_holidays(year) == want, (year, sorted(market_days.national_holidays(year) ^ want))
    td = market_days.is_trading_day
    assert not td(date(2026, 10, 12)) and td(date(2026, 10, 13))            # スポーツの日（月）
    assert not td(date(2026, 12, 31)) and not td(date(2027, 1, 1)) and td(date(2026, 12, 30)) and td(date(2027, 1, 4))
    assert not td(date(2026, 10, 10))                                        # 土曜
    assert market_days.previous_trading_day(date(2026, 10, 13)) == date(2026, 10, 9)   # 祝日と土日をまたぐ
    assert market_days.previous_trading_day(date(2027, 1, 4)) == date(2026, 12, 30)    # 年末年始をまたぐ


def test_should_build_skips_market_holidays():
    # 2026-10-12（月・スポーツの日）: タイマーは祝日を知らずに 11:53・17:17・18:47 に頼んでくる。
    # 以前は、金曜の大引けと同じ中身を2回作っていた
    from datetime import datetime
    at = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=should_build.JST)  # noqa: E731
    auto = lambda now, built: should_build.decide(at(now), built, manual=False)[0]  # noqa: E731
    for now in ("2026-10-12 11:53", "2026-10-12 17:17", "2026-10-12 18:47"):
        assert not auto(now, "2026-10-09 17:25"), now
    assert auto("2026-10-13 11:53", "2026-10-09 17:25")       # 休み明けはふだんどおり
    assert not auto("2026-12-31 17:17", "2026-12-30 17:25")   # 年末年始も休場
    # 金曜の大引けのデータが出来ていなければ、休場日でも作る（作ったあとは作らない）
    assert auto("2026-10-12 11:53", "2026-10-09 12:01")
    assert not auto("2026-10-12 17:17", "2026-10-12 12:01")
    assert not auto("2026-10-12 14:00", "2026-10-09 12:01")   # 時間帯の外では作らない
    assert should_build.decide(at("2026-10-12 14:00"), "2026-10-09 17:25", manual=True)[0]   # 手動はいつでも


def test_light_update_picks_up_disclosures_after_the_evening_build():
    # 開示だけの更新: 夕方の更新（金曜 17:25）のあとに出た開示を、夜と翌朝に拾う。
    # 2026-10-09（金）〜 10-13（火）。10/12（月）は祝日
    from datetime import datetime
    at = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=should_build.JST)  # noqa: E731
    fri = {"built": "2026-10-09 17:25", "as_of": "2026-10-09", "session": "close", "kept": "kept-2026-10-09-17-25"}
    mode = lambda now, last=fri: should_build.plan(at(now), last, manual=False)[0]  # noqa: E731
    after = lambda t: {**fri, "refreshed": {"at": t}}  # noqa: E731
    noon = {"built": "2026-10-09 12:01", "as_of": "2026-10-09", "session": "am"}
    assert mode("2026-10-09 17:18", noon) == "full"                          # 夕方の全体の更新はこれまでどおり
    assert mode("2026-10-09 17:30") == "skip"                                # 公開したばかり
    assert mode("2026-10-09 18:48") == "light"                               # 予備の回: 大引けのデータがあれば開示だけ
    assert mode("2026-10-09 18:52", after("2026-10-09 18:50")) == "skip"     # 重ねて届いた分
    assert mode("2026-10-09 20:18", after("2026-10-09 18:50")) == "light"
    assert mode("2026-10-10 01:57", after("2026-10-09 20:20")) == "light"    # 土曜の未明に遅れて届いた分: 金曜の夜の残り
    assert mode("2026-10-10 03:10", after("2026-10-10 02:00")) == "skip"     # 金曜の分は取り直し済み（土日は開示が出ない）
    assert mode("2026-10-12 08:38", after("2026-10-10 02:00")) == "skip"     # 祝日の朝
    assert mode("2026-10-12 08:38", after("2026-10-09 20:20")) == "light"    # 金曜の夜の残りをまだ拾っていなければ拾う
    assert mode("2026-10-13 01:30", after("2026-10-10 02:00")) == "skip"     # 休み明けの未明（8時より前は開示が出ない）
    assert mode("2026-10-13 08:38", after("2026-10-10 02:00")) == "light"    # 休み明けの朝: 寄り付き前の開示
    assert mode("2026-10-13 08:50", after("2026-10-13 08:41")) == "skip"
    for now in ("2026-10-13 09:00", "2026-10-13 10:30", "2026-10-13 14:00", "2026-10-13 16:59"):
        assert mode(now, after("2026-10-13 08:41")) == "skip", now           # 取引時間中は昼と夕方の更新に任せる
    assert mode("2026-10-13 11:53", after("2026-10-13 08:41")) == "full"     # 昼の全体の更新はこれまでどおり
    # 公開中のデータが直近の大引けのものでなければ、開示だけ取り直すことはしない（古いデータを新しく見せない）
    am = {"built": "2026-10-13 12:01", "as_of": "2026-10-13", "session": "am"}
    assert mode("2026-10-13 20:18", am) == "full"                            # 夕方の回が抜けていれば、全体の更新を試みる
    assert mode("2026-10-14 08:38", am) == "skip"                            # 翌朝も前場のデータのままなら触らない
    assert mode("2026-10-14 08:38", fri) == "skip"                           # 2取引日前のデータ
    assert mode("2026-10-13 08:38", {"built": "2026-10-09 17:25"}) == "skip"  # いつのデータか分からない（古い形の記録）
    assert mode("2026-10-13 08:38", {**fri, "refreshed": {"at": "壊れた値"}}) == "skip"   # 判定できなければ行わない
    # 取得した結果を残していないデータ（この仕組みを入れる前の更新・材料を取得できなかった日）には行わない
    unkept = {k: v for k, v in fri.items() if k != "kept"}
    assert mode("2026-10-09 18:48", unkept) == "skip" and mode("2026-10-13 08:38", unkept) == "skip"
    assert should_build.plan(at("2026-10-13 10:30"), fri, manual=True)[0] == "full"       # 手動はいつでも
    assert should_build.plan(at("2026-10-13 10:30"), fri, manual=True, want_light=True)[0] == "light"
    assert should_build.plan(at("2026-10-13 10:30"), unkept, manual=True, want_light=True)[0] == "error"
    assert should_build.kept_key("2026-10-09 17:25") == "kept-2026-10-09-17-25"


def test_kept_data_opens_only_with_the_same_key_and_format():
    cfg = {"salt": "AAAAAAAAAAAAAAAAAAAAAA==", "iterations": 1000}
    key = secure.derive_key("正しい合言葉です", cfg)
    blob = build.pack_kept({"built": "2026-10-09 17:25", "session": "close"}, b"fetched", b"extras", key)
    kept = build.open_kept(blob, key)
    assert (kept["status"]["built"], kept["fetched"], kept["extras"]) == ("2026-10-09 17:25", b"fetched", b"extras")

    def refused(blob, key) -> str:
        try:
            build.open_kept(blob, key)
        except build.KeptError as e:
            return str(e)
        raise AssertionError("開けてしまった")

    assert "合言葉" in refused(blob, secure.derive_key("違う合言葉です", cfg))
    assert "合言葉" in refused(blob[:-1] + bytes([blob[-1] ^ 1]), key)      # 1ビットでも変わっていれば開かない
    version, build.KEPT_VERSION = build.KEPT_VERSION, build.KEPT_VERSION + 1
    try:
        assert "形式" in refused(blob, key)                                  # 形式を変えたあとの古い保存結果
    finally:
        build.KEPT_VERSION = version


def test_refresh_disclosures_refetches_since_the_last_fetch_and_marks_new_items():
    # 金曜 17:22 に株価と一緒に取得した開示を、月曜の朝に取り直す（合成データの最終日 2026-08-28 は金曜）
    p, base, disc, days, last = _reason_panel()
    fri_1722 = last + pd.Timedelta(hours=17, minutes=22)
    mon_0840 = last + pd.Timedelta(days=3, hours=8, minutes=40)
    row = lambda t, code, title: {"time": t, "code": code, "title": title, "url": None}  # noqa: E731
    friday = disc[disc["time"] >= last].to_dict("records")
    late = [row(last + pd.Timedelta(hours=19), "1004", "通期業績予想の下方修正に関するお知らせ"),
            row(last + pd.Timedelta(days=3, hours=8), "1005", "当社株式に対する公開買付けの開始に関するお知らせ")]
    calls = []

    def fake(answer, ok_days):
        def fetch_disclosures(start, end):
            calls.append((start, end))
            return pd.DataFrame(answer, columns=["time", "code", "title", "url"]), set(ok_days)
        return fetch_disclosures

    since_fri = [d.date() for d in pd.date_range(last, last + pd.Timedelta(days=3))]
    kept = lambda: rsn.Extras(disclosures=disc.copy(), disclosure_days=set(days), disclosures_at=fri_1722)  # noqa: E731
    original = build.fetch.fetch_disclosures
    try:
        build.fetch.fetch_disclosures = fake(friday + late, since_fri)
        ex = kept()
        build.refresh_disclosures(ex, p.dates, mon_0840)
        assert calls == [(last.date(), mon_0840.date())]                  # 前に取得した日から今日まで
        assert len(ex.disclosures) == 5 and ex.disclosures_at == mon_0840 and ex.seen_at == fri_1722
        assert set(since_fri) <= ex.disclosure_days
        rs = rsn.compute(p, base, ex, mon_0840)
        upcoming = {x["code"]: x for x in rs.feed if x["day"] is None}
        assert set(upcoming) == {"1001", "1004", "1005"}
        assert "late" not in upcoming["1001"] and upcoming["1004"]["late"] and upcoming["1005"]["late"]
        # 一覧の行には、新着の分類と文言を別に持つ（1001 の引け後の決算短信は、前からあったので新着ではない）
        assert (rs.latest.at["1004", "disc_new"], rs.latest.at["1004", "disc_new_text"]) == ("業績修正", "業績予想の下方修正")
        assert rs.latest.at["1005", "disc_new"] == "TOB・M&A" and pd.isna(rs.latest.at["1001", "disc_new"])
        assert rs.latest.at["1001", "disc"] == "決算"
        st = rs.status["disclosures"]
        assert (st["since"], st["fetched"]) == ("2026-08-28 17:22", "2026-08-31 08:40")
        # その日の値動きの理由は、開示を取り直しても変わらない（引け後の開示は次の取引日の材料）
        before = rsn.compute(p, base, kept(), fri_1722)
        assert rs.latest["why"].to_dict() == before.latest["why"].to_dict()
        assert before.status["disclosures"]["since"] is None and before.latest["disc_new"].isna().all()   # 全体の更新に新着は無い

        def refused(answer, ok_days, ex) -> str:
            build.fetch.fetch_disclosures = fake(answer, ok_days)
            try:
                build.refresh_disclosures(ex, p.dates, mon_0840)
            except RuntimeError as e:
                return str(e)
            raise AssertionError("取り直せてしまった")

        # 日付が変わった直後（土曜 00:10）に取得していたら、前の日（金曜）から取り直す
        calls.clear()
        build.fetch.fetch_disclosures = fake(friday + late, since_fri)
        build.refresh_disclosures(rsn.Extras(disclosures=disc.copy(), disclosure_days=set(days),
                                             disclosures_at=last + pd.Timedelta(days=1, minutes=10)), p.dates, mon_0840)
        assert calls == [(last.date(), mon_0840.date())]

        assert "取得できない日" in refused(friday + late, since_fri[:-1], kept())       # 月曜の分が取れない
        many = [row(last + pd.Timedelta(hours=16, minutes=m), "1006", f"お知らせ{m}") for m in range(8)]
        big = rsn.Extras(disclosures=pd.concat([disc, pd.DataFrame(many)], ignore_index=True),
                         disclosure_days=set(days), disclosures_at=fri_1722)
        assert "少なすぎます" in refused(late, since_fri, big)                           # 前にあった金曜の10件が消えている
    finally:
        build.fetch.fetch_disclosures = original


def test_stale_close_data_is_not_published():
    # 取引日の大引け後なのに Yahoo が当日分を返さないと、前日のデータを「大引け後」として出してしまう
    from datetime import date, datetime
    fri, thu = date(2026, 10, 9), date(2026, 10, 8)
    at = lambda h, m, d=fri: datetime(d.year, d.month, d.day, h, m, tzinfo=build.JST)  # noqa: E731
    assert build.stale_reason(at(17, 20), fri, 0.99) is None
    assert "当日の日足がまだありません" in build.stale_reason(at(17, 20), thu, 0.99)
    assert "少なすぎます" in build.stale_reason(at(17, 20), fri, 0.30)      # 当日分が一部の銘柄にしか無い
    assert build.stale_reason(at(8, 0), thu, 0.99) is None                  # 朝に前の取引日の分を作るのは正常
    assert build.stale_reason(at(11, 55), thu, 0.99) is None                # 昼は対象外（前場の検査は別にある）
    assert build.stale_reason(at(17, 20, date(2026, 10, 12)), fri, 0.99) is None   # 休場日は当日の日足が無くて正常
    assert build.stale_reason(at(17, 20, date(2026, 10, 10)), fri, 0.99) is None   # 土曜


def test_premium_days_follow_the_settlement_calendar():
    # 逆日歩は、受渡し（2取引日後）から次の受渡しまでの暦日数分かかる
    from datetime import date
    assert market_days.premium_days(date(2026, 10, 8)) == 1     # 木曜: 受渡し 10/13 → 次は 10/14
    assert market_days.premium_days(date(2026, 10, 7)) == 4     # 水曜: 受渡し 10/9（金）→ 次は祝日明けの 10/13（火）
    assert market_days.premium_days(date(2026, 9, 30)) == 3     # ふだんの水曜: 週末をまたいで3日
    assert market_days.premium_days(date(2026, 10, 1)) == 1
    # 値動きの理由の表に出す逆日歩は、合計の額と1日あたりの両方を持つ
    p, base, disc, days, last = _reason_panel()
    premium = pd.DataFrame([{"code": "1001", "date": pd.Timestamp("2026-10-07"), "rate": 0.2, "max_rate": 2.0, "days": 4}])
    ex = rsn.Extras(disclosures=disc, disclosure_days=days, premium=premium)
    pr = rsn.compute(p, base, ex, last + pd.Timedelta(hours=17)).detail["1001"]["premium"]
    assert (pr["rate"], pr["days"], pr["daily"], pr["max"]) == (0.2, 4, 0.05, 2.0)


def test_next_update_skips_closed_days():
    from datetime import datetime
    at = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=build.JST)  # noqa: E731
    nxt = lambda s: market_days.next_update(at(s)).strftime("%Y-%m-%d %H:%M")        # noqa: E731
    assert nxt("2026-10-08 12:01") == "2026-10-08 17:30"      # 昼の実行のあとは夕方（自分自身の 12:05 は数えない）
    assert nxt("2026-10-08 17:25") == "2026-10-09 12:05"      # 夕方の実行のあとは翌日の昼
    assert nxt("2026-10-09 17:25") == "2026-10-13 12:05"      # 金曜の夕方 → 土日と祝日（10/12）を飛ばして火曜
    assert nxt("2026-10-09 11:00") == "2026-10-09 12:05"      # 午前に手で作った場合
    assert nxt("2026-12-30 17:25") == "2027-01-04 12:05"      # 年末年始


def test_morning_session_uses_morning_volume_and_cutoff():
    # 昼の実行（前場の引け後）: 出来高は前場の分なので、1日平均の1.5倍以上で急増とみる。
    # 11:30 以降の開示は前場の値動きの理由にせず、後場の材料として一覧に出す
    p, base, disc, days, last = _reason_panel()
    vol = p.volume.copy()
    vol.iloc[-1, 4] = 20000.0            # 1004: 1日平均の2倍・値動きなし（夕方の基準3倍には届かない）
    p = data.Panel(p.open, p.high, p.low, p.close, vol, p.master)
    disc = pd.concat([disc, pd.DataFrame([{"time": last + pd.Timedelta(hours=11, minutes=40), "code": "1001",
                                           "title": "業績予想の上方修正に関するお知らせ", "url": None}])])
    ex = rsn.Extras(disclosures=disc, disclosure_days=days)
    now = last + pd.Timedelta(hours=11, minutes=55)
    close = rsn.compute(p, base, ex, now, session="close")
    am = rsn.compute(p, base, ex, now, session="am")
    assert pd.isna(close.latest.at["1004", "why"])
    assert am.latest.at["1004", "why"] == "supply" and am.latest.at["1004", "why_text"] == "出来高急増・値動き小"
    assert am.detail["1004"]["clues"][0]["text"].startswith("前場だけで出来高が1日平均の2.0倍")
    assert close.latest.at["1001", "why"] == "news"          # 大引け後なら 11:40 の開示も当日の理由
    assert am.latest.at["1001", "why"] == "unknown"          # 前場の理由にはしない
    # 11:40 の開示は「後場の材料」、引け後（16:00）の開示は「次の取引日の材料」
    assert {x["pending"] for x in am.disclosures["1001"] if x["day"] is None} == {"pm", "next"}
    # 開示の一覧でも、昼の実行では 11:40 の開示は「これからの材料」（大引け後なら当日に効いた開示）
    assert ("1001", "業績修正", "pm") in [(x["code"], x["category"], x["pending"]) for x in am.feed if x["day"] is None]
    assert [x["category"] for x in close.feed if x["code"] == "1001" and x["day"] is not None] == ["業績修正"]
    assert am.latest.at["1001", "disc"] == "業績修正" and close.latest.at["1001", "disc"] == "決算"


def test_disclosure_feed_lists_upcoming_and_todays_items():
    # 開示の一覧: 引け後の開示（次の取引日の材料）と、最新日に効いた開示（その日の値動き付き）。定例は出さない
    p, base, disc, days, last = _reason_panel()
    extra = pd.DataFrame([
        {"time": last + pd.Timedelta(hours=16, minutes=5), "code": "1001",
         "title": "通期業績予想の上方修正に関するお知らせ", "url": None},
        {"time": last + pd.Timedelta(hours=16, minutes=10), "code": "1003",
         "title": "定款の一部変更に関するお知らせ", "url": None},
    ])
    ex = rsn.Extras(disclosures=pd.concat([disc, extra], ignore_index=True), disclosure_days=days)
    rs = rsn.compute(p, base, ex, last + pd.Timedelta(hours=17))
    upcoming = [(x["code"], x["category"], x["pending"]) for x in rs.feed if x["day"] is None]
    assert upcoming == [("1001", "業績修正", "next"), ("1001", "決算", "next")]     # 銘柄の中は、効きそうな順
    today = {x["code"]: x for x in rs.feed if x["day"] is not None}
    assert set(today) == {"1000", "1002"}                    # 前日の引け後（1000）と当日の場中（1002）の開示
    assert today["1000"]["ret"] > 15 and today["1000"]["idio"] > 10 and today["1002"]["kind"] == "supply"
    assert all("ret" not in x for x in rs.feed if x["day"] is None)                # まだ値動きに効いていない
    # 一覧の行に付ける印は、これからの材料の先頭だけ（当日に効いた開示は「値動きの理由」の側に出ている）
    assert (rs.latest.at["1001", "disc"], rs.latest.at["1001", "disc_text"]) == ("業績修正", "業績予想の上方修正")
    assert pd.isna(rs.latest.at["1000", "disc"]) and pd.isna(rs.latest.at["1003", "disc"])


def test_short_clue_uses_only_recent_reports():
    short = pd.DataFrame({
        "code": ["4935", "4935"], "holder": ["A", "A"],
        "calc_date": pd.to_datetime(["2026-09-11", "2026-09-18"]),
        "ratio": [0.06, 0.05], "prev_ratio": [0.07, 0.06],
    })
    all_ = rsn._short_summary(short)["4935"]
    assert (all_["prev"], all_["now"], all_["change"]) == (7.0, 5.0, -2.0)
    assert rsn._short_summary(short, since=pd.Timestamp("2026-09-21")) == {}


def test_export_finite_drops_nan():
    assert export._finite({"a": [1.0, float("nan")], "b": {"c": float("inf")}, "d": "x"}) == \
        {"a": [1.0, None], "b": {"c": None}, "d": "x"}


# --- テーマ -------------------------------------------------------------------------

def test_theme_table_format():
    table = themes.parse("""
# 先頭のメモ
1234 最初のテーマより前の行は読まない
[テーマA]
説明: 説明の文
1000 あ社   # メモ
1001
[テーマB]
130A い社
""")
    assert [(t.name, t.desc, list(t.members)) for t in table] == [("テーマA", "説明の文", ["1000", "1001"]), ("テーマB", "", ["130A"])]
    assert table[0].members["1000"] == "あ社"
    for bad in ("[A]\n12 コードが短い", "[A]\n1000 x\n[A]\n1001 y"):     # 読めない行・同じテーマが2回
        try:
            themes.parse(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"読めてしまった: {bad!r}")


def test_theme_table_in_the_repo_is_readable():
    table = themes.load()
    assert len(table) >= 20 and all(len(t.members) >= 4 for t in table)
    assert {"サイバーセキュリティ", "自動運転"} <= {t.name for t in table}


def _theme_panel():
    """80銘柄・330営業日の合成データ。テーマAの8銘柄は、最後の5日だけ毎日+4%多く上げて売買代金が10倍。
    テーマBの8銘柄はふつう。3銘柄だけのテーマは判定しない。"""
    rng = np.random.default_rng(5)
    idx = pd.bdate_range("2025-06-02", periods=330)
    codes = [f"{2000 + i}" for i in range(80)]
    rets = rng.normal(0, 0.01, size=(330, 80))
    rets[-5:, :8] += 0.04
    close = pd.DataFrame(1000 * np.exp(np.cumsum(rets, axis=0)), index=idx, columns=codes)
    turnover = pd.DataFrame(1e8 * rng.uniform(0.8, 1.2, size=(330, 80)), index=idx, columns=codes)
    turnover.iloc[-5:, :8] *= 10
    liquid = pd.DataFrame(True, index=idx, columns=codes)
    table = [themes.Theme("A", "", dict.fromkeys(codes[:8], "")), themes.Theme("B", "", dict.fromkeys(codes[8:16], "")),
             themes.Theme("小さい", "", dict.fromkeys(codes[16:19], ""))]
    return close, turnover, liquid, table


def test_theme_rising_together_with_turnover_is_flagged():
    close, turnover, liquid, table = _theme_panel()
    a, b, small = themes.stats_at(close, turnover, liquid.iloc[-1], table)["themes"]
    w = a["w"]["5"]
    assert a["state"] == "surge" and a["flow"] and w["rel"] > 15 and w["up"] == 100 and 8 < w["tr"] < 12 and w["z"] > 4
    assert b["state"] is None and not b["flow"]
    assert small["state"] is None and small["w"]["5"]["z"] is None      # 銘柄が少ないテーマは判定しない
    # 値上がりだけで売買代金が増えていなければ「そろって上昇」まで（資金が集まっているとは出さない）
    flat = pd.DataFrame(1e8, index=turnover.index, columns=turnover.columns)
    quiet = themes.stats_at(close, flat, liquid.iloc[-1], table)["themes"][0]
    assert quiet["state"] == "surge" and not quiet["flow"] and quiet["w"]["5"]["tr"] == 1.0
    # 5日前の時点では、まだ何も起きていない
    before = themes.stats_at(close, turnover, liquid.iloc[-6], table, i=len(close) - 6)["themes"][0]
    assert before["state"] is None
    # 昼の実行は、最新日の売買代金が前場の分（1日の約半分）なので割り戻す
    half = turnover.copy()
    half.iloc[-1] *= themes.AM_SHARE
    am = themes.stats_at(close, half, liquid.iloc[-1], table, session="am")["themes"][0]["w"]["1"]["tr"]
    assert abs(am - a["w"]["1"]["tr"]) < 0.01
    # 画面用の一覧は、そろって上げているテーマを先に並べ、上げの大きい銘柄を付ける
    panel = data.Panel(close, close, close, close, turnover / close, pd.DataFrame(index=close.columns))
    result = themes.compute(panel, liquid, table=table)
    assert [t["name"] for t in result["themes"]][0] == "A" and len(result["themes"][0]["lead"]) == 3
    assert themes.hot_tag(result) == dict.fromkeys(close.columns[:8], ("A", True))
    assert result["turnover"]["2000"][0] > 8 and result["missing"] == []


def test_theme_moving_together_explains_a_move_without_disclosure():
    # テーマの銘柄がその日にそろって動いたら、開示の無い目立った動きに「地合い（テーマ）」と付ける
    close, turnover, liquid, table = _theme_panel()
    moves = themes.day_labels(close, liquid, table, days=3)
    last = close.index[-1].strftime("%Y-%m-%d")
    assert moves[(last, "2000")] == (1, "テーマ「A」がそろって上昇") and (last, "2010") not in moves
    p, base, disc, days, last = _reason_panel()
    day = last.strftime("%Y-%m-%d")
    ex = lambda: rsn.Extras(disclosures=disc, disclosure_days=days)  # noqa: E731
    up = {(day, "1001"): (1, "テーマ「T」がそろって上昇"), (day, "1000"): (1, "テーマ「T」がそろって上昇")}
    rs = rsn.compute(p, base, ex(), last + pd.Timedelta(hours=17), theme_moves=up)
    assert (rs.latest.at["1001", "why"], rs.latest.at["1001", "why_text"]) == ("market", "テーマ「T」がそろって上昇")
    assert rs.detail["1001"]["clues"][0]["key"] == "theme"
    assert rs.latest.at["1000", "why"] == "news"                      # 会社の開示があれば、そちらを理由にする
    down = {(day, "1001"): (-1, "テーマ「T」がそろって下落")}          # テーマは下げたのに、この銘柄は上げた
    assert rsn.compute(p, base, ex(), last + pd.Timedelta(hours=17), theme_moves=down).latest.at["1001", "why"] == "unknown"


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except Exception as e:  # テスト名と理由を並べて出す
                failed += 1
                print(f"FAIL {name}: {type(e).__name__}: {e}")
    sys.exit(1 if failed else 0)
