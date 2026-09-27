import { useMemo, useState } from "react";
import { api, paths, useData } from "../data";
import LineChart, { type LineDef } from "../components/LineChart";
import { Card, Delta, ErrorBox, Icon, Loading, RANK_COLOR, RankBadge } from "../components/ui";
import { mdDate, num } from "../format";
import { back } from "../router";
import type { MarketResponse } from "../types";

const SCORE_RANGE: Record<number, [number, number]> = { 1: [0, 100] };
const PCT_RANGE: Record<number, [number, number]> = { 0: [0, 100] };
const MID_BASELINE: Record<number, number> = { 0: 50 };
const SEG_COLOR: Record<string, string> = { プライム: "#3987e5", スタンダード: "#d95926", グロース: "#199e70" };
const f0 = (v: number | null) => (v == null ? "—" : v.toLocaleString("ja-JP", { maximumFractionDigits: 0 }));
const f1 = (v: number | null) => (v == null ? "—" : v.toFixed(1));
const fPct = (v: number | null) => (v == null ? "—" : `${v.toFixed(1)}%`);

export default function Market() {
  const { data, error, loading, reload } = useData<MarketResponse>(paths.market, api.market);
  const [table, setTable] = useState(false);

  const nikkeiLines = useMemo<LineDef[]>(
    () =>
      data?.nikkei
        ? [
            { key: "close", label: "日経平均", color: "#a9c3cf", series: data.nikkei.close_series, pane: 0, format: f0 },
            { key: "score", label: "モメンタム度", color: RANK_COLOR.A, series: data.nikkei.series, pane: 1, rankColored: true, format: f0 },
          ]
        : [],
    [data],
  );
  const breadthLines = useMemo<LineDef[]>(
    () =>
      data
        ? [
            { key: "b", label: "ランクB以上", color: "#3987e5", series: data.breadth.b_plus_series, format: fPct },
            { key: "s", label: "ランクS", color: "#d95926", series: data.breadth.s_share_series, format: fPct },
          ]
        : [],
    [data],
  );
  const segLines = useMemo<LineDef[]>(
    () => (data ? data.segments.map((s) => ({ key: s.name, label: s.name, color: SEG_COLOR[s.name] ?? "#a9c3cf", series: s.series, format: f1 })) : []),
    [data],
  );
  const paneHeights = useMemo(() => [170, 90], []);

  return (
    <div>
      <div className="top-bar">
        <button className="icon-btn" onClick={back} aria-label="戻る"><Icon name="back" /></button>
        <h1>地合い</h1>
        <span />
      </div>
      {loading && !data && <Loading />}
      {error && !data && <ErrorBox message={error} onRetry={reload} />}
      {data && (
        <div className={loading ? "fade-stale" : ""}>
          {data.nikkei && (
            <Card title="日経平均" guide="nikkei" sub="上段=指数、下段=指数そのもののモメンタム度（個別株と同じ計算）">
              <div className="flex items-center gap-3 mb-2">
                <span className="text-[26px] font-extrabold">{num(data.nikkei.score)}</span>
                <RankBadge rank={data.nikkei.rank} large />
                <span className="text-[13px] t-2">5日で <Delta v={data.nikkei.delta5} suffix="" /></span>
              </div>
              <LineChart lines={nikkeiLines} ranges={SCORE_RANGE} height={280} paneHeights={paneHeights} />
            </Card>
          )}

          <Card title="ランクB以上の銘柄の比率" guide="breadth"
            sub={`終値100円以上の ${num(data.breadth.count)} 銘柄のうち、モメンタム度55以上（ランクS・A・B）の割合`}>
            <div className="flex items-baseline gap-2 mb-2">
              <span className="text-[26px] font-extrabold">{num(data.breadth.b_plus, 1)}%</span>
              <span className="text-[13px] t-2">ランクS {num(data.breadth.s_share, 1)}%</span>
            </div>
            <LineChart lines={breadthLines} ranges={PCT_RANGE} height={200} />
            <p className="note mt-2">
              指数が上がっていてもこの比率が下がっていれば、一部の大型株だけの上げで、全体の広がりは弱まっています。
              記録のある日の中では、いまの値は {num(data.breadth.b_plus_percentile)}% の日より高い水準です。
            </p>
            <button className="card-link mt-1" onClick={() => setTable(!table)}>{table ? "表を閉じる" : "直近10日を表で見る"}</button>
            {table && (
              <table className="tbl mt-1">
                <thead><tr><th>日付</th><th>ランクB以上</th><th>ランクS</th></tr></thead>
                <tbody>
                  {data.breadth.b_plus_series.dates.slice(-10).reverse().map((d, i) => {
                    const n = data.breadth.b_plus_series.dates.length;
                    const j = n - 1 - i;
                    return (
                      <tr key={d}>
                        <td>{mdDate(d)}</td>
                        <td>{fPct(data.breadth.b_plus_series.values[j])}</td>
                        <td>{fPct(data.breadth.s_share_series.values[j] ?? null)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </Card>

          <Card title="市場区分ごとの強さ" guide="segments" sub="各市場の全銘柄のモメンタム度の中央値（灰色の線が中立の50）">
            <div className="grid grid-cols-3 gap-2 mb-3">
              {data.segments.map((s) => (
                <div key={s.name} className="tile text-center">
                  <div className="text-[12px] font-semibold" style={{ color: "var(--text-1)" }}>
                    <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: SEG_COLOR[s.name], marginRight: 4 }} />
                    {s.name}
                  </div>
                  <div className="flex items-center justify-center gap-1.5 mt-1">
                    <span className="text-[20px] font-bold">{num(s.median)}</span>
                    <RankBadge rank={s.rank} />
                  </div>
                  <div className="note !text-[10.5px]">5日 <Delta v={s.delta5} suffix="" /> · {num(s.count)}銘柄</div>
                </div>
              ))}
            </div>
            <LineChart lines={segLines} ranges={PCT_RANGE} baselines={MID_BASELINE} height={200} />
          </Card>

          <Card title="TOPIX について">
            <p className="prose !text-[13px]">
              TOPIX の指数値は無料のデータ源（yfinance）から取得できません。ETF で代用すると水準が別物になるため、
              ここでは<b>市場区分ごとの中央値</b>を出しています。時価総額で加重した指数とは違い、小型株も大型株も1銘柄として数えます。
            </p>
          </Card>
        </div>
      )}
    </div>
  );
}
