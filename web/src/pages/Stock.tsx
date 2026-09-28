import { useEffect, useMemo, useState } from "react";
import { api, invalidate, paths, useData } from "../data";
import { setWatched } from "../watch";
import Radar from "../components/Radar";
import StockChart from "../components/StockChart";
import { Card, Delta, Disclaimer, ErrorBox, Icon, Loading, RankBadge, Sheet, WhyChip } from "../components/ui";
import { mdDate, mdTime, num, pct, shares, signed, yen, yenLarge } from "../format";
import { METRICS, RANK_TEXT, type MetricInfo } from "../metrics";
import { back, go, rememberStock } from "../router";
import type { Disclosure, Margin, Reason, Report, StockDetail, StockSignal } from "../types";

export default function Stock({ code }: { code: string }) {
  const { data, error, loading, reload } = useData<StockDetail>(paths.stock(code), () => api.stock(code));
  const [sheet, setSheet] = useState<MetricInfo | null>(null);
  const [watched, setWatchedState] = useState<boolean | null>(null);

  useEffect(() => {
    if (data) {
      rememberStock(data.code, data.name);
      setWatchedState(data.watched);
    }
  }, [data]);

  // ウォッチリストはこの端末の中に保存する（watch.ts）
  const toggleWatch = () => {
    if (!data) return;
    setWatched(data.code, !watched);
    setWatchedState(!watched);
    invalidate(paths.home);
  };

  return (
    <div>
      <div className="top-bar">
        <button className="icon-btn" onClick={back} aria-label="戻る"><Icon name="back" /></button>
        <h1>{code} {data?.name ?? ""}</h1>
        <button className="icon-btn" onClick={toggleWatch} aria-label={watched ? "ウォッチリストから外す" : "ウォッチリストに追加"} disabled={!data}
          style={{ color: watched ? "var(--gold)" : "var(--text-2)" }}>
          <Icon name={watched ? "star-fill" : "star"} />
        </button>
      </div>

      {loading && !data && <Loading label="銘柄の指標を読み込み中…" slow />}
      {error && !data && <ErrorBox message={error} onRetry={reload} />}
      {data && (
        <div className={loading ? "fade-stale" : ""}>
          <Summary d={data} />
          <ReasonCard d={data} />
          <MetricsCard d={data} onOpen={setSheet} />
          <RadarCard d={data} />
          <Card icon="trend" title="モメンタム度推移 × 日足" guide="chart" sub="上段=株価、下段=モメンタム度（0〜100）。指で触れた日の値が上に出ます">
            <StockChart chart={data.chart} signals={data.signals} />
          </Card>
          <SignalsCard signals={data.signals} />
          <ReportCard d={data} />
          <Card guide="verify-link">
            <button className="w-full flex items-center justify-between text-left" onClick={() => go("verify")}>
              <span>
                <span className="font-bold flex items-center gap-2"><Icon name="flask" size={18} />この数字は当たるのか？</span>
                <span className="note block mt-1">指標とシグナルのこれまでの実績（市場平均との差）を検証画面で確認できます。</span>
              </span>
              <Icon name="chev" />
            </button>
          </Card>
          <Disclaimer />
        </div>
      )}

      <Sheet open={sheet != null} onClose={() => setSheet(null)} title={sheet?.label}>
        {sheet && data && <MetricSheet info={sheet} d={data} />}
      </Sheet>
    </div>
  );
}

/* ---------- 概要 ---------- */

