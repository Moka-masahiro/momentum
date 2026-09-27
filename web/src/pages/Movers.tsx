import { useState } from "react";
import { api, paths, useData } from "../data";
import { Card, Delta, ErrorBox, Icon, Loading, Seg, WHY_LABEL, WhyNote } from "../components/ui";
import { num, slashDate } from "../format";
import { back, go } from "../router";
import type { MoversResponse, Why } from "../types";

const ORDER: Why[] = ["news", "supply", "unknown", "market"];

/**
 * きょう目立って動いた銘柄と、その理由の手がかり（pipeline/momentum/reasons.py）。
 * 並びは業種平均との差の大きい順。地合い（業種ごと動いただけ）は自然に後ろに来る。
 */
export default function Movers() {
  const { data, error, loading, reload } = useData<MoversResponse>(paths.movers, api.movers);
  const [why, setWhy] = useState<"" | Why>("");
  const [liquidOnly, setLiquidOnly] = useState(true);
  const [limit, setLimit] = useState(50);

  const base = (data?.items ?? []).filter((r) => !liquidOnly || r.liquid);
  const count = (k: Why) => base.filter((r) => r.why === k).length;
  const items = why ? base.filter((r) => r.why === why) : base;
  const st = data?.status;

  return (
    <div>
      <div className="top-bar">
        <button className="icon-btn" onClick={back} aria-label="戻る"><Icon name="back" /></button>
        <h1>値動きの理由</h1>
        <span />
      </div>
      {loading && !data && <Loading />}
      {error && !data && <ErrorBox message={error} onRetry={reload} />}
      {data && (
        <div className={`stack ${loading ? "fade-stale" : ""}`}>
          <div className="card !p-3" data-guide="movers-filter">
            <Seg value={why} onChange={(v) => { setWhy(v); setLimit(50); }}
              options={[{ value: "" as const, label: `すべて ${base.length}` },
                ...ORDER.map((k) => ({ value: k, label: `${WHY_LABEL[k]} ${count(k)}` }))]} />
            <div className="flex items-center justify-between mt-3">
              <span className="note">{slashDate(data.as_of)} の値動き</span>
              <label className="flex items-center gap-2 text-[13px] t-2">
                <input type="checkbox" checked={liquidOnly} onChange={(e) => setLiquidOnly(e.target.checked)} />
                流動性のある銘柄だけ
              </label>
            </div>
            {st && !st.disclosures.ok && (
              <p className="note t-warn mt-2">開示を取得できなかったため、ニュースかどうかの判定をしていません。</p>
            )}
            {st === null && <p className="note t-warn mt-2">この日は値動きの理由を作れませんでした。</p>}
          </div>

          <Card>
            <div className="list-head" style={{ gridTemplateColumns: "1fr 58px 44px" }}>
              <span>銘柄名・理由</span><span className="text-right">前日比</span><span className="text-right">出来高</span>
            </div>
            {items.slice(0, limit).map((r) => (
              <button key={r.code} className="list-row" style={{ gridTemplateColumns: "1fr 58px 44px" }} onClick={() => go(`stock/${r.code}`)}>
                <span className="list-name">
                  <b>{r.name}</b>
                  <small className="list-sub"><span>{r.code}</span><WhyNote row={r} /></small>
                </span>
                <span className="text-right text-[12.5px] font-semibold"><Delta v={r.chg1} /></span>
                <span className="text-right text-[11.5px] t-2 num">{r.vr != null ? `${num(r.vr, 1)}倍` : "—"}</span>
              </button>
            ))}
            {items.length === 0 && <p className="text-[13px] t-3 py-2">該当する銘柄はありません。</p>}
            {items.length > limit && (
              <button className="btn-ghost w-full mt-2 text-[13px]" onClick={() => setLimit(limit + 50)}>さらに50件</button>
            )}
          </Card>

          <Card title="判定のしかた" guide="movers-rules">
            <p className="prose !text-[13px]">
              業種平均との差が<b>普段の3倍以上</b>、または出来高が<b>20日平均の3倍以上</b>だった銘柄に、上から順に当てはめます。
            </p>
            <ul className="mt-2 space-y-2 text-[13px] leading-snug">
              <li><WhyNote row={{ why: "market" }} /> 業種全体が同じ向きに大きく動き、この銘柄だけの動きは目立たない。
                または開示は無いが、同じ業種の他の銘柄もそろって同じ向きに大きく動いた（テーマ・連れ高）</li>
              <li><WhyNote row={{ why: "news" }} /> 前の取引日の引け（15:30）から当日の引けまでに、会社の適時開示がある</li>
              <li><WhyNote row={{ why: "supply" }} /> 増資・自社株買いなど株の需給に関わる開示がある。または開示は無いが、出来高が急増したのに値動きは小さい（指数の入れ替え・大口の売買）、信用取引の規制・日々公表の対象、機関の空売りが値動きと同じ向きに大きく増減、権利落ち日の下げ</li>
              <li><WhyNote row={{ why: "unknown" }} /> どれにも当たらない</li>
            </ul>
            <p className="note mt-3">
              ニュースは会社の適時開示だけで、新聞報道・アナリストの格付け・テーマ買いは拾えません（無料で自動取得してよい入手先が無いため）。
              会社が「一部報道について」を出したときだけ、報道が理由だとわかります。需給の手がかりは状況証拠で、原因の証明ではありません。
              開示を取得できなかった日を含むときは判定しません。
            </p>
          </Card>
        </div>
      )}
    </div>
  );
}
