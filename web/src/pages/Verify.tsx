import { useMemo, useState } from "react";
import { api, paths, useData } from "../data";
import Bars from "../components/Bars";
import LineChart, { type LineDef } from "../components/LineChart";
import { Card, Delta, ErrorBox, Icon, Loading, RankBadge } from "../components/ui";
import { num, pct, slashDate } from "../format";
import { VERIFY_LABEL } from "../metrics";
import { back } from "../router";
import type { VerifyResponse } from "../types";

const ZERO: Record<number, number> = { 0: 0 };
const f3 = (v: number | null) => (v == null ? "—" : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(3));
const ROLL_COLOR: Record<string, string> = { score: "#3987e5", sr: "#d95926", stab: "#199e70" };

/** モメンタム度の結果を、その時点のデータから文章にする（固定の文面だとデータが変わると嘘になる） */
function ScoreStory({ data, significant }: { data: VerifyResponse; significant: number }) {
  const h = data.ic.find((r) => r.key === "score")?.horizons["20"];
  const roll = [...(data.rolling_ic.series.score ?? [])].reverse().find((x) => x != null) ?? null;
  if (!h) return null;
  const flip = h.first_half != null && h.second_half != null && Math.sign(h.first_half) !== Math.sign(h.second_half);
  return (
    <p className="prose mt-2">
      モメンタム度と20日後の市場比の相関は、前半（〜{slashDate(data.half_date)}）が <b>{ic(h.first_half)}</b>、後半が <b>{ic(h.second_half)}</b>。
      {flip ? "期間によって向きが逆になっています。" : "向きは同じですが、どちらも小さな値です。"}
      {roll != null && (
        <>
          直近60日の平均は <b>{ic(roll)}</b> で、いまは
          {roll < 0 ? "強い銘柄ほどその後に市場平均に負けやすい" : "強い銘柄ほどその後も市場平均を上回りやすい"}局面です。
        </>
      )}
      {significant === 0 && <> ランキングは「いま強い銘柄」の一覧であって、「これから上がる銘柄」の予想ではありません。</>}
    </p>
  );
}

