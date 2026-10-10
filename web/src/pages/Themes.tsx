import { useState } from "react";
import { api, paths, useData } from "../data";
import { Card, Delta, ErrorBox, Icon, Loading, RankBadge, Seg, SessionBadge, THEME_WINDOW, ThemeBadges, WhyNote } from "../components/ui";
import { num, pct, slashDate } from "../format";
import { back, go } from "../router";
import type { StockRow, Theme, ThemeMember, ThemesResponse } from "../types";
import { watchlist } from "../watch";

const WINDOWS = [
  { value: "1", label: "1日" },
  { value: "5", label: "5日" },
  { value: "20", label: "20日" },
  { value: "60", label: "60日" },
];
const CHG: Record<string, (r: StockRow) => number | null> = {
  "1": (r) => r.chg1, "5": (r) => r.chg5, "20": (r) => r.chg20, "60": (r) => r.chg60,
};
/** 売買代金の倍率。大きいほど小数を減らす */
const times = (v: number | null | undefined) => (v == null ? "—" : `${num(v, v < 10 ? 1 : 0)}倍`);

/**
 * テーマごとの値動きと売買代金（pipeline/momentum/themes.py）。テーマと銘柄の対応は手作りの表
 * （pipeline/themes.txt）で、網羅ではない。#/themes が一覧、#/themes/<テーマ名> がそのテーマの銘柄。
 */
export default function Themes({ name }: { name?: string }) {
  const { data, error, loading, reload } = useData<ThemesResponse>(paths.themes, api.themes);
  const theme = name ? data?.themes.find((t) => t.name === name) : undefined;
  return (
    <div>
      <div className="top-bar">
        <button className="icon-btn" onClick={back} aria-label="戻る"><Icon name="back" /></button>
        <h1>{name ?? "テーマ"}</h1>
        <span />
      </div>
      {loading && !data && <Loading />}
      {error && !data && <ErrorBox message={error} onRetry={reload} />}
      {data && !data.ok && <div className="card"><p className="note t-warn">この日はテーマを作れませんでした。</p></div>}
      {data && data.ok && (
        <div className={`stack ${loading ? "fade-stale" : ""}`}>
          {!name && <List data={data} />}
          {name && theme && <Detail data={data} theme={theme} />}
          {name && !theme && <div className="card"><p className="note">「{name}」というテーマは表にありません。</p></div>}
        </div>
      )}
    </div>
  );
}

/** いまの状況を1文にする（数字はデータから作る。固定の文面にしない） */
function headline(data: ThemesResponse): string {
  const hot = data.themes.filter((t) => t.state);
  const flow = hot.filter((t) => t.flow);
  if (flow.length) return `${flow.map((t) => `「${t.name}」`).join("")}に資金が集まっているかもしれません。`;
  if (hot.length) return `${hot.map((t) => `「${t.name}」`).join("")}がそろって上げています（売買代金は、市場全体と比べて特に膨らんではいません）。`;
  return "いま、そろって上げているテーマはありません。";
}

function List({ data }: { data: ThemesResponse }) {
  const hot = data.themes.filter((t) => t.state);
  const rest = data.themes.filter((t) => !t.state);
  return (
    <>
      <Card>
        <p className="text-[14px] font-semibold leading-snug">{headline(data)}</p>
        <p className="note mt-2 flex items-center gap-1.5">
          {slashDate(data.as_of)} 時点<SessionBadge session={data.session} />
          <span>· 数字は市場の中央値との差（市場比）</span>
        </p>
      </Card>

      <Card title="そろって上げているテーマ" aside={`${hot.length} / ${data.themes.length}`} guide="themes-list">
        {hot.map((t) => <ThemeRow key={t.name} t={t} />)}
        {hot.length === 0 && <p className="text-[13px] t-3 py-1">該当するテーマはありません。</p>}
      </Card>

      <Card title="そのほかのテーマ" sub="5日の上げが、ほかの銘柄より高い方に偏っている順">
        {rest.map((t) => <ThemeRow key={t.name} t={t} />)}
      </Card>

      <Card title="表に無い、5日で大きく上げた銘柄" guide="themes-loose"
        sub="どのテーマの表にも入っていない銘柄（流動性あり）。新しいテーマが動き出しているかもしれません">
        {data.loose.map((r) => (
          <button key={r.code} className="list-row" style={{ gridTemplateColumns: "1fr 62px 40px" }} onClick={() => go(`stock/${r.code}`)}>
            <span className="list-name">
              <b>{r.name}</b>
              <small className="list-sub"><span>{r.code} · {r.sector33 ?? "—"}</span><WhyNote row={r} /></small>
            </span>
            <span className="text-right text-[13px] font-semibold"><Delta v={r.chg5} /></span>
            <span className="text-center"><RankBadge rank={r.rank} /></span>
          </button>
        ))}
        {data.loose.length === 0 && <p className="text-[13px] t-3 py-1">該当する銘柄はありません。</p>}
        <p className="note mt-2">
          5日の上げが、市場の上位1割の線（市場比 {pct(data.big["5"])}）の2倍以上の銘柄を、上げの大きい順に15件まで出しています。
        </p>
      </Card>

      <Card title="見かた">
        <ul className="space-y-2 text-[13px] leading-snug t-1">
          <li>・<b>そろって上げている</b>は、テーマの真ん中の銘柄（中央値）が、全銘柄の上位1割に入るほど市場より上げていて、一部の銘柄だけの動きではないテーマです。5日で当たれば「5日で急騰」、20日だけなら「20日で上昇」、60日だけなら「60日で上昇」と出します。</li>
          <li>・そのうえで、売買代金が普段より大きく膨らんでいれば（市場全体の膨らみ方の1.5倍以上）、<span className="why why-flow">資金集中？</span> の印を付けます。大型株のテーマは、上げていても売買代金はあまり膨らまないので、印が付かないことがあります。</li>
          <li>・売買代金の「普段」は、その前の250営業日の中央値です。銘柄ごとに倍率を出して、テーマの中央値を取っています。</li>
          <li>・<b>テーマと銘柄の対応は手作りの表</b>です。網羅ではなく、誤りもありえます。表に無い銘柄は、どのテーマにも数えません。新しいテーマは、上の「表に無い、5日で大きく上げた銘柄」に先に現れます。</li>
        </ul>
        <p className="note mt-3">
          同じ業種の銘柄はもともと一緒に動くので、業種ごと動いたときにもテーマは当たります。「まとまって買われている」という観察で、
          理由の証明でも、この先も上がるという予想でもありません。数えているのは流動性のある銘柄（売買代金20日平均5,000万円以上）だけです。
        </p>
      </Card>
    </>
  );
}

