import { useState } from "react";
import { api, paths, useData } from "../data";
import { Card, Delta, DiscChip, ErrorBox, Icon, Loading, RankBadge, RowMarks, Disclaimer, SessionBadge, SessionNote, THEME_WINDOW, ThemeBadges, ThemeChip, WHY_LABEL, WhyNote } from "../components/ui";
import Spark from "../components/Spark";
import { mdDate, mdTime, num, pct, slashDate, yen } from "../format";
import { flag, go, setFlag } from "../router";
import type { Home as HomeData, StockRow, Why } from "../types";

export default function Home({ onGuide }: { onGuide: () => void }) {
  const { data, error, loading, reload } = useData<HomeData>(paths.home, api.home);
  const [welcome, setWelcome] = useState(() => !flag("m_welcome_done"));

  return (
    <div>
      <header className="flex items-center justify-between py-2 mb-2">
        <div className="flex items-center gap-2.5">
          <Logo />
          <div>
            <div className="text-[21px] font-extrabold leading-tight tracking-wide">モメンタム</div>
            <div className="note !text-[11px]">自分用・日本株</div>
          </div>
        </div>
        <div className="text-right">
          <div className="note !text-[11px]">データ日付</div>
          <div className="flex items-center justify-end gap-1.5">
            <SessionBadge session={data?.session} />
            <span className="text-[17px] font-bold num">{data ? slashDate(data.as_of) : "—"}</span>
          </div>
        </div>
      </header>
      <SessionNote session={data?.session} className="mb-2 px-1" />
      {data && <StaleNotice data={data} />}

      {welcome && (
        <div className="card mb-3" style={{ borderColor: "rgba(232,199,111,0.5)" }}>
          <div className="flex items-start gap-3">
            <span className="t-gold mt-0.5"><Icon name="guide" size={22} /></span>
            <div className="flex-1">
              <div className="font-bold">はじめに</div>
              <p className="prose !text-[13px] mt-1">
                全銘柄の日足から、いまの勢い（モメンタム）と需給を機械的に計算して並べるアプリです。
                画面の見方は右下のガイドからいつでも確認できます。
              </p>
              <div className="flex gap-2 mt-3">
                <button className="btn-primary" onClick={() => { setFlag("m_welcome_done"); setWelcome(false); onGuide(); }}>
                  使い方ガイドを見る
                </button>
                <button className="btn-ghost" onClick={() => { setFlag("m_welcome_done"); setWelcome(false); }}>
                  閉じる
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {loading && !data && <Loading label="全銘柄の指標を読み込み中…" slow />}
      {error && !data && <ErrorBox message={error} onRetry={reload} />}
      {data && (
        <div className={loading ? "fade-stale" : ""}>
          {/* 登録があれば、自分の銘柄を最初に見せる（無いうちは下に案内だけ出す） */}
          {data.watchlist.length > 0 && <WatchCard rows={data.watchlist} />}
          <MarketCard data={data} />
          <ThemesCard themes={data.themes} />
          <MoversCard data={data} />
          <UpcomingCard data={data} />
          <RankingCard rows={data.ranking} universe={data.universe} />
          <SignalCard data={data} />
          <MarginCard m={data.margin} />
          {data.watchlist.length === 0 && <WatchCard rows={data.watchlist} />}
          <Card icon="flask" title="この数字は当たる？" link="検証を見る" onLink={() => go("verify")} guide="verify-home">
            <p className="prose !text-[13px]">
              モメンタム度やシグナルが、その後に市場平均を上回ったかを毎日検証しています。
              <VerifyLine v={data.verify_summary} />
            </p>
          </Card>
          <button className="card w-full flex items-center justify-between !py-3 text-left" onClick={() => go("settings")}>
            <span className="flex items-center gap-2 t-2 font-semibold"><Icon name="gear" size={18} />設定・データの状態</span>
            <Icon name="chev" size={18} />
          </button>
          <Disclaimer />
        </div>
      )}
    </div>
  );
}

/** 予定の時刻を1時間過ぎても新しいデータが届いていなければ知らせる（更新の失敗に気づけるように） */
function StaleNotice({ data }: { data: HomeData }) {
  if (!data.next_update) return null;
  const due = Date.parse(`${data.next_update.replace(" ", "T")}:00+09:00`);
  if (!(Date.now() > due + 60 * 60 * 1000)) return null;
  return (
    <p className="note t-warn mb-2 px-1" role="status">
      予定していた更新（{mdTime(data.next_update)} ごろ）がまだ届いていません。表示しているのは {slashDate(data.as_of)} のデータです。
      電波のある場所で開き直しても変わらなければ、更新が失敗している可能性があります。
    </p>
  );
}

function VerifyLine({ v }: { v: HomeData["verify_summary"] | undefined }) {
  if (!v) return null; // 古いデータには要約が無い
  const period = v.from ? `（${slashDate(v.from)}〜${slashDate(v.to)}、${num(v.days)}営業日）` : "";
  if (v.metrics_significant === 0 && v.signals_significant === 0) {
    return <b>いまのところ、{v.metrics}つの指標も{v.signals}種類のシグナルも、統計的に有意な差はありません{period}。</b>;
  }
  return (
    <b>
      {v.metrics}つの指標のうち{v.metrics_significant}つ、{v.signals}種類のシグナルのうち{v.signals_significant}種類に、
      一部の期間で有意な差がありました{period}。
    </b>
  );
}

function Logo() {
  return (
    <svg width="38" height="38" viewBox="0 0 64 64" aria-hidden="true">
      <defs>
        <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#1f6fb8" />
          <stop offset="1" stopColor="#123a66" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="15" fill="url(#lg)" stroke="rgba(120,200,230,0.5)" />
      <path d="M13 45l13-13 8 7 16-19" stroke="#8ef0c8" strokeWidth="6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M41 19h10v10" stroke="#8ef0c8" strokeWidth="6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Stat({ label, sub, score, rank }: { label: string; sub?: string; score: number | null | undefined; rank: StockRow["rank"] }) {
  return (
    <div className="text-center">
      <div className="text-[13px] font-semibold t-1">{label}</div>
      <div className="note !text-[10px] -mt-0.5 mb-1">{sub ?? " "}</div>
      <div className="inline-flex items-center gap-1.5">
        <span className="text-[22px] font-bold">{num(score)}</span>
        <RankBadge rank={rank} />
      </div>
    </div>
  );
}

function MarketCard({ data }: { data: HomeData }) {
  const m = data.market;
  const seg = (name: string) => m.segments.find((s) => s.name === name);
  const prime = seg("プライム");
  const growth = seg("グロース");
  return (
    <Card icon="bars" title="地合い" link="詳細を見る" onLink={() => go("market")} guide="market">
      <div className="grid grid-cols-3 gap-2">
        <Stat label="日経平均" sub="指数そのもの" score={m.nikkei?.score} rank={m.nikkei?.rank ?? null} />
        <Stat label="プライム" sub="全銘柄の中央値" score={prime?.median} rank={prime?.rank ?? null} />
        <Stat label="グロース" sub="全銘柄の中央値" score={growth?.median} rank={growth?.rank ?? null} />
      </div>
      <div className="tile mt-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-[12px] t-2">ランクB以上の銘柄</div>
          <div className="text-[20px] font-bold">{num(m.breadth.b_plus, 1)}<span className="text-[13px] t-2 ml-0.5">%</span></div>
          <div className="note !text-[11px]">
            {m.breadth.b_plus_percentile != null ? `記録のある日の ${num(m.breadth.b_plus_percentile)}% より広い` : ""}
          </div>
        </div>
        <div className="text-right">
          <Spark series={m.breadth_spark} domain={[0, 100]} />
          <div className="note !text-[10px]">直近60日</div>
        </div>
      </div>
      {m.nikkei && (
        <div className="note mt-2">
          日経平均 {num(m.nikkei.close)} <Delta v={m.nikkei.change_pct} digits={2} />（{slashDate(m.nikkei.date)}）
        </div>
      )}
    </Card>
  );
}

/** そろって上げているテーマ。売買代金も膨らんでいるテーマがあれば、最初の1文で名前を挙げる */
function ThemesCard({ themes }: { themes: HomeData["themes"] }) {
  if (themes === undefined) return null; // テーマの無い古いデータ
  const flow = (themes ?? []).filter((t) => t.flow);
  return (
    <Card icon="tag" title="上げているテーマ" link="一覧を見る" onLink={() => go("themes")} guide="themes-home"
      sub="そろって市場より上げているテーマ。売買代金も大きく膨らんでいれば「資金集中？」">
      {themes === null ? (
        <p className="note">この日はテーマを作れませんでした。</p>
      ) : themes.length === 0 ? (
        <p className="note">いま、そろって上げているテーマはありません。</p>
      ) : (
        <>
          {flow.length > 0 && (
            <p className="text-[13.5px] font-semibold leading-snug mb-1">
              {flow.map((t) => `「${t.name}」`).join("")}に資金が集まっているかもしれません。
            </p>
          )}
          {themes.slice(0, 4).map((t) => {
            const w = THEME_WINDOW[t.state];
            return (
              <button key={t.name} className="list-row" style={{ gridTemplateColumns: "1fr auto" }} onClick={() => go(`themes/${encodeURIComponent(t.name)}`)}>
                <span className="list-name">
                  <b>{t.name}</b>
                  <small className="list-sub wrap">
                    <ThemeBadges state={t.state} flow={t.flow} />
                    <span>{t.n}銘柄の{num(t.up)}%が市場を上回る · 売買代金 {num(t.tr, t.tr != null && t.tr < 10 ? 1 : 0)}倍</span>
                  </small>
                  <span className="list-title">{t.lead.filter(Boolean).join("、")} ほか</span>
                </span>
                <span className="text-right leading-tight">
                  <span className="block text-[15px] font-bold"><Delta v={t.rel[w]} /></span>
                  <span className="block text-[10.5px] t-3">{w}日・市場比</span>
                </span>
              </button>
            );
          })}
          <p className="note mt-2">
            テーマと銘柄の対応は手作りの表で、網羅ではありません。数字は流動性のある銘柄の中央値で、売買代金は普段（前250営業日の中央値）の何倍か。
          </p>
        </>
      )}
    </Card>
  );
}

const MOVER_ORDER: Why[] = ["news", "supply", "unknown", "market"];

function MoversCard({ data }: { data: HomeData }) {
  const st = data.reasons;
  if (st === undefined) return null; // 値動きの理由の無い古いデータ
  const rows = data.movers;
  const top = rows.filter((r) => r.why !== "market").slice(0, 5);
  const am = data.session === "am";
  return (
    <Card icon="pulse" title={am ? "前場で目立って動いた銘柄" : "きょう目立って動いた銘柄"} link="一覧を見る" onLink={() => go("movers")} guide="movers"
      sub={am
        ? "業種平均との差が普段の3倍以上、または前場だけで出来高が1日平均の1.5倍以上だった銘柄（流動性あり）と、その理由の手がかり"
        : "業種平均との差か出来高が、普段の3倍以上だった銘柄（流動性あり）と、その理由の手がかり"}>
      {st === null ? (
        <p className="note">この日は値動きの理由を作れませんでした（材料の取得か計算に失敗）。</p>
      ) : (
        <>
          <div className="flex flex-wrap gap-1.5">
            {MOVER_ORDER.map((k) => (
              <button key={k} className={`why why-${k} !text-[12px] !py-1.5 !px-2`} onClick={() => go("movers")}>
                {WHY_LABEL[k]} {rows.filter((r) => r.why === k).length}
              </button>
            ))}
          </div>
          {!st.disclosures.ok && (
            <p className="note t-warn mt-2">開示を取得できなかったため、ニュースかどうかの判定をしていません。</p>
          )}
          <div className="mt-2">
            {top.map((r) => (
              <button key={r.code} className="list-row" style={{ gridTemplateColumns: "1fr auto" }} onClick={() => go(`stock/${r.code}`)}>
                <span className="list-name">
                  <b>{r.name}</b>
                  <small className="list-sub"><ThemeChip row={r} /><WhyNote row={r} /></small>
                </span>
                <span className="text-right text-[13px] font-semibold"><Delta v={r.chg1} /></span>
              </button>
            ))}
            {top.length === 0 && <p className="note mt-1">業種の動きと違う目立った値動きはありませんでした。</p>}
          </div>
          <p className="note mt-2">ニュースは会社の適時開示だけで、新聞報道は含みません。材料不明は、開示も需給の手がかりも無かったものです。</p>
        </>
      )}
    </Card>
  );
}

function UpcomingCard({ data }: { data: HomeData }) {
  const rows = data.upcoming;
  if (rows === undefined) return null; // これからの材料の無い古いデータ
  const am = data.session === "am";
  const liquid = rows.filter((r) => r.liquid);
  const counts = new Map<string, number>();
  for (const r of liquid) counts.set(r.disc!, (counts.get(r.disc!) ?? 0) + 1);
  const fresh = liquid.filter((r) => r.disc_new).length;
  const st = data.reasons?.disclosures;
  const ok = st?.ok;
  return (
    <Card icon="doc" title={am ? "後場の材料" : "次の取引日の材料"} link="一覧を見る" onLink={() => go("disclosures")} guide="disclosures-home"
      sub={`${am ? "前場の引け（11:30）" : "大引け（15:30）"}より後に出た会社の開示（定例を除く）。まだ株価には反映されていません`}>
      {ok === false && <p className="note t-warn mb-2">開示を取得できなかった日があります。</p>}
      <div className="flex flex-wrap gap-1.5">
        {fresh > 0 && (
          <button className="why why-new !text-[12px] !py-1.5 !px-2" onClick={() => go("disclosures/new")}>新着 {fresh}</button>
        )}
        {[...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6).map(([c, n]) => (
          <button key={c} className="why why-unknown !text-[12px] !py-1.5 !px-2" onClick={() => go("disclosures")}>{c} {n}</button>
        ))}
      </div>
      <div className="mt-2">
        {rows.slice(0, 5).map((r) => (
          <button key={r.code} className="list-row" style={{ gridTemplateColumns: "1fr 40px" }} onClick={() => go(`stock/${r.code}`)}>
            <span className="list-name">
              <b>{r.name}</b>
              <small className="list-sub">
                {r.disc_new ? (
                  <><span className="why why-new">新着</span><DiscChip category={r.disc_new} /><span className="why-text">{r.disc_new_text}</span></>
                ) : (
                  <><DiscChip category={r.disc} /><span className="why-text">{r.disc_text}</span></>
                )}
              </small>
            </span>
            <span className="text-center"><RankBadge rank={r.rank} /></span>
          </button>
        ))}
        {rows.length === 0 && <p className="note mt-1">{am ? "前場の引けより後" : "引け後"}の開示は、まだありません。</p>}
      </div>
      <p className="note mt-2">
        {st?.fetched ? `開示は ${mdTime(st.fetched)} に取得。` : ""}
        {rows.length > 0 ? `流動性のある ${num(liquid.length)} 銘柄（全体では ${num(rows.length)} 銘柄）。ウォッチリストの銘柄を先に、次に${st?.since ? "新着、" : ""}売買代金の大きい順。` : ""}
        {st?.since ? `新着は、株価を取得した ${mdTime(st.since)} より後に、開示だけ取り直して見つかったものです。` : ""}
      </p>
    </Card>
  );
}

function RankingCard({ rows, universe }: { rows: StockRow[]; universe: number }) {
  return (
    <Card icon="trend" title="モメンタム度ランキング" link="TOP 50 を見る" onLink={() => go("ranking")} guide="ranking"
      sub={`売買代金20日平均5,000万円以上の ${num(universe)} 銘柄から`}>
      <div className="list-head"><span>順位</span><span>銘柄名</span><span className="text-right">モメンタム度</span><span className="text-center">ランク</span></div>
      {rows.map((r) => (
        <button key={r.code} className="list-row" onClick={() => go(`stock/${r.code}`)}>
          <span className="list-pos">#{r.position}</span>
          <span className="list-name">
            <b>{r.name}</b>
            <small className="list-sub">
              <span>{r.code} · 1か月 <span className={r.chg20 != null && r.chg20 >= 0 ? "t-up" : "t-down"}>{pct(r.chg20)}</span></span>
              <ThemeChip row={r} />
              <WhyNote row={r} text={false} />
            </small>
          </span>
          <span className="list-val">{num(r.score)}</span>
          <span className="text-center"><RankBadge rank={r.rank} /></span>
        </button>
      ))}
    </Card>
  );
}

function SignalCard({ data }: { data: HomeData }) {
  const s = data.signals;
  return (
    <Card icon="bolt" title="シグナル" link="一覧を見る" onLink={() => go("signals")} guide="signals-home">
      <div className="flex items-baseline gap-2">
        <span className="t-2 text-[13px]">本日</span>
        <span className="text-[30px] font-extrabold t-accent leading-none">{num(s.total)}</span>
        <span className="t-2 text-[13px]">件（流動性あり {num(s.liquid)} 件）</span>
      </div>
      <div className="grid grid-cols-2 gap-2 mt-3">
        {s.by_type.map((t) => (
          <button key={t.key} className="tile pressable" onClick={() => go("signals")}>
            <div className="flex items-center justify-between">
              <span className={`text-[13px] font-semibold ${t.tone === "warn" ? "t-warn" : "t-1"}`}>{t.label}</span>
              <span className="text-[15px] font-bold num">{t.count}</span>
            </div>
            <div className="note !text-[10.5px] mt-0.5">
              20日後 市場比 <span className="t-2 num">{pct(t.excess20, 2)}</span> · 勝率 <span className="t-2 num">{num(t.win20)}%</span>
            </div>
          </button>
        ))}
      </div>
      <p className="note mt-2">
        「市場比」は同じ期間の全銘柄平均との差、「勝率」は市場平均に勝った割合（これまでの実績・流動性のある銘柄）。
        {data.verify_summary == null
          ? ""
          : data.verify_summary.signals_significant === 0
            ? "どのシグナルも、偶然と区別できる差はありません。"
            : `${data.verify_summary.signals_significant} 種類のシグナルに、偶然とは言いにくい差があります（検証画面）。`}
      </p>
    </Card>
  );
}

function MarginCard({ m }: { m: HomeData["margin"] }) {
  if (m === undefined) return null; // 制度信用倍率の無い古いデータ
  return (
    <Card icon="scale" title="制度信用倍率" link="一覧を見る" onLink={() => go("margin")} guide="margin-home"
      sub={m ? `制度信用の買い残 ÷ 売り残（${mdDate(m.date)} 申込み分）` : undefined}>
      {m === null ? (
        <p className="note">この日は JPX の信用残を取得できませんでした。</p>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          <button className="tile pressable" onClick={() => go("margin")}>
            <div className="text-[12px] t-2">全銘柄の合計</div>
            <div className="text-[20px] font-bold num">{num(m.ratio, 2)}<span className="text-[13px] t-2 ml-0.5">倍</span></div>
            <div className="note !text-[11px]">前日 {num(m.ratio_prev, 2)}倍</div>
          </button>
          <button className="tile pressable" onClick={() => go("margin")}>
            <div className="text-[12px] t-2">売り長（1倍未満）</div>
            <div className="text-[20px] font-bold num">{num(m.short)}<span className="text-[13px] t-2 ml-0.5">銘柄</span></div>
            <div className="note !text-[11px]">倍率のある {num(m.rated)} 銘柄中</div>
          </button>
        </div>
      )}
    </Card>
  );
}

function WatchCard({ rows }: { rows: StockRow[] }) {
  return (
    <Card icon="star" title="ウォッチリスト" link={`登録 ${rows.length} 件`} onLink={() => go("watchlist")} guide="watch">
      {rows.length === 0 && <p className="note">銘柄詳細の ☆ で追加できます（この端末の中に保存されます）。</p>}
      {rows.map((r) =>
        r.missing ? (
          <div key={r.code} className="list-row"><span className="t-3 text-[12px]">{r.code}</span><span className="t-3 text-[12px]">日足なし</span><span /><span /></div>
        ) : (
          <button key={r.code} className="list-row" style={{ gridTemplateColumns: "1fr auto auto 40px" }} onClick={() => go(`stock/${r.code}`)}>
            <span className="list-name"><b>{r.name}</b><small className="list-sub wrap"><span>{r.code}</span><RowMarks row={r} /></small></span>
            <span className="text-right text-[13px] num">{yen(r.close)}</span>
            <span className="text-right text-[12px] w-[52px]"><Delta v={r.chg1} /></span>
            <span className="text-center"><RankBadge rank={r.rank} /></span>
          </button>
        ),
      )}
    </Card>
  );
}
