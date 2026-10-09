import { useState } from "react";
import { api, paths, useData } from "../data";
import { Card, Delta, ErrorBox, Icon, Loading, RankBadge, Seg, SessionBadge } from "../components/ui";
import { mdTime, num, pct, slashDate } from "../format";
import { back, go } from "../router";
import type { DisclosureGroup, DisclosuresResponse, FeedItem } from "../types";

type Tab = "upcoming" | "today";

/**
 * 会社の適時開示の一覧（定例を除く）。「これからの材料」は引け後に出て、まだ値動きに効いていない開示
 * （昼の更新では 11:30 以降＝後場の材料）。「効いた開示」は最新日の値動きに効いた開示と、その日の騰落率。
 * 並びと分類は pipeline/momentum/reasons.py・export.py が決める。ここは絞り込むだけ。
 */
export default function Disclosures() {
  const { data, error, loading, reload } = useData<DisclosuresResponse>(paths.disclosures, api.disclosures);
  const [tab, setTab] = useState<Tab>("upcoming");
  const [category, setCategory] = useState("");
  const [liquidOnly, setLiquidOnly] = useState(true);
  const [watchOnly, setWatchOnly] = useState(false);
  const [limit, setLimit] = useState(50);

  const am = data?.session === "am";
  // ウォッチリストの銘柄は、流動性が無くても出す（自分で選んだ銘柄なので）
  const pool = (t: Tab) => (data?.[t] ?? []).filter((g) => (watchOnly ? g.watched : !liquidOnly || g.stock.liquid || g.watched));
  const base = pool(tab);
  const counts = new Map<string, number>();
  for (const g of base) for (const c of new Set(g.items.map((x) => x.category))) counts.set(c, (counts.get(c) ?? 0) + 1);
  const active = counts.has(category) ? category : "";
  const head = (g: DisclosureGroup): FeedItem => (active && g.items.find((x) => x.category === active)) || g.items[0];
  const hits = active ? base.filter((g) => g.items.some((x) => x.category === active)) : base;
  // これからの材料はデータの順（売買代金の大きい順）、効いた開示は業種との差の大きい順（反応の大きかったものから）。
  // どちらも、ウォッチリストの銘柄を先頭に寄せる
  const rows = (tab === "today" ? [...hits].sort((a, b) => Math.abs(head(b).idio ?? 0) - Math.abs(head(a).idio ?? 0)) : [...hits])
    .sort((a, b) => Number(b.watched) - Number(a.watched));
  const anyWatched = !!data && [...data.upcoming, ...data.today].some((g) => g.watched);
  const reset = () => setLimit(50);
  const when = (x: FeedItem) => (x.time.startsWith(data?.as_of ?? "-") ? x.time.slice(11) : mdTime(x.time));

  return (
    <div>
      <div className="top-bar">
        <button className="icon-btn" onClick={back} aria-label="戻る"><Icon name="back" /></button>
        <h1>適時開示</h1>
        <span />
      </div>
      {loading && !data && <Loading />}
      {error && !data && <ErrorBox message={error} onRetry={reload} />}
      {data && (
        <div className={`stack ${loading ? "fade-stale" : ""}`}>
          <div className="card !p-3" data-guide="disclosures-filter">
            <Seg value={tab} onChange={(v) => { setTab(v); setCategory(""); reset(); }}
              options={[
                { value: "upcoming" as const, label: `${am ? "後場の材料" : "次の取引日の材料"} ${pool("upcoming").length}` },
                { value: "today" as const, label: `${am ? "前場に効いた開示" : "効いた開示"} ${pool("today").length}` },
              ]} />
            <div className="mt-2">
              <Seg value={active} onChange={(v) => { setCategory(v); reset(); }}
                options={[{ value: "", label: `すべて ${base.length}` },
                  ...[...counts.entries()].sort((a, b) => b[1] - a[1]).map(([c, n]) => ({ value: c, label: `${c} ${n}` }))]} />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 mt-3">
              <span className="note flex items-center gap-1.5">
                {slashDate(data.as_of)} {tab === "upcoming" ? (am ? "11:30 以降の開示" : "引け後の開示") : (am ? "の前場" : "の値動き")}
                <SessionBadge session={data.session} />
              </span>
              <span className="flex items-center gap-3">
                {anyWatched && (
                  <label className="flex items-center gap-1.5 text-[13px] t-2">
                    <input type="checkbox" checked={watchOnly} onChange={(e) => { setWatchOnly(e.target.checked); reset(); }} />
                    ウォッチだけ
                  </label>
                )}
                <label className="flex items-center gap-1.5 text-[13px] t-2">
                  <input type="checkbox" checked={liquidOnly} disabled={watchOnly} onChange={(e) => { setLiquidOnly(e.target.checked); reset(); }} />
                  流動性あり
                </label>
              </span>
            </div>
            {!data.ok && <p className="note t-warn mt-2">開示を取得できなかった日があります。一覧に出ていない開示があるかもしれません。</p>}
          </div>

          <Card guide="disclosures-list">
            <div className="list-head" style={{ gridTemplateColumns: "1fr auto" }}>
              <span>銘柄名・開示</span><span className="text-right">{tab === "today" ? (am ? "前場の騰落" : "当日の騰落") : "ランク"}</span>
            </div>
            {rows.slice(0, limit).map((g) => {
              const x = head(g);
              return (
                <button key={g.stock.code} className="list-row" style={{ gridTemplateColumns: "1fr auto" }} onClick={() => go(`stock/${g.stock.code}`)}>
                  <span className="list-name">
                    <b>{g.watched && <span className="t-gold">★ </span>}{g.stock.name}</b>
                    <small className="list-sub">
                      <span className={`why why-${x.kind}`}>{x.category}</span>
                      <span>{g.stock.code} · {when(x)}{g.items.length > 1 ? ` · ほか${g.items.length - 1}件` : ""}</span>
                    </small>
                    <span className="list-title">{x.title}</span>
                  </span>
                  {tab === "today" ? (
                    <span className="text-right leading-tight">
                      <span className="block text-[14px] font-semibold"><Delta v={x.ret} /></span>
                      <span className="block text-[10.5px] t-3 num">業種比 {pct(x.idio)}</span>
                    </span>
                  ) : (
                    <span className="text-center"><RankBadge rank={g.stock.rank} /></span>
                  )}
                </button>
              );
            })}
            {rows.length === 0 && <p className="text-[13px] t-3 py-2">該当する開示はありません。</p>}
            {rows.length > limit && (
              <button className="btn-ghost w-full mt-2 text-[13px]" onClick={() => setLimit(limit + 50)}>さらに50件</button>
            )}
          </Card>

          <Card title="見かた">
            <ul className="space-y-2 text-[13px] leading-snug t-1">
              <li>・<b>{am ? "後場の材料" : "次の取引日の材料"}</b>は、{am ? "前場の引け（11:30）より後" : "大引け（15:30）より後"}に出た開示です。まだ株価には反映されていません。売買代金の大きい銘柄から並べています（ウォッチリストの銘柄は先頭）。</li>
              <li>・<b>効いた開示</b>は、前の取引日の引け後から{am ? "前場の引け" : "当日の引け"}までに出た開示と、その日の騰落率です。業種平均との差が大きい順に並べています（ウォッチリストの銘柄は先頭）。</li>
              <li>・同じ銘柄に複数の開示があるときは、いちばん重要そうなものを見出しにして「ほか◯件」と出します。銘柄を押すと、詳細の「値動きの理由」で全部の表題と PDF を確認できます。</li>
              <li>・分類は表題の言葉から機械的に付けています（当てはまらないものは「その他」）。ガバナンス報告書や招集通知などの定例のものは出しません。ランクはモメンタム度のランクです。</li>
            </ul>
            <p className="note mt-3">
              出どころは会社の適時開示（やのしん TDnet WEB-API 経由）。
              {data.latest ? `取得できた最も新しい開示は ${mdTime(data.latest)}。これより後に出た開示は、次の更新で入ります。` : ""}
              新聞報道やアナリストの格付けは含みません。該当 {num(rows.length)} 銘柄。
            </p>
          </Card>
        </div>
      )}
    </div>
  );
}