function Summary({ d }: { d: StockDetail }) {
  const m = d.metrics;
  return (
    <Card guide="summary">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[20px] font-extrabold leading-tight">{d.name}</div>
          <div className="note mt-0.5">{d.code} · {d.segment ?? "—"} · {d.sector33 ?? "—"}</div>
        </div>
        {d.signals_today.length > 0 && (
          <span className="chip chip-up shrink-0"><Icon name="bolt" size={12} />本日シグナル</span>
        )}
      </div>
      <div className="flex items-end gap-3 mt-3">
        <span className="text-[28px] font-bold leading-none">{yen(d.close)}</span>
        <span className="text-[15px] font-semibold"><Delta v={d.chg1} digits={2} /></span>
      </div>
      <div className="flex gap-4 mt-1.5 text-[12.5px] t-2">
        <span>5日 <Delta v={d.chg5} /></span>
        <span>1か月 <Delta v={d.chg20} /></span>
        <span>3か月 <Delta v={d.chg60} /></span>
      </div>

      <div className="tile mt-3">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-[12px] t-2">モメンタム度</div>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-[30px] font-extrabold leading-none">{num(m.score)}</span>
              <RankBadge rank={m.rank} large />
              <span className="text-[13px] t-2">{m.rank ? RANK_TEXT[m.rank] : ""}</span>
            </div>
          </div>
          <div className="text-right text-[12px] t-2 leading-6">
            <div>前日 <Delta v={m.score_d1} suffix="" /></div>
            <div>5日 <Delta v={m.score_d5} suffix="" /></div>
            <div>1か月 <Delta v={m.score_d20} suffix="" /></div>
          </div>
        </div>
        <div className="note mt-2">
          {d.position != null
            ? `流動性のある ${num(d.universe)} 銘柄中 ${num(d.position)} 位`
            : "売買代金が少ない（20日平均5,000万円未満）ため順位・実績の集計対象外"}
          {" · "}売買代金 {yenLarge(m.turnover20)}/日
        </div>
      </div>
      {!d.traded_today && (
        <p className="note mt-2 t-warn">最新日は売買が成立していません。{mdDate(d.last_date)} 時点の値です。</p>
      )}
    </Card>
  );
}

/* ---------- 値動きの理由 ---------- */

const KIND_CLASS: Record<Disclosure["kind"], string> = { news: "why-news", supply: "why-supply", routine: "why-routine" };

/** 判定の中身を1〜2文で。数字はその日のデータから作る（固定の文面にしない） */
function reasonSentence(r: Reason): string {
  if (r.ret == null) return "最新日は売買が成立していないため、判定していません。";
  const move = `業種平均との差 ${pct(r.idio)}`;
  const why = r.z != null && Math.abs(r.z) >= 3
    ? `（普段の${num(Math.abs(r.z), 1)}倍）`
    : r.vr != null && r.vr >= 3 ? `（出来高は20日平均の${num(r.vr, 1)}倍）` : "";
  if (r.notable && !r.checked) {
    return `目立って動きました（${move}）が、開示を取得できなかった日を含むため、理由を判定していません。`;
  }
  switch (r.label) {
    case "news":
      return `業種平均より ${pct(r.idio)} 動きました${why}。前の取引日の引け後から当日の引けまでに、会社の開示がありました。`;
    case "supply":
      return r.disclosures.some((x) => x.kind === "supply")
        ? `業種平均より ${pct(r.idio)} 動きました${why}。増資・自社株買いなど、株の需給に関わる開示がありました。`
        : `業種平均より ${pct(r.idio)} 動きました${why}。開示はありませんが、需給の手がかりがあります。`;
    case "market":
      return r.clues.some((c) => c.key === "group")
        ? `業種平均より ${pct(r.idio)} 動きました${why}。開示はありませんが、同じ業種の他の銘柄もそろって同じ向きに動いた日です。`
        : `${r.sector ?? "業種"}全体が ${pct(r.sector_ret)} 動いた日で、この銘柄だけの動きは目立ちません（${move}）。`;
    case "unknown":
      return `業種平均より ${pct(r.idio)} 動きました${why}が、開示も需給の手がかりも見当たりません。新聞報道やテーマ買いなど、ここでは拾えない理由の可能性があります。`;
    default:
      return `目立った動きはありません（${move}・出来高は20日平均の${num(r.vr, 1)}倍）。`;
  }
}

