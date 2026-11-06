import { useState } from "react";
import { RxLine, RxTrends, TIMING, rx5Label } from "../components/Reaction";
import { api, paths, useData } from "../data";
import { Card, Delta, ErrorBox, Icon, Loading, RankBadge, ScopeChecks, Seg, SessionBadge } from "../components/ui";
import { mdDate, mdTime, num, pct, slashDate } from "../format";
import { back, go } from "../router";
import type { DisclosureGroup, DisclosuresResponse, FeedItem } from "../types";
import { watchlist } from "../watch";

type Tab = "upcoming" | "today" | "trends";
type Sort = "r" | "tr" | "r5";
const SORT_LABEL: Record<Sort, string> = { r: "市場比", tr: "売買代金", r5: "5日" };
const NEW = "@new";   // 分類の絞り込みに並べる「新着」（分類ではなく、開示だけの更新で見つかったもの）

/**
 * 会社の適時開示の一覧（定例を除く）。「これからの材料」は引け後に出て、まだ値動きに効いていない開示
 * （昼の更新では 11:30 以降＝後場の材料）。「効いた開示」は最新日の値動きに効いた開示と、その日の騰落率。
 * 並びと分類は pipeline/momentum/reasons.py・export.py が決める。ここは絞り込むだけ。
 * 「新着」は、株価を取得した夕方の更新のあとで、開示だけ取り直して見つかったもの（#/disclosures/new で絞って開く）。
 */