function ic(v: number | null | undefined) {
  if (v == null) return "—";
  return (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(3);
}

export default function Verify() {
  const { data, error, loading, reload } = useData<VerifyResponse>(paths.verify, api.verify);
  const [decTable, setDecTable] = useState(false);

  const rolling = useMemo<LineDef[]>(
    () =>
      data
        ? (["score", "sr", "stab"] as const)
            .filter((k) => data.rolling_ic.series[k])
            .map((k) => ({
              key: k,
              label: VERIFY_LABEL[k],
              color: ROLL_COLOR[k],
              series: { dates: data.rolling_ic.dates, values: data.rolling_ic.series[k] },
              format: f3,
            }))
        : [],
    [data],
  );

  const significant = data
    ? data.ic.filter((r) => Object.values(r.horizons).some((h) => h && h.t != null && Math.abs(h.t) >= 2)).length
    : 0;

  return (
    <div>
      <div className="top-bar">
        <button className="icon-btn" onClick={back} aria-label="戻る"><Icon name="back" /></button>
        <h1>検証 — この数字は当たるのか</h1>
        <span />
      </div>
      {loading && !data && <Loading slow />}
      {error && !data && <ErrorBox message={error} onRetry={reload} />}
      {data && (
        <div className={loading ? "fade-stale" : ""}>
          <Card title="結論" guide="verify-summary">
            <p className="prose">
              {slashDate(data.first_date)}〜{slashDate(data.last_date)} の日足で、各指標が高い銘柄ほど<b>その後に市場平均を上回ったか</b>を測りました
              {data.ic_first_date && (
                <>（指標が出そろい、20営業日後の結果も出ている {slashDate(data.ic_first_date)}〜{slashDate(data.ic_last_date)} の {num(data.ic_days)} 営業日）</>
              )}。
              {significant === 0 ? (
                <> {data.ic.length}つの指標とも、統計的に有意な関係は<b>見つかっていません</b>。</>
              ) : (
                <> {data.ic.length}つの指標のうち {significant} つで、一部の期間に有意な関係がありました。</>
              )}
            </p>
            <ScoreStory data={data} significant={significant} />
            <ul className="note mt-3 space-y-1 list-disc pl-4">
              <li>リターンは「翌営業日の始値 → N営業日後の終値」。当日の終値で判定するので、同じ日には入れない前提</li>
              <li>「市場比」は同じ期間の全銘柄の単純平均との差。対象は売買代金20日平均5,000万円以上・終値100円以上</li>
              <li>t値は日ごとの平均を1標本とし、保有期間の重なりの分だけ標本数を割り引いたもの。|t|≥2 を「有意」とする</li>
            </ul>
          </Card>

          <Card title="IC（順位の相関）" guide="verify-ic" sub="その日の全銘柄で「指標の順位」と「その後の市場比の順位」の相関。0なら無関係、+0.05でも株式では強い部類">
            <table className="tbl">
              <thead><tr><th>指標</th><th>5日後</th><th>20日後</th><th>60日後</th></tr></thead>
              <tbody>
                {data.ic.map((r) => (
                  <tr key={r.key}>
                    <td>{VERIFY_LABEL[r.key] ?? r.key}</td>
                    {(["5", "20", "60"] as const).map((h) => {
                      const x = r.horizons[h];
                      const sig = x?.t != null && Math.abs(x.t) >= 2;
                      return (
                        <td key={h} className={sig ? "t-1 font-bold" : "t-2"}>
                          {ic(x?.ic)}<span className="t-3 text-[10.5px]"> ({num(x?.t, 1)})</span>{sig ? "＊" : ""}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="note mt-1">（）内は t値。＊は |t|≥2。</div>
            <div className="mt-3 text-[13px] font-bold">前半と後半（20日後）</div>
            <table className="tbl mt-1">
              <thead><tr><th>指標</th><th>前半</th><th>後半</th></tr></thead>
              <tbody>
                {data.ic.map((r) => (
                  <tr key={r.key}>
                    <td>{VERIFY_LABEL[r.key] ?? r.key}</td>
                    <td>{ic(r.horizons["20"]?.first_half)}</td>
                    <td>{ic(r.horizons["20"]?.second_half)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          <Card title="局面の変化" guide="verify-rolling" sub="20日後のICの60日移動平均。0より上なら「その指標が高い銘柄ほど、その後に市場平均を上回った」時期">
            <LineChart lines={rolling} baselines={ZERO} height={210} format={f3} />
          </Card>

          <Card title="ランク別の実績" guide="verify-ranks" sub="モメンタム度のランクごとの、その後の市場比（日ごとの平均をさらに平均）">
            <table className="tbl">
              <thead><tr><th>ランク</th><th>比率</th><th>5日</th><th>20日</th><th>60日</th><th>勝率20日</th></tr></thead>
              <tbody>
                {data.ranks.map((r) => (
                  <tr key={r.rank}>
                    <td><RankBadge rank={r.rank} /></td>
                    <td className="t-2">{num(r.share, 0)}%</td>
                    <td><Delta v={r.horizons["5"]?.excess_mean} digits={2} /></td>
                    <td><Delta v={r.horizons["20"]?.excess_mean} digits={2} /></td>
                    <td><Delta v={r.horizons["60"]?.excess_mean} digits={2} /></td>
                    <td>{num(r.horizons["20"]?.win_rate, 0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-3 text-[13px] font-bold">20日後の市場比（前半 → 後半）</div>
            <table className="tbl mt-1">
              <thead><tr><th>ランク</th><th>前半</th><th>後半</th></tr></thead>
              <tbody>
                {data.ranks.map((r) => (
                  <tr key={r.rank}>
                    <td><RankBadge rank={r.rank} /></td>
                    <td><Delta v={r.horizons["20"]?.first_half} digits={2} /></td>
                    <td><Delta v={r.horizons["20"]?.second_half} digits={2} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="note mt-2">勝率が5割を切るのは、値上がりの分布が右に歪んでいる（少数の大化けが平均を押し上げる）ため。平均がプラスでも「多くの銘柄は市場平均に負けている」ことがある。</p>
          </Card>

          <Card title="十分位（20日後の市場比）" guide="verify-deciles" sub="毎日、モメンタム度で10グループに分けたときの成績（1=最も弱い、10=最も強い）">
            <div className="text-[12px] t-2 mt-1">前半（〜{slashDate(data.half_date)}）</div>
            <Bars bars={data.deciles.map((d) => ({ label: String(d.decile), value: d.first_half }))} />
            <div className="text-[12px] t-2 mt-2">後半</div>
            <Bars bars={data.deciles.map((d) => ({ label: String(d.decile), value: d.second_half }))} />
            <button className="card-link mt-1" onClick={() => setDecTable(!decTable)}>{decTable ? "表を閉じる" : "表で見る"}</button>
            {decTable && (
              <table className="tbl mt-1">
                <thead><tr><th>十分位</th><th>全期間</th><th>前半</th><th>後半</th></tr></thead>
                <tbody>
                  {data.deciles.map((d) => (
                    <tr key={d.decile}><td>{d.decile}</td><td>{pct(d.excess_mean, 2)}</td><td>{pct(d.first_half, 2)}</td><td>{pct(d.second_half, 2)}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Card title="シグナルの実績" guide="verify-signals" sub="流動性のある銘柄で発動した分。市場比は同じ期間の全銘柄平均との差">
            <table className="tbl">
              <thead><tr><th>シグナル</th><th>件数</th><th>5日</th><th>20日</th><th>勝率20日</th><th>t20日</th></tr></thead>
              <tbody>
                {data.signal_defs.map((s) => {
                  const st = data.signal_stats[s.key];
                  const h5 = st?.horizons["5"];
                  const h20 = st?.horizons["20"];
                  return (
                    <tr key={s.key}>
                      <td className={s.tone === "warn" ? "t-warn" : ""}>{s.label}</td>
                      <td>{num(st?.events)}</td>
                      <td><Delta v={h5?.excess_mean} digits={2} /></td>
                      <td><Delta v={h20?.excess_mean} digits={2} /></td>
                      <td>{num(h20?.win_rate, 0)}%</td>
                      <td className="t-2">{num(h20?.t, 2)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>

          <Card title="株価の段差の補正" sub="値幅制限を超える段差を、株式分割（または取得の不具合）とみなして過去側を補正した記録">
            {data.adjustments.length === 0 && <p className="note">ありません。</p>}
            <table className="tbl">
              <tbody>
                {data.adjustments.map((a) => (
                  <tr key={`${a.date}-${a.code}`}>
                    <td>{slashDate(a.date)}</td>
                    <td>{a.code}</td>
                    <td className="t-2">{num(a.prev_close)} → {num(a.close)}</td>
                    <td className="t-2">{a.kind === "split" ? `分割 1:${num(1 / a.ratio, 1)}` : "段差"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          <Card title="この検証の限界">
            <ul className="note space-y-1.5 list-disc pl-4 !text-[12px]">
              <li>期間が約2年と短く、AI・半導体相場や銀行株の上昇など特定の局面の影響を強く受けている</li>
              <li>いま上場している銘柄だけで計算しているので、期間中に上場廃止になった銘柄が抜けている（生存者バイアス）</li>
              <li>売買手数料・スプレッド・約定できないストップ高（安）は考慮していない</li>
              <li>多くの指標と期間を同時に見ているので、偶然 |t|≥2 になるものが出てもおかしくない</li>
              <li>数字は毎日の日足の取り込み後に計算し直され、期間が延びるにつれて変わる</li>
            </ul>
          </Card>
        </div>
      )}
    </div>
  );
}
