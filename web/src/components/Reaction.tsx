import { useState, type ReactNode } from "react";
import { api, paths, useData } from "../data";
import { num, slashDate } from "../format";
import type { RxGroup, RxScope, RxSummary, Rx } from "../types";
import { Delta, ErrorBox, Loading } from "./ui";

/**
 * 開示への市場の反応（pipeline/momentum/reaction.py）。「良い・悪い」の判定や予測ではなく、
 * 開示のあとに株価と売買代金がどう動いたかという事実だけを並べる。
 */

export const TIMING: Record<Rx["t"], string> = { pre: "寄り付き前", mid: "場中の開示", post: "引け後" };

/** 5日の見出し（5日に満たないうちは「3日」など） */
export function rx5Label(rx: Rx): string {
  return rx.n5 >= 5 ? "5日" : `${rx.n5}日`;
}

/** 開示の行に付ける反応の1行（市場比・5日・窓・寄り→引け・売買代金）と、切り分けの注記 */
export function RxLine({ rx, compact = false }: { rx: Rx | null | undefined; compact?: boolean }) {
  if (!rx) return null;
  const notes = [
    rx.t === "mid" ? "場中の開示（開示の前の値動きも含む）" : null,
    rx.partial === "am" ? "前場までの途中経過" : rx.partial === "intraday" ? "取引時間中の途中経過" : null,
    rx.with?.length ? `同じ日に${rx.with.join("・")}の開示も` : null,
    rx.theme ? `${rx.theme}した日` : null,
    rx.after ? `この${rx.n5}日の間にほかの開示も（${rx.after}日）` : null,
  ].filter(Boolean) as string[];
  return (
    <div className="rx">
      <div className="rx-nums num">
        {!compact && <span className={`rx-t rx-t-${rx.t}`}>{TIMING[rx.t]}</span>}
        <span>市場比 <Delta v={rx.r} /></span>
        {rx.n5 > 1 && <span>{rx5Label(rx)} <Delta v={rx.r5} /></span>}
        <span>窓 <Delta v={rx.gap} /></span>
        <span>寄→引 <Delta v={rx.oc} /></span>
        <span>代金 {rx.tr == null ? "—" : `${num(rx.tr, 1)}倍`}</span>
      </div>
      {notes.length > 0 && <div className="rx-notes">{notes.map((n) => <span key={n}>※{n}</span>)}</div>}
    </div>
  );
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rx-stat">
      <div className="rx-stat-l">{label}</div>
      <div className="rx-stat-v num">{children}</div>
    </div>
  );
}

function Stats({ s }: { s: RxSummary }) {
  return (
    <div className="rx-stats">
      <Stat label="市場比の中央値"><Delta v={s.r} digits={2} /></Stat>
      <Stat label="上がった割合">{s.up == null ? "—" : `${num(s.up)}%`}</Stat>
      <Stat label="動きの大きさ">{s.abs == null ? "—" : `${num(s.abs, 2)}%`}</Stat>
      <Stat label={`5日の中央値（${num(s.n5)}件）`}><Delta v={s.r5} digits={2} /></Stat>
      <Stat label="売買代金の倍率">{s.tr == null ? "—" : `${num(s.tr, 2)}倍`}</Stat>
      <Stat label="窓の中央値"><Delta v={s.gap} digits={2} /></Stat>
    </div>
  );
}

function GroupRow({ g, minN }: { g: RxGroup; minN: number }) {
  const [open, setOpen] = useState(false);
  const few = (n: number) => n < minN;
  return (
    <div className="rx-group">
      <button className="rx-group-head" onClick={() => g.subs.length && setOpen(!open)} aria-expanded={open}>
        <b>{g.category}</b>
        {few(g.n) && <span className="why why-unknown">参考</span>}
        <span className="t-3 text-[12px] num">{num(g.n)}件</span>
        {g.subs.length > 0 && <span className="ml-auto t-3 text-[12px]">{open ? "閉じる" : `内訳 ${g.subs.length}`}</span>}
      </button>
      <Stats s={g} />
      {open && g.subs.map((s) => (
        <div key={s.sub} className="rx-sub">
          <div className="flex items-center gap-1.5 text-[12.5px]">
            <span>{s.sub}</span>
            {few(s.n) && <span className="why why-unknown">参考</span>}
            <span className="t-3 num">{num(s.n)}件</span>
          </div>
          <Stats s={s} />
        </div>
      ))}
    </div>
  );
}

/** 種類ごとの傾向（適時開示の画面のタブ） */
export function RxTrends({ liquidOnly }: { liquidOnly: boolean }) {
  const { data, error, loading, reload } = useData(paths.reactions, api.reactions);
  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorBox message={error} onRetry={reload} />;
  const st = data?.stats;
  const scope: RxScope | undefined = st ? (liquidOnly ? st.scopes.liquid : st.scopes.all) : undefined;
  if (!st || !scope) return <p className="note">まだ傾向を出せるデータがありません（次の更新で作られます）。</p>;
  return (
    <div>
      <p className="note">
        {st.first && st.last ? `${slashDate(st.first)}〜${slashDate(st.last)} に効いた開示` : ""}
        {` ${num(scope.total)}件のうち、条件に合う ${num(scope.used)}件で数えています。`}
        {liquidOnly ? "流動性のある銘柄だけ。" : "すべての銘柄。"}
      </p>
      <div className="mt-2">
        {scope.groups.map((g) => <GroupRow key={g.category} g={g} minN={st.min_n} />)}
      </div>
      <ul className="space-y-1.5 text-[12.5px] leading-snug t-2 mt-3">
        <li>・<b>数えた開示</b>: 寄り付き前か引け後に出て、同じ日にほかの分類の開示が無く、その銘柄のテーマもそろって動いていないもの。
          除いた件数は、場中の開示 {num(scope.excluded.mid)}件・ほかの開示と重なった {num(scope.excluded.with)}件・テーマがそろって動いた {num(scope.excluded.theme)}件（重なりあり）。
          同じ銘柄・同じ日・同じ分類の開示（決算短信と説明資料など）は1件に数えます。</li>
        <li>・<b>市場比</b>は、効いた日の騰落率から市場全体（終値100円以上の全銘柄）の中央値を引いたもの。<b>上がった割合</b>は市場比がプラスだった割合、
          <b>動きの大きさ</b>は市場比の絶対値の中央値（上げ下げを問わず、どれだけ動いたか）。<b>5日</b>は効いた日を含む{st.days}取引日で、5日たった開示だけで数えます。</li>
        <li>・件数が {st.min_n}件未満の分類は「参考」です。分類は表題の言葉から機械的に付けたもので、誤りもあります。
          業績修正・配当などの「内訳」も表題の言葉だけで分けています（表題に上方・下方が書かれていない修正は「業績予想の修正」にまとまり、上げ下げの両方を含みます）。</li>
        <li>・<b>過去の反応の集計で、良い・悪いの判定や、これからの値動きの予想ではありません。この傾向とその後の値動きの関係は検証していません。</b></li>
      </ul>
    </div>
  );
}

