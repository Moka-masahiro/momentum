import { useState } from "react";
import { api, paths, useData } from "../data";
import { Card, Delta, ErrorBox, Icon, Loading, RankBadge } from "../components/ui";
import { mdDate, num, pct } from "../format";
import { back, go } from "../router";
import type { SignalGroup, SignalsResponse } from "../types";

export default function Signals({ date }: { date?: string }) {
  const { data, error, loading, reload } = useData<SignalsResponse>(paths.signals(date), () => api.signals(date));
  const [liquidOnly, setLiquidOnly] = useState(true);

  return (
    <div>
      <div className="top-bar">
        <button className="icon-btn" onClick={back} aria-label="戻る"><Icon name="back" /></button>
        <h1>シグナル</h1>
        <span />
      </div>
      {loading && !data && <Loading />}
      {error && !data && <ErrorBox message={error} onRetry={reload} />}
      {data && (
        <div className={`stack ${loading ? "fade-stale" : ""}`}>
          <div data-guide="signal-date" className="card !p-3">
            <div className="note mb-2">日付（直近20営業日）</div>
            <div className="flex gap-1.5 overflow-x-auto pb-1" style={{ scrollbarWidth: "none" }}>
              {data.dates.map((d, i) => (
                <button key={d} className={`chip ${d === data.date ? "chip-on" : ""}`} onClick={() => go(i === 0 ? "signals" : `signals/${d}`)}>
                  {mdDate(d)}
                </button>
              ))}
            </div>
            <div className="flex items-center justify-between mt-3">
              <div>
                <span className="text-[26px] font-extrabold t-accent">{num(data.total)}</span>
                <span className="t-2 text-[13px] ml-1">件（{mdDate(data.date)}）</span>
              </div>
              <label className="flex items-center gap-2 text-[13px] t-2">
                <input type="checkbox" checked={liquidOnly} onChange={(e) => setLiquidOnly(e.target.checked)} />
                流動性のある銘柄だけ
              </label>
            </div>
          </div>
          <div className="card !py-3" style={{ borderColor: "rgba(232,199,111,0.4)" }}>
            <p className="prose !text-[12.5px]">
              シグナルは「その日に起きたこと」の検知で、予想ではありません。各シグナルの実績は、
              <b>翌営業日の始値で入り、N営業日後の終値まで</b>の値動きを、<b>同じ期間の市場平均との差</b>で測っています。
              相場全体が上がった期間は、どんなシグナルでも素の成績はプラスに見えるためです。
            </p>
          </div>
          {data.groups.map((g, i) => (
            <Group key={g.key} g={g} liquidOnly={liquidOnly} guide={i === 0 ? "signal-group" : undefined} />
          ))}
        </div>
      )}
    </div>
  );
}

function Group({ g, liquidOnly, guide }: { g: SignalGroup; liquidOnly: boolean; guide?: string }) {
  const [open, setOpen] = useState(false);
  const items = liquidOnly ? g.items.filter((x) => x.liquid) : g.items;
  const shown = open ? items : items.slice(0, 8);
  return (
    <Card guide={guide}
      title={<span className="flex items-center gap-2">{g.label}{g.tone === "warn" && <span className="chip chip-warn">警戒</span>}</span>}
      aside={`${items.length} 件`}>
      <p className="note -mt-1">{g.rule}</p>
      <StatTile g={g} />
      <div className="mt-2">
        {shown.length === 0 && <p className="text-[13px] t-3 py-2">この日の発動はありません。</p>}
        {shown.map((r) => (
          <button key={r.code} className="list-row" style={{ gridTemplateColumns: "1fr 58px auto 40px" }} onClick={() => go(`stock/${r.code}`)}>
            <span className="list-name"><b>{r.name}</b><small>{r.code} · {r.segment ?? "—"}{!r.liquid ? " · 薄商い" : ""}</small></span>
            <span className="text-right text-[12px]"><Delta v={r.chg1} /></span>
            <span className="text-right text-[16px] font-bold num">{num(r.score)}</span>
            <span className="text-center"><RankBadge rank={r.rank} /></span>
          </button>
        ))}
      </div>
      {items.length > 8 && (
        <button className="btn-ghost w-full mt-2 text-[13px]" onClick={() => setOpen(!open)}>
          {open ? "閉じる" : `すべて表示（${items.length}件）`}
        </button>
      )}
    </Card>
  );
}

function StatTile({ g }: { g: SignalGroup }) {
  const st = g.stats;
  if (!st) return null;
  return (
    <div className="tile mt-2">
      <div className="text-[11.5px] t-2 mb-1">これまでの実績（流動性のある銘柄の発動 {num(st.events)} 件）</div>
      <table className="tbl">
        <thead>
          <tr><th></th><th>5日後</th><th>10日後</th><th>20日後</th></tr>
        </thead>
        <tbody>
          <tr>
            <td>市場平均との差</td>
            {(["5", "10", "20"] as const).map((h) => <td key={h}><Delta v={st.horizons[h]?.excess_mean} digits={2} /></td>)}
          </tr>
          <tr>
            <td>勝率（市場比）</td>
            {(["5", "10", "20"] as const).map((h) => <td key={h}>{num(st.horizons[h]?.win_rate, 1)}%</td>)}
          </tr>
          <tr>
            <td>（参考）素の平均</td>
            {(["5", "10", "20"] as const).map((h) => <td key={h} className="t-3">{pct(st.horizons[h]?.ret_mean, 2)}</td>)}
          </tr>
        </tbody>
      </table>
      <div className="note mt-1">
        {(["5", "10", "20"] as const).some((h) => st.horizons[h]?.significant)
          ? "一部の期間で統計的に有意な差があります（t値2以上）。"
          : `どの期間も有意差なし（20日後の t値 ${num(st.horizons["20"]?.t, 2)}）。偶然と区別できない水準です。`}
      </div>
    </div>
  );
}
