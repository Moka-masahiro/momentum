"""回帰テスト（実データで踏んだ罠を合成データで再現する）。

    cd pipeline
    .venv\\Scripts\\python.exe tests\\test_momentum.py      # pytest が無くても動く
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import secure  # noqa: E402
from momentum import data, indicators as ind, signals as sig  # noqa: E402


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