export default function Disclosures({ initial }: { initial?: string }) {
  const { data, error, loading, reload } = useData<DisclosuresResponse>(paths.disclosures, api.disclosures);
  const [tab, setTab] = useState<Tab>("upcoming");
  const [category, setCategory] = useState(initial === "new" ? NEW : "");
  const [liquidOnly, setLiquidOnly] = useState(true);
  const [watchOnly, setWatchOnly] = useState(false);
  const [limit, setLimit] = useState(50);
  const [day, setDay] = useState("");
  const [sort, setSort] = useState<Sort>("r");

  const am = data?.session === "am";
  // ウォッチリストの銘柄は、流動性が無くても出す（自分で選んだ銘柄なので）
  const pool = (t: "upcoming" | "today") =>
    (data?.[t] ?? []).filter((g) => (watchOnly ? g.watched : !liquidOnly || g.stock.liquid || g.watched));
  // 効いた開示は直近5取引日分。日を選んで見る（既定は最新日）
  const days = [...new Set((data?.today ?? []).map((g) => g.day ?? ""))].filter(Boolean).sort().reverse();
  const activeDay = days.includes(day) ? day : days[0] ?? "";
  const base = tab === "trends" ? [] : tab === "today" ? pool("today").filter((g) => g.day === activeDay) : pool("upcoming");
  const counts = new Map<string, number>();
  for (const g of base) for (const c of new Set(g.items.map((x) => x.category))) counts.set(c, (counts.get(c) ?? 0) + 1);
  const fresh = base.filter((g) => g.items.some((x) => x.late)).length;
  const active = category === NEW ? (fresh > 0 ? NEW : "") : counts.has(category) ? category : "";
  const match = (x: FeedItem) => (active === NEW ? !!x.late : x.category === active);
  const head = (g: DisclosureGroup): FeedItem => (active && g.items.find(match)) || g.items[0];
  const hits = active ? base.filter((g) => g.items.some(match)) : base;
  // これからの材料はデータの順（売買代金の大きい順）。効いた開示は選んだ指標の大きい順（市場比・5日は上げ下げを問わず
  // 動きの大きい順、売買代金は倍率の大きい順。反応の無い古いデータは業種との差）。どちらも、ウォッチリストの銘柄を先頭に寄せる
  const key = (g: DisclosureGroup): number => {
    const rx = head(g).rx;
    if (sort === "tr") return rx?.tr ?? -1;
    if (sort === "r5") return Math.abs(rx?.r5 ?? 0);
    return Math.abs(rx ? rx.r ?? 0 : head(g).idio ?? 0);
  };
  const rows = (tab === "today" ? [...hits].sort((a, b) => key(b) - key(a)) : [...hits])
    .sort((a, b) => Number(b.watched) - Number(a.watched));
  const hasRx = (data?.today ?? []).some((g) => g.items.some((x) => x.rx));
  const anyWatched = watchlist().length > 0;
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
                { value: "upcoming" as const, label: `${am ? "後場の材料" : "次の取引日"} ${pool("upcoming").length}` },
                { value: "today" as const, label: "効いた開示" },
                { value: "trends" as const, label: "種類ごとの傾向" },
              ]} />
            {tab === "today" && days.length > 1 && (
              <div className="mt-2">
                <Seg value={activeDay} onChange={(v) => { setDay(v); reset(); }}
                  options={days.map((d) => ({ value: d, label: `${mdDate(d)} ${pool("today").filter((g) => g.day === d).length}` }))} />
              </div>
            )}
            {tab === "today" && hasRx && (
              <div className="mt-2 flex items-center gap-2">
                <span className="note">並べ替え</span>
                <Seg value={sort} onChange={(v) => { setSort(v); reset(); }}
                  options={(Object.keys(SORT_LABEL) as Sort[]).map((s) => ({ value: s, label: SORT_LABEL[s] }))} />
              </div>
            )}
            {tab !== "trends" && <div className="mt-2">
              <Seg value={active} onChange={(v) => { setCategory(v); reset(); }}
                options={[{ value: "", label: `すべて ${base.length}` },
                  ...(fresh > 0 ? [{ value: NEW, label: `新着 ${fresh}` }] : []),
                  ...[...counts.entries()].sort((a, b) => b[1] - a[1]).map(([c, n]) => ({ value: c, label: `${c} ${n}` }))]} />
            </div>}
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 mt-3">
              <span className="note flex items-center gap-1.5">
                {tab === "trends" ? "過去の開示への反応の集計"
                  : tab === "upcoming" ? `${slashDate(data.as_of)} ${am ? "11:30 以降の開示" : "引け後の開示"}`
                  : `${slashDate(activeDay || data.as_of)} ${am && activeDay === data.as_of ? "の前場" : "の値動き"}`}
                {tab !== "trends" && <SessionBadge session={data.session} />}
              </span>
              <ScopeChecks hasWatch={anyWatched} watchOnly={watchOnly} onWatch={(v) => { setWatchOnly(v); reset(); }}
                liquidOnly={liquidOnly} onLiquid={(v) => { setLiquidOnly(v); reset(); }} />
            </div>
            {!data.ok && <p className="note t-warn mt-2">開示を取得できなかった日があります。一覧に出ていない開示があるかもしれません。</p>}
          </div>

          {tab === "trends" ? (
            <Card title="開示の種類ごとの市場の反応" guide="disclosures-trends">
              <RxTrends liquidOnly={liquidOnly && !watchOnly} />
            </Card>
          ) : (
          <Card guide="disclosures-list">
            <div className="list-head" style={{ gridTemplateColumns: "1fr auto" }}>
              <span>銘柄名・開示</span><span className="text-right">{tab === "today" ? (hasRx ? SORT_LABEL[sort === "r5" ? "r5" : "r"] : am ? "前場の騰落" : "当日の騰落") : "ランク"}</span>
            </div>
            {rows.slice(0, limit).map((g) => {
              const x = head(g);
              return (
                <button key={g.stock.code} className="list-row" style={{ gridTemplateColumns: "1fr auto" }} onClick={() => go(`stock/${g.stock.code}`)}>
                  <span className="list-name">
                    <b>{g.watched && <span className="t-gold">★ </span>}{g.stock.name}</b>
                    <small className="list-sub">
                      {x.late && <span className="why why-new">新着</span>}
                      <span className={`why why-${x.kind}`}>{x.category}</span>
                      <span>
                        {g.stock.code} · {when(x)}{g.items.length > 1 ? ` · ほか${g.items.length - 1}件` : ""}
                        {!x.late && g.items.some((y) => y.late) ? "（新着あり）" : ""}
                      </span>
                    </small>
                    <span className="list-title">{x.title}</span>
                    {tab === "today" && <RxLine rx={x.rx} />}
                  </span>
                  {tab === "today" && x.rx ? (
                    <span className="text-right leading-tight">
                      <span className="block text-[14px] font-semibold">
                        <Delta v={sort === "r5" ? x.rx.r5 : x.rx.r} />
                      </span>
                      <span className="block text-[10.5px] t-3 num">
                        {sort === "r5" ? rx5Label(x.rx) : TIMING[x.rx.t]}
                      </span>
                      <span className="block text-[10.5px] t-3 num">代金 {x.rx.tr == null ? "—" : `${num(x.rx.tr, 1)}倍`}</span>
                    </span>
                  ) : tab === "today" ? (
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
          )}

          <Card title="見かた">
            <ul className="space-y-2 text-[13px] leading-snug t-1">
              <li>・<b>{am ? "後場の材料" : "次の取引日の材料"}</b>は、{am ? "前場の引け（11:30）より後" : "大引け（15:30）より後"}に出た開示です。まだ株価には反映されていません。売買代金の大きい銘柄から並べています（ウォッチリストの銘柄は先頭）。</li>
              <li>・<b>効いた開示</b>は、前の取引日の引け後から{am ? "前場の引け" : "その日の引け"}までに出た開示です（直近5取引日分。日付で切り替え）。
                寄り付き前の開示はその日、取引時間中の開示もその日（<b>場中の開示</b>。開示の前の値動きも含みます）、引け後・休日の開示は次の取引日に効いたとみなします。
                <b>市場比</b>はその日の騰落率と市場全体（終値100円以上の全銘柄）の中央値の差、<b>5日</b>は効いた日を含む5取引日の市場比（5日たつまでは途中の日数）、
                <b>窓</b>は前日終値から始値、<b>寄→引</b>は始値から終値、<b>代金</b>はその日の売買代金が普段（前250営業日の中央値）の何倍か。
                同じ日にほかの開示があった・テーマがそろって動いた・5日の間にほかの開示があったときは ※ で示します（開示だけが原因とは限りません）。
                動きの大きい順・売買代金の倍率の大きい順に並べ替えられます（ウォッチリストの銘柄は先頭）。</li>
              <li>・<b>種類ごとの傾向</b>は、過去の開示（最長で株価のある約2年）への反応を分類ごとに集計したものです。いずれも市場の反応という事実で、
                良い悪いの判定やこれからの値動きの予想ではありません。<b>反応とその後の値動きの関係は検証していません。</b></li>
              <li>・同じ銘柄に複数の開示があるときは、いちばん重要そうなものを見出しにして「ほか◯件」と出します。銘柄を押すと、詳細の「値動きの理由」で全部の表題と PDF を確認できます。</li>
              <li>・分類は表題の言葉から機械的に付けています（当てはまらないものは「その他」）。ガバナンス報告書や招集通知などの定例のものは出しません。ランクはモメンタム度のランクです。</li>
              <li>
                ・夕方の更新のあとに出た開示は、夜（19時前と20時すぎ）と翌朝（8時40分ごろ）に開示だけ取り直して足し、<span className="why why-new">新着</span> の印を付けます。株価と指標は夕方のままです。
                {data.since ? `いまの新着は、株価を取得した ${mdTime(data.since)} より後に見つかったものです。` : ""}
              </li>
            </ul>
            <p className="note mt-3">
              出どころは会社の適時開示（やのしん TDnet WEB-API 経由）。
              {data.fetched
                ? `${mdTime(data.fetched)} に取得${data.latest ? `（最も新しい開示は ${mdTime(data.latest)}）` : ""}。これより後に出た開示は、次の更新で入ります。`
                : data.latest ? `取得できた最も新しい開示は ${mdTime(data.latest)}。これより後に出た開示は、次の更新で入ります。` : ""}
              新聞報道やアナリストの格付けは含みません。該当 {num(rows.length)} 銘柄。
            </p>
          </Card>
        </div>
      )}
    </div>
  );
}
