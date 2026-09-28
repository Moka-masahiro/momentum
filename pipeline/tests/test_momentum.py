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
import secure  # noqa: E402
from momentum import data, export, indicators as ind, reasons as rsn, signals as sig  # noqa: E402


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
