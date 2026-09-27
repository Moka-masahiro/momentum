import { useState } from "react";
import { api, paths, useData } from "../data";
import { Card, ErrorBox, Icon, Loading, RankBadge, Seg } from "../components/ui";
import { num, pct } from "../format";
import { back, go } from "../router";
import type { RankingResponse } from "../types";

const TURNOVER = [
  { value: "50000000", label: "5千万円〜" },
  { value: "100000000", label: "1億円〜" },
  { value: "1000000000", label: "10億円〜" },
  { value: "0", label: "制限なし" },
];

export default function Ranking() {
  const [segment, setSegment] = useState("");
  const [turnover, setTurnover] = useState("50000000");
  const [limit, setLimit] = useState(50);
  const key = paths.ranking(segment, Number(turnover), limit);
  const { data, error, loading, reload } = useData<RankingResponse>(key, () => api.ranking(segment, Number(turnover), limit));

  return (
    <div>
      <div className="top-bar">
        <button className="icon-btn" onClick={back} aria-label="戻る"><Icon name="back" /></button>
        <h1>モメンタム度ランキング</h1>
        <span />
      </div>
      <div className="stack">
        <Seg value={segment} onChange={(v) => { setSegment(v); setLimit(50); }}
          options={[{ value: "", label: "全市場" }, { value: "プライム", label: "プライム" }, { value: "スタンダード", label: "スタンダード" }, { value: "グロース", label: "グロース" }]} />
        <div>
          <div className="note mb-1 px-1">売買代金（20日平均）</div>
          <Seg value={turnover} onChange={(v) => { setTurnover(v); setLimit(50); }} options={TURNOVER} />
        </div>
        {loading && !data && <Loading />}
        {error && !data && <ErrorBox message={error} onRetry={reload} />}
        {data && (
          <Card className={loading ? "fade-stale" : ""} sub={`該当 ${num(data.count)} 銘柄 · 終値100円以上 · ${data.as_of.replace(/-/g, "/")} 時点`}>
            <div className="list-head" style={{ gridTemplateColumns: "34px 1fr 54px auto 40px" }}>
              <span>順位</span><span>銘柄名</span><span className="text-right">1か月</span><span className="text-right">モメンタム度</span><span className="text-center">ランク</span>
            </div>
            {data.items.map((r, i) => (
              <button key={r.code} className="list-row" style={{ gridTemplateColumns: "34px 1fr 54px auto 40px" }} onClick={() => go(`stock/${r.code}`)}>
                <span className="list-pos">#{i + 1}</span>
                <span className="list-name">
                  <b>{r.name}</b>
                  <small>{r.code} · {r.segment ?? "—"}{r.signals_today.length ? " · ⚡" : ""}</small>
                </span>
                <span className={`text-right text-[12px] num ${r.chg20 != null && r.chg20 >= 0 ? "t-up" : "t-down"}`}>{pct(r.chg20)}</span>
                <span className="list-val">{num(r.score)}</span>
                <span className="text-center"><RankBadge rank={r.rank} /></span>
              </button>
            ))}
            {data.items.length < data.count && limit < 500 && (
              <button className="btn-ghost w-full mt-2 text-[13px]" onClick={() => setLimit(Math.min(500, limit + 50))}>
                さらに50件
              </button>
            )}
            <p className="note mt-3">
              並びはモメンタム度の順（値が同じときは元の合成z値の順）。⚡は本日シグナルが出た銘柄。
              上位ほど「今のトレンドが強い」銘柄ですが、これまでの検証では、上位がその後も市場平均を上回るとは言えません（検証画面）。
            </p>
          </Card>
        )}
      </div>
    </div>
  );
}