function ThemeRow({ t }: { t: Theme }) {
  const w = t.w;
  const key = t.state ? THEME_WINDOW[t.state] : "5";
  return (
    <button className="list-row" style={{ gridTemplateColumns: "1fr auto" }} onClick={() => go(`themes/${encodeURIComponent(t.name)}`)}>
      <span className="list-name">
        <b>{t.name}</b>
        <small className="list-sub wrap">
          <ThemeBadges state={t.state} flow={t.flow} />
          <span>{t.n}銘柄 · 売買代金 {times(w[key]?.tr)}</span>
        </small>
        <span className="list-title">
          5日 <Delta v={w["5"]?.rel} /> · 20日 <Delta v={w["20"]?.rel} /> · 60日 <Delta v={w["60"]?.rel} />
        </span>
      </span>
      <span className="text-right leading-tight">
        <span className="block text-[15px] font-bold"><Delta v={w["1"]?.rel} /></span>
        <span className="block text-[10.5px] t-3">きょう</span>
      </span>
    </button>
  );
}

function Detail({ data, theme }: { data: ThemesResponse; theme: ThemesResponse["themes"][number] }) {
  const [win, setWin] = useState(theme.state ? THEME_WINDOW[theme.state] : "5");
  const watched = new Set(watchlist());
  const chg = CHG[win];
  const items = [...theme.items].sort((a, b) => (chg(b) ?? -1e9) - (chg(a) ?? -1e9));
  const s = theme.state ? theme.w[THEME_WINDOW[theme.state]] : null;
  return (
    <>
      <Card>
        {theme.desc && <p className="note !text-[12.5px]">{theme.desc}</p>}
        <div className="flex flex-wrap items-center gap-1.5 mt-2"><ThemeBadges state={theme.state} flow={theme.flow} /></div>
        <p className="text-[13.5px] leading-snug mt-2">
          {s ? (
            <>
              この{THEME_WINDOW[theme.state!]}日で、流動性のある {theme.n} 銘柄の中央値が市場より <b>{pct(s.rel)}</b> 高く、
              {num(s.up)}% の銘柄が市場を上回りました。売買代金は普段の <b>{times(s.tr)}</b>
              {theme.flow ? "に膨らんでいて、資金が集まっているかもしれません。" : "で、市場全体と比べて特に膨らんではいません。"}
            </>
          ) : "いまは、そろって上げてはいません。"}
        </p>
        <table className="tbl mt-3">
          <thead><tr><th>期間</th><th>市場比（中央値）</th><th>市場を上回った</th><th>売買代金</th></tr></thead>
          <tbody>
            {WINDOWS.map(({ value, label }) => {
              const x = theme.w[value];
              return x ? (
                <tr key={value}>
                  <td>{label}{x.hot ? " ●" : ""}</td>
                  <td><Delta v={x.rel} /></td>
                  <td>{x.up != null ? `${num(x.up)}%` : "—"}</td>
                  <td>{times(x.tr)}{x.flow ? " ↑" : ""}</td>
                </tr>
              ) : null;
            })}
          </tbody>
        </table>
        <p className="note mt-2">
          ● はそろって上げている期間、↑ は売買代金が市場全体より大きく膨らんでいる期間。{slashDate(data.as_of)} 時点。
        </p>
      </Card>

      <Card title="銘柄" aside={`${theme.items.length} 銘柄`}>
        <Seg value={win} onChange={setWin} options={WINDOWS} />
        <div className="list-head mt-3" style={{ gridTemplateColumns: "1fr 62px 40px" }}>
          <span>銘柄名・売買代金（20日）</span><span className="text-right">騰落</span><span className="text-center">ランク</span>
        </div>
        {items.map((r: ThemeMember) => (
          <button key={r.code} className="list-row" style={{ gridTemplateColumns: "1fr 62px 40px" }} onClick={() => go(`stock/${r.code}`)}>
            <span className="list-name">
              <b>{watched.has(r.code) && <span className="t-gold">★ </span>}{r.name}</b>
              <small className="list-sub">
                <span>{r.code} · {r.liquid ? `普段の${times(r.tr20)}` : "流動性なし（集計の対象外）"}</span>
                <WhyNote row={r} text={false} />
              </small>
            </span>
            <span className="text-right text-[13px] font-semibold"><Delta v={chg(r)} /></span>
            <span className="text-center"><RankBadge rank={r.rank} /></span>
          </button>
        ))}
        <p className="note mt-2">
          騰落はその銘柄の値（市場比ではありません）。市場の中央値は {WINDOWS.find((x) => x.value === win)?.label}で {pct(data.market[win])}。
          銘柄の選び方は手作りの表によるもので、網羅ではありません。
        </p>
      </Card>
    </>
  );
}