function ReasonCard({ d }: { d: StockDetail }) {
  const r = d.reason;
  if (!r) return null; // 値動きの理由を作れなかった日・古いデータ
  // 判定に効いた順に並んでいる（reasons.py）。多い日は上から3件だけ出し、残りは下の一覧で見る
  const relevant = r.disclosures.filter((x) => x.kind !== "routine");
  const shown = relevant.slice(0, 3);
  return (
    <Card icon="pulse" guide="reason" aside={mdDate(r.date)}
      title={<span className="flex items-center gap-2">値動きの理由<WhyChip why={r.label} /></span>}>
      <p className="text-[13.5px] leading-relaxed">{reasonSentence(r)}</p>

      {shown.length > 0 && (
        <div className="mt-2 space-y-1.5">
          {shown.map((x) => (
            <div key={x.time + x.title} className="tile !py-2">
              <div className="flex items-center gap-1.5 text-[11.5px] t-3">
                <span className="num">{mdTime(x.time)}</span>
                <span className={`why ${KIND_CLASS[x.kind]}`}>{x.category}</span>
              </div>
              <DisclosureTitle x={x} className="text-[13px] mt-1 leading-snug" />
            </div>
          ))}
          {relevant.length > shown.length && (
            <p className="note">ほか {relevant.length - shown.length} 件は、下の「直近30日の開示」にあります。</p>
          )}
        </div>
      )}
      {r.clues.length > 0 && (
        <ul className="mt-2 space-y-1">
          {r.clues.map((c) => (
            <li key={c.key} className="text-[13px] leading-snug t-1">・{c.text}</li>
          ))}
        </ul>
      )}

      <table className="tbl mt-3">
        <tbody>
          <tr><td>当日の騰落率</td><td><Delta v={r.ret} digits={2} /></td></tr>
          <tr><td>業種（{r.sector ?? "—"}）の中央値</td><td><Delta v={r.sector_ret} /></td></tr>
          <tr><td>市場全体の中央値</td><td><Delta v={r.market_ret} /></td></tr>
          <tr><td>出来高（20日平均比）</td><td>{r.vr != null ? `${num(r.vr, 1)}倍` : "—"}</td></tr>
          <tr>
            <td>機関の空売り残高</td>
            <td style={{ whiteSpace: "normal" }}>
              {r.short ? `${num(r.short.now, 2)}%（前回 ${num(r.short.prev, 2)}%・${r.short.holders}社）` : "報告なし"}
            </td>
          </tr>
          {r.margin && <MarginRows m={r.margin} />}
          <tr><td>逆日歩</td><td>{r.premium ? `${num(r.premium.rate, 2)}円` : "なし"}</td></tr>
          <tr><td>信用取引の規制など</td><td style={{ whiteSpace: "normal" }}>{r.flags.length ? r.flags.join("・") : "なし"}</td></tr>
        </tbody>
      </table>
      <p className="note mt-2">
        ニュースは会社の適時開示だけで、新聞報道・アナリストの格付け・テーマ買いは含みません。
        需給の手がかりは状況証拠で、原因の証明ではありません。
        機関の空売り残高は、発行済株式の0.5%以上を空売りしている機関の報告分{r.short ? `（${mdDate(r.short.date)} 計算分まで）` : ""}。
        {r.margin && `信用残は ${mdDate(r.margin.date)} 申込み時点（JPX・毎日16時公表）で、日数は直前20日平均の出来高の何日分か。`}
        逆日歩は権利取りの時期に優待目当てでも付くため、判定には使わず表示だけにしています。
      </p>
      <DisclosureList items={d.disclosures ?? []} />
    </Card>
  );
}

