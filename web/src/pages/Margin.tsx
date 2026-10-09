import { useState } from "react";
import { api, paths, useData } from "../data";
import { Card, ErrorBox, Icon, Loading, RankBadge, ScopeChecks, Seg } from "../components/ui";
import { mdDate, num, shares } from "../format";
import { back, go } from "../router";
import type { MarginResponse, MarginRow } from "../types";
import { watchlist } from "../watch";

type Order = "low" | "high";

const COLS = "1fr 66px 36px";
// 並べる側の残高が、直前20日平均の出来高の何日分以上あるか（低い順は売り残、高い順は買い残で見る）
const SIZE = [
  { value: "1", label: "1日分〜" },
  { value: "0.3", label: "0.3日分〜" },
  { value: "0", label: "制限なし" },
];

const oku = (v: number) => `${num(v / 1e8, 1)}億株`;
/** 倍率。売り残がわずかだと数百倍になるので、大きいほど小数を減らす */
const times = (v: number | null) => num(v, v == null || v < 10 ? 2 : v < 100 ? 1 : 0);

/**
 * 制度信用倍率（制度信用の買い残 ÷ 売り残）の一覧。JPX「銘柄別信用取引残高」のうち制度信用の分だけで、
 * 一般信用（証券会社ごとの無期限・1日信用など）は入れない。倍率を出せるのは制度信用の売り残がある銘柄だけ。
 */