function MarginRows({ m }: { m: Margin }) {
  const days = (d: number | null) => (d != null ? `・出来高の${num(d, 1)}日分` : "");
  const chg = (c: number | null) => (c != null ? `（前日比 ${c > 0 ? "+" : c < 0 ? "−" : "±"}${shares(Math.abs(c))}）` : "");
  return (
    <>
      <tr>
        <td>信用買い残</td>
        <td style={{ whiteSpace: "normal" }}>{shares(m.buy)}{chg(m.buy_chg)}{days(m.buy_days)}{m.buy_ratio != null ? `・上場比${num(m.buy_ratio, 1)}%` : ""}</td>
      </tr>
      <tr>
        <td>信用売り残</td>
        <td style={{ whiteSpace: "normal" }}>{shares(m.sell)}{chg(m.sell_chg)}{days(m.sell_days)}</td>
      </tr>
      <tr><td>信用倍率（買い÷売り）</td><td>{m.ratio != null ? `${num(m.ratio, 2)}倍` : "売り残なし"}</td></tr>
    </>
  );
}

function DisclosureTitle({ x, className = "" }: { x: Disclosure; className?: string }) {
  const tone = x.kind === "routine" ? "t-3" : "t-1";
  if (!x.url) return <div className={`${className} ${tone}`}>{x.title}</div>;
  return (
    <a className={`${className} ${tone} block underline decoration-dotted underline-offset-2`} href={x.url} target="_blank" rel="noreferrer">
      {x.title}
    </a>
  );
}

function DisclosureList({ items }: { items: Disclosure[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? items : items.slice(0, 5);
  return (
    <div className="mt-4">
      <div className="text-[13px] font-bold">直近30日の開示</div>
      {items.length === 0 ? (
        <p className="note mt-1">直近30日の開示はありません。</p>
      ) : (
        <>
          <div className="note">右はその開示が効いた取引日の騰落率（かっこ内は業種平均との差）。表題を押すと TDnet の PDF が開きます（公開から31日で消えます）。</div>
          {shown.map((x) => (
            <div key={x.time + x.title} className="grid gap-x-3 py-2 border-t border-[rgba(120,200,230,0.08)] first:border-t-0"
              style={{ gridTemplateColumns: "minmax(0,1fr) auto" }}>
              <div className="min-w-0">
                <div className="flex items-center gap-1.5 text-[11.5px] t-3">
                  <span className="num">{mdTime(x.time)}</span>
                  <span className={`why ${KIND_CLASS[x.kind]}`}>{x.category}</span>
                </div>
                <DisclosureTitle x={x} className="text-[12.5px] mt-1 leading-snug" />
              </div>
              <div className="text-right text-[12px] whitespace-nowrap">
                {x.day ? (
                  <>
                    <div className="note !text-[10.5px]">{mdDate(x.day)}</div>
                    <div className="font-semibold"><Delta v={x.ret} /></div>
                    <div className="text-[10.5px] t-3 num">（{pct(x.idio)}）</div>
                  </>
                ) : (
                  <span className="note">次の取引日</span>
                )}
              </div>
            </div>
          ))}
          {items.length > 5 && (
            <button className="btn-ghost w-full mt-2 text-[13px]" onClick={() => setAll(!all)}>
              {all ? "閉じる" : `すべて表示（${items.length}件）`}
            </button>
          )}
        </>
      )}
    </div>
  );
}

/* ---------- 主要指標 ---------- */

function MetricsCard({ d, onOpen }: { d: StockDetail; onOpen: (m: MetricInfo) => void }) {
  const alerts = d.report.available ? d.report.alerts : [];
  return (
    <Card title="主要指標" guide="metrics" sub="タップで意味と読み方を確認">
      <div className="grid grid-cols-2 gap-2">
        {METRICS.map((info) => {
          const v = d.metrics[info.key] as number | null;
          const r = v == null ? null : info.read(v);
          return (
            <button key={info.key} className="tile pressable" onClick={() => onOpen(info)} style={r?.tone === "warn" ? { borderColor: "rgba(240,180,76,0.5)" } : undefined}>
              <div className="flex items-center justify-between text-[12px] t-2 font-semibold">
                {info.short}
                <span className="t-3"><Icon name="info" size={15} /></span>
              </div>
              <div className="text-[22px] font-bold mt-0.5 num">{v == null ? "—" : info.key === "power" ? signed(v, 2, "") : num(v, info.digits)}</div>
              <div className={`text-[11.5px] mt-0.5 flex items-center gap-1 ${r?.tone === "warn" ? "t-warn" : "t-2"}`}>
                {r?.tone === "warn" && <Icon name="warn" size={12} />}
                {r?.text ?? "データ不足"}
              </div>
            </button>
          );
        })}
      </div>
      <div className="tile mt-2">
        <div className="text-[12px] font-semibold t-gold flex items-center gap-1"><Icon name="warn" size={14} />警戒メモ</div>
        {alerts.length === 0 ? (
          <div className="text-[13px] t-2 mt-1">特に目立つ警戒点はありません。</div>
        ) : (
          <ul className="mt-1 space-y-1">
            {alerts.map((a, i) => (
              <li key={i} className={`text-[13px] leading-snug ${a.level === "warn" ? "t-1" : "t-2"}`}>
                {a.level === "warn" ? "⚠ " : "・"}{a.text}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

function MetricSheet({ info, d }: { info: MetricInfo; d: StockDetail }) {
  const v = d.metrics[info.key] as number | null;
  const r = v == null ? null : info.read(v);
  return (
    <div>
      <div className="tile">
        <div className="text-[13px] t-2">{d.name}</div>
        <div className="text-[30px] font-extrabold">{v == null ? "—" : info.key === "power" ? signed(v, 2, "") : num(v, info.digits)}</div>
        <div className={`text-[13px] font-semibold ${r?.tone === "warn" ? "t-warn" : "t-accent"}`}>{r?.text ?? "データ不足"}</div>
      </div>
      <dl className="mt-3 space-y-3 prose !text-[13.5px]">
        <div><dt className="font-bold t-1">何を測っているか</dt><dd className="m-0">{info.what}</dd></div>
        <div><dt className="font-bold t-1">読み方</dt><dd className="m-0">{info.how}</dd></div>
        <div><dt className="font-bold t-1">何と比べた値か</dt><dd className="m-0">{info.compare}</dd></div>
        <div><dt className="font-bold t-1">実測で分かっていること</dt><dd className="m-0">{info.evidence}</dd></div>
      </dl>
      <p className="note mt-3">この指標単体で判断せず、トレンド・シグナル・価格の推移とあわせて見ることが前提です。</p>
    </div>
  );
}

/* ---------- 5角形 ---------- */

function RadarCard({ d }: { d: StockDetail }) {
  const h = d.rank_history?.horizons["20"];
  return (
    <Card title="5角形" guide="radar" sub="外側ほど強い（0〜100）。SR・POWERはその日の全銘柄の中での位置、安定度は自分の過去1年との比較">
      <div className="flex justify-center">
        <Radar axes={d.radar} />
      </div>
      {d.rank_history && h && (
        <div className="tile mt-2">
          <div className="text-[12px] t-2">
            ランク{d.rank_history.rank}（{RANK_TEXT[d.rank_history.rank]}）だった銘柄のこれまでの実績
          </div>
          <div className="flex items-baseline gap-3 mt-1">
            <span className="text-[13px] t-2">20営業日後 市場比</span>
            <span className="text-[18px] font-bold"><Delta v={h.excess_mean} digits={2} /></span>
            <span className="text-[13px] t-2">勝率 <b className="t-1">{num(h.win_rate, 1)}%</b></span>
          </div>
          <div className="note mt-1">
            {h.t != null && Math.abs(h.t) >= 2 ? `t値 ${num(h.t, 2)}（統計的に有意）` : `t値 ${num(h.t, 2)}（偶然と区別できない）`}
            {" · "}前半 {pct(h.first_half, 2)} / 後半 {pct(h.second_half, 2)}
          </div>
        </div>
      )}
    </Card>
  );
}

/* ---------- シグナル ---------- */

function SignalsCard({ signals }: { signals: StockSignal[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? signals : signals.slice(0, 6);
  return (
    <Card icon="bolt" title="検知シグナルと、その後" guide="signals"
      sub="発動の翌営業日の始値から、N営業日後の終値まで。（）内は同じ期間の市場平均との差">
      {signals.length === 0 && <p className="text-[13px] t-2">期間中（約2年）に検知したシグナルはありません。</p>}
      <div className="space-y-2">
        {shown.map((s) => (
          <div key={`${s.date}-${s.key}`} className="tile">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2">
                <span className="text-[13px] font-semibold num">{mdDate(s.date)}</span>
                <span className={`chip ${s.tone === "warn" ? "chip-warn" : "chip-up"}`}>{s.label}</span>
              </span>
              <span className="text-[12px] t-2">
                {s.entry != null ? <>参考 {yen(s.entry)}（{mdDate(s.entry_date)}始値）</> : "翌日待ち"}
              </span>
            </div>
            <div className="grid grid-cols-4 gap-1 mt-2 text-center">
              {(["5", "10", "20"] as const).map((h) => {
                const x = s.horizons[h];
                return (
                  <div key={h}>
                    <div className="note !text-[10.5px]">{h}日後</div>
                    {x ? (
                      <>
                        <div className="text-[13px] font-semibold"><Delta v={x.ret} /></div>
                        <div className="text-[10.5px] t-3 num whitespace-nowrap">（{pct(x.excess)}）</div>
                      </>
                    ) : (
                      <div className="text-[12px] t-3 mt-0.5">経過待ち</div>
                    )}
                  </div>
                );
              })}
              <div>
                <div className="note !text-[10.5px]">現在</div>
                <div className="text-[13px] font-semibold"><Delta v={s.now_pct} /></div>
                {!s.liquid && <div className="text-[10px] t-3">集計対象外</div>}
              </div>
            </div>
          </div>
        ))}
      </div>
      {signals.length > 6 && (
        <button className="btn-ghost w-full mt-2 text-[13px]" onClick={() => setAll(!all)}>
          {all ? "閉じる" : `すべて表示（${signals.length}件）`}
        </button>
      )}
      <p className="note mt-2">
        シグナルの定義と、全銘柄での過去の実績は <button className="card-link !inline !p-0" onClick={() => go("signals")}>シグナル一覧</button> にあります。
      </p>
    </Card>
  );
}

/* ---------- テクニカル整理 ---------- */

const TREND_CLASS: Record<string, string> = { 上昇: "t-up", 下降: "t-down", レンジ: "t-2" };

function ReportCard({ d }: { d: StockDetail }) {
  const r: Report = d.report;
  // チャートに引く節目は戻り高値と押し安値だけ（移動平均は線で出ている）。
  // 配列を毎回作るとチャートが作り直されるので固定する
  const chartLevels = useMemo(
    () => (r.available ? r.levels.filter((l) => l.key === "resistance" || l.key === "support") : []),
    [r],
  );
  if (!r.available) {
    return (
      <Card title="テクニカル整理" guide="report"><p className="text-[13px] t-2">{r.reason}</p></Card>
    );
  }
  const tf = r.timeframes;
  const b = r.background;
  return (
    <Card title="テクニカル整理" guide="report" sub="決まったルールで機械的に整理したもの（AIの文章ではなく、同じデータなら同じ結果）">
      <div className="tile">
        <div className="text-[12px] font-semibold t-accent">まとめ</div>
        <p className="text-[14px] leading-relaxed mt-1">{r.conclusion}</p>
      </div>

      <div className="mt-3 text-[13px] font-bold">時間軸の流れ</div>
      <div className="grid grid-cols-3 gap-2 mt-1.5">
        {([["monthly", "月足", "6か月線"], ["weekly", "週足", "13週線"], ["daily", "日足", "25日線"]] as const).map(([k, label, ma]) => {
          const t = tf[k];
          return (
            <div key={k} className="tile text-center">
              <div className="note !text-[11px]">{label}</div>
              <div className={`text-[18px] font-bold ${t ? TREND_CLASS[t.label] : "t-3"}`}>{t?.label ?? "—"}</div>
              <div className="note !text-[10px] leading-tight mt-0.5">
                {t ? <>{ma}{t.above ? "の上" : "の下"}<br />傾き {pct(t.slope_pct, 1)}</> : "本数不足"}
              </div>
            </div>
          );
        })}
      </div>
      <div className="note mt-1.5">{r.alignment}</div>

      <div className="grid grid-cols-2 gap-2 mt-3">
        <div className="tile">
          <div className="note !text-[11px]">局面</div>
          <div className="text-[17px] font-bold">{r.phase.label}</div>
          <div className="text-[11.5px] t-2 mt-0.5 leading-snug">{r.phase.text}</div>
        </div>
        <div className="tile">
          <div className="note !text-[11px]">{b.position_window >= 240 ? "52週" : `${b.position_window}日`}レンジ内の位置</div>
          <div className="text-[17px] font-bold">{num(b.position)}%</div>
          <div className="h-1.5 rounded bg-[#1a3440] mt-1.5 overflow-hidden">
            <div className="h-full rounded" style={{ width: `${Math.max(2, Math.min(100, b.position ?? 0))}%`, background: "var(--accent)" }} />
          </div>
          <div className="flex justify-between note !text-[10px] mt-0.5"><span>{yen(b.low)}</span><span>{yen(b.high)}</span></div>
        </div>
        <div className="tile">
          <div className="note !text-[11px]">出来高（5日÷60日）</div>
          <div className="text-[17px] font-bold">{b.vol_state ?? "—"}</div>
          <div className="text-[11.5px] t-2">{num(b.vol_ratio, 2)} 倍</div>
        </div>
        <div className="tile">
          <div className="note !text-[11px]">移動平均からの乖離</div>
          <div className="text-[13px] mt-1">25日 <b><Delta v={b.dev25} /></b></div>
          <div className="text-[13px]">75日 <b><Delta v={b.dev75} /></b></div>
          <div className="note !text-[10.5px] mt-0.5">1日の平均値幅 {yen(b.atr >= 100 ? Math.round(b.atr) : b.atr)}（{num(b.atr_pct, 1)}%）</div>
        </div>
      </div>

      <div className="mt-4 text-[13px] font-bold">節目</div>
      <div className="note mb-2">直近の戻り高値・押し安値（前後5本で最も高い・安い足）と移動平均。点線がチャート上の位置です。</div>
      <StockChart chart={d.chart} levels={chartLevels} showScore={false} defaultPeriod="6M" height={250} />
      <table className="tbl mt-3">
        <thead>
          <tr><th>節目</th><th>価格</th><th>現在値から</th></tr>
        </thead>
        <tbody>
          {r.levels.map((l) => (
            <tr key={l.key}>
              <td>{l.label}</td>
              <td>{yen(l.price)}</td>
              <td><Delta v={d.close ? (l.price / d.close - 1) * 100 : null} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {r.range.ratio != null && (
        <div className="tile mt-3">
          <div className="text-[12px] t-2">戻り高値までの余地 : 押し安値までの余地</div>
          <div className="text-[18px] font-bold mt-0.5">
            <span className="t-up">{pct(r.range.upside_pct)}</span>
            <span className="t-3 mx-2">:</span>
            <span className="t-down">{pct(r.range.downside_pct)}</span>
            <span className="text-[13px] t-2 ml-2">（{num(r.range.ratio, 2)} 倍）</span>
          </div>
          <div className="note mt-1">節目までの距離を比べただけの目安です。節目で止まる保証はありません。</div>
        </div>
      )}
      <ul className="mt-3 space-y-1.5">
        {r.levels.map((l) => (
          <li key={l.key} className="note"><b className="t-2">{l.label}</b>: {l.note}</li>
        ))}
      </ul>
    </Card>
  );
}