export default function Margin() {
  const { data, error, loading, reload } = useData<MarginResponse>(paths.margin, api.margin);
  const [order, setOrder] = useState<Order>("low");
  const [segment, setSegment] = useState("");
  const [size, setSize] = useState("1");
  const [liquidOnly, setLiquidOnly] = useState(true);
  const [watchOnly, setWatchOnly] = useState(false);
  const [limit, setLimit] = useState(50);

  const low = order === "low";
  const days = (r: MarginRow) => (low ? r.m.sell_days : r.m.buy_days) ?? 0;
  const watched = new Set(watchlist());
  // ウォッチリストだけのときは、流動性や残高の大きさでは落とさない（自分で選んだ銘柄なので）
  const items = (data?.items ?? [])
    .filter((r) => r.m.ratio != null && (!segment || r.segment === segment)
      && (watchOnly ? watched.has(r.code) : (!liquidOnly || r.liquid) && days(r) >= Number(size)))
    .sort((a, b) => (low ? a.m.ratio! - b.m.ratio! : b.m.ratio! - a.m.ratio!) || days(b) - days(a));
  const s = data?.summary;
  const reset = () => setLimit(50);

  return (
    <div>
      <div className="top-bar">
        <button className="icon-btn" onClick={back} aria-label="戻る"><Icon name="back" /></button>
        <h1>制度信用倍率</h1>
        <span />
      </div>
      {loading && !data && <Loading />}
      {error && !data && <ErrorBox message={error} onRetry={reload} />}
      {data && !s && (
        <div className="card"><p className="note t-warn">この日は JPX の信用残を取得できなかったため、一覧を作れませんでした。</p></div>
      )}
      {data && s && (
        <div className={`stack ${loading ? "fade-stale" : ""}`}>
          <div className="card !p-3" data-guide="margin-filter">
            <Seg value={order} onChange={(v) => { setOrder(v); reset(); }}
              options={[{ value: "low" as const, label: "低い順（売り長）" }, { value: "high" as const, label: "高い順（買い長）" }]} />
            <div className="mt-2">
              <Seg value={segment} onChange={(v) => { setSegment(v); reset(); }}
                options={[{ value: "", label: "全市場" }, { value: "プライム", label: "プライム" }, { value: "スタンダード", label: "スタンダード" }, { value: "グロース", label: "グロース" }]} />
            </div>
            <div className="mt-2">
              <div className="note mb-1 px-1">{low ? "売り残" : "買い残"}の大きさ（出来高20日平均の何日分か）</div>
              <Seg value={size} onChange={(v) => { setSize(v); reset(); }} options={SIZE} />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 mt-3">
              <span className="note">{mdDate(data.date)} 申込み分 · 該当 {num(items.length)} 銘柄</span>
              <ScopeChecks hasWatch={watched.size > 0} watchOnly={watchOnly} onWatch={(v) => { setWatchOnly(v); reset(); }}
                liquidOnly={liquidOnly} onLiquid={(v) => { setLiquidOnly(v); reset(); }} />
            </div>
          </div>

          <Card guide="margin-list">
            <div className="list-head" style={{ gridTemplateColumns: COLS }}>
              <span>銘柄名・{low ? "売り残" : "買い残"}</span><span className="text-right">倍率</span><span className="text-center">ランク</span>
            </div>
            {items.slice(0, limit).map((r) => (
              <button key={r.code} className="list-row" style={{ gridTemplateColumns: COLS }} onClick={() => go(`stock/${r.code}`)}>
                <span className="list-name">
                  <b>{watched.has(r.code) && <span className="t-gold">★ </span>}{r.name}</b>
                  <small className="list-sub">
                    <span>{r.code} · {low ? "売り残" : "買い残"} {shares(low ? r.m.sell : r.m.buy)}</span>
                    <span className="why-text">{days(r) ? `${num(days(r), 1)}日分` : ""}</span>
                  </small>
                </span>
                <span className="text-right leading-tight">
                  <span className="block text-[16px] font-bold num">{times(r.m.ratio)}<span className="text-[11px] t-2 font-semibold">倍</span></span>
                  <span className="block text-[10.5px] t-3 num">前日 {times(r.m.ratio_prev)}</span>
                </span>
                <span className="text-center"><RankBadge rank={r.rank} /></span>
              </button>
            ))}
            {items.length === 0 && <p className="text-[13px] t-3 py-2">該当する銘柄はありません。</p>}
            {items.length > limit && (
              <button className="btn-ghost w-full mt-2 text-[13px]" onClick={() => setLimit(limit + 50)}>さらに50件</button>
            )}
          </Card>

          <Card title="全銘柄の合計" sub="制度信用の買い残の合計 ÷ 売り残の合計（一般信用は含まない）">
            <div className="grid grid-cols-2 gap-2">
              <div className="tile">
                <div className="text-[12px] t-2">制度信用倍率</div>
                <div className="text-[20px] font-bold num">{num(s.ratio, 2)}<span className="text-[13px] t-2 ml-0.5">倍</span></div>
                <div className="note !text-[11px]">前日 {num(s.ratio_prev, 2)}倍</div>
              </div>
              <div className="tile">
                <div className="text-[12px] t-2">売り長（1倍未満）</div>
                <div className="text-[20px] font-bold num">{num(s.short)}<span className="text-[13px] t-2 ml-0.5">銘柄</span></div>
                <div className="note !text-[11px]">倍率のある {num(s.rated)} 銘柄中</div>
              </div>
            </div>
            <p className="note mt-2">
              買い残 {oku(s.buy)} ÷ 売り残 {oku(s.sell)}（信用残を読めた {num(s.stocks)} 銘柄。ETF・REIT は含まない）。
            </p>
          </Card>

          <Card title="見かた">
            <ul className="space-y-2 text-[13px] leading-snug t-1">
              <li>・<b>制度信用倍率 ＝ 制度信用の買い残 ÷ 売り残。</b>1倍未満は売り残の方が多い「売り長」、大きいほど買い残に偏った「買い長」です。</li>
              <li>・売り残はいずれ買い戻される株、買い残はいずれ売られる株です（制度信用は6か月以内に決済）。売り長の銘柄は上がると買い戻しが重なりやすく、買い長の銘柄は上値で売りが出やすい、と言われます。</li>
              <li>・「◯日分」は、その残高が直前20日平均の出来高の何日分に当たるかです。倍率が極端でも、残高が小さければ値動きへの影響は小さくなります。</li>
              <li>・一般信用（証券会社ごとの無期限・1日信用など）は入れていません。銘柄詳細に出している合計の信用倍率とは別の数字です。</li>
              <li>・倍率を出せるのは、制度信用の売り残がある銘柄だけです。貸借銘柄でない銘柄は制度信用では売れないので、倍率がありません。</li>
              <li>・ランクはモメンタム度のランクです（倍率とは別の指標）。</li>
            </ul>
            <p className="note mt-3">
              出どころは JPX「銘柄別信用取引残高」。申込日の次の営業日に公表されるので、株価より1営業日（昼の更新では2営業日）前の残高です。
              <b>倍率の低い・高い銘柄がその後どう動いたかは、このアプリでは検証していません</b>（JPX が毎日公表するようになったのが2026年9月28日で、まだ履歴が無いため）。
            </p>
          </Card>
        </div>
      )}
    </div>
  );
}
