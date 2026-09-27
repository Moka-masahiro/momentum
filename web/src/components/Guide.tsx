import { useEffect, useState } from "react";
import { api } from "../data";
import { go } from "../router";
import { Icon } from "./ui";

/**
 * 使い方ガイド。画面の該当箇所（data-guide 属性）を金色の枠で囲み、下の吹き出しで説明する。
 * 紹介動画のアプリにあった「ステップごとに実データの画面を案内する」形を真似ている。
 */
export interface Step {
  route?: string;          // この画面へ移動してから案内する。"@top" はランキング1位の銘柄
  target: string;          // data-guide の値
  title: string;
  body: string;
  action?: string;         // 「次へ」ボタンの文言
}

export interface Tour {
  key: string;
  title: string;
  desc: string;
  steps: Step[];
}

export const TOURS: Tour[] = [
  {
    key: "today",
    title: "今日見る銘柄を探す",
    desc: "検索とランキングから詳細画面へ。上から順に何を見るか",
    steps: [
      { route: "", target: "search", title: "下の検索から探せます",
        body: "「銘柄検索」を押すと、会社名の一部や銘柄コード（例: 7203、トヨタ）で探せます。" },
      { route: "", target: "ranking", title: "ランキング上位の銘柄で説明します",
        body: "このガイドでは、いまモメンタム度が1位の銘柄を例に、詳細画面を上から順に見ていきます。", action: "実データで見る" },
      { route: "@top", target: "summary", title: "まず銘柄名と全体感",
        body: "株価と5日・1か月・3か月の騰落率、モメンタム度とランク、流動性のある約1,900銘柄の中での順位です。" },
      { target: "metrics", title: "今日見る理由を数字で確認",
        body: "勢い（モメンタム度・POWER）、上げ方の質（SR）、需給（買い集め）、荒れ具合（安定度）、過熱感（RSI）。カードをタップすると意味と読み方が開きます。" },
      { target: "radar", title: "5角形で強さの偏りを見る",
        body: "5項目とも外側ほど強い。いびつな形なら弱点があります。下に、同じランクだった銘柄が過去にどうなったかを出しています。" },
      { target: "chart", title: "値動きと勢いを合わせて見る",
        body: "上段が株価、下段がモメンタム度。指で触れた日の値が上に出ます。▲はシグナルが出た日です。" },
      { target: "signals", title: "シグナルと、その後",
        body: "発動の翌営業日の始値から5・10・20営業日後まで。小さい数字は同じ期間の市場平均との差で、ここがプラスなら市場より良かったことになります。" },
      { target: "report", title: "テクニカル整理",
        body: "月足・週足・日足の向き、局面、節目を決まったルールで機械的に整理しています（AIの文章ではないので、同じデータなら必ず同じ結果）。" },
      { target: "verify-link", title: "この数字は当たるのか？",
        body: "モメンタム度やシグナルが過去にどれだけ当たったかは「検証」で毎日計算し直しています。いまのところ、どれも市場平均を有意に上回っていません。", action: "ガイドを終える" },
    ],
  },
  {
    key: "market",
    title: "地合いの見方",
    desc: "相場全体が強いのか、一部だけなのか",
    steps: [
      { route: "", target: "market", title: "地合い（相場全体の強さ）",
        body: "日経平均そのもののモメンタム度と、プライム・グロースの全銘柄のモメンタム度の中央値です。下の比率は、ランクB以上の銘柄がどれだけあるか。" },
      { route: "market", target: "breadth", title: "上向きの銘柄の広がり",
        body: "指数が上がっていてもこの比率が下がっていれば、一部の大型株だけの上げです。" },
      { target: "segments", title: "市場区分ごとの強さ",
        body: "プライム・スタンダード・グロースの中央値の推移。どの市場に勢いがあるかを比べます。", action: "ガイドを終える" },
    ],
  },
  {
    key: "signals",
    title: "シグナルの見方",
    desc: "出来事の検知と、過去の実績の読み方",
    steps: [
      { route: "signals", target: "signal-date", title: "日付を選ぶ",
        body: "直近20営業日のシグナルを見返せます。件数は、その日に条件を満たした銘柄の数です。" },
      { target: "signal-group", title: "定義と、これまでの実績",
        body: "各シグナルの条件と、流動性のある銘柄での過去の成績。「市場平均との差」と「勝率（市場比）」を見ます。素の平均は相場全体の上げを含むので参考程度に。", action: "ガイドを終える" },
    ],
  },
  {
    key: "verify",
    title: "検証の見方",
    desc: "この数字をどこまで信じてよいか",
    steps: [
      { route: "verify", target: "verify-summary", title: "結論から",
        body: "各指標が高い銘柄ほど、その後に市場平均を上回ったかを測っています。" },
      { target: "verify-ic", title: "IC（順位の相関）",
        body: "0なら無関係。t値が2以上なら偶然とは言いにくい。前半と後半で符号が逆なら、局面によって効き方が変わっているということです。" },
      { target: "verify-rolling", title: "局面の変化",
        body: "60日ごとの平均。0より上の時期は「強い銘柄がさらに強かった」、下の時期は「強い銘柄が失速した」時期です。" },
      { target: "verify-ranks", title: "ランク別の実績",
        body: "ランクごとの、その後の市場比と勝率。ランクSが一番良いとは限りません。", action: "ガイドを終える" },
    ],
  },
];

function current(): string {
  return window.location.hash.replace(/^#\/?/, "");
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function GuideRunner({ tour, onClose }: { tour: Tour; onClose: () => void }) {
  const [i, setI] = useState(0);
  const step = tour.steps[i];
  const last = i === tour.steps.length - 1;

  useEffect(() => {
    let cancelled = false;
    let el: HTMLElement | null = null;
    (async () => {
      let route = step.route;
      if (route === "@top") {
        const r = await api.ranking("", 50_000_000, 1).catch(() => null);
        route = r?.items[0] ? `stock/${r.items[0].code}` : "ranking";
      }
      if (route !== undefined && current() !== route) go(route);
      // 画面の描画（データの取得）を待つ
      for (let k = 0; k < 80 && !cancelled; k++) {
        el = document.querySelector<HTMLElement>(`[data-guide="${step.target}"]`);
        if (el) break;
        await sleep(100);
      }
      if (cancelled || !el) return;
      await sleep(80);
      el.classList.add("guide-focus");
      if (el.closest(".bottom-bar")) return; // 画面下に固定された検索ボタンなどはスクロール不要
      const top = Math.max(0, el.getBoundingClientRect().top + window.scrollY - 76);
      window.scrollTo({ top, behavior: "smooth" });
      // 描画が止まっている（省電力・背面のタブ等）とスムーズスクロールが進まないことがあるので、
      // 届いていなければ最後は瞬時に合わせる
      await sleep(650);
      if (!cancelled && Math.abs(window.scrollY - top) > 40) window.scrollTo(0, top);
    })();
    return () => {
      cancelled = true;
      document.querySelectorAll(".guide-focus").forEach((e) => e.classList.remove("guide-focus"));
    };
  }, [tour, i, step]);

  return (
    <div className="guide-card" role="dialog" aria-live="polite">
      <div className="flex items-center justify-between">
        <span className="text-[11.5px] font-semibold t-accent flex items-center gap-1"><Icon name="guide" size={14} />{tour.title}</span>
        <span className="flex items-center gap-2">
          <span className="text-[12px] t-2 num">{i + 1}/{tour.steps.length}</span>
          <button className="icon-btn !w-7 !h-7" onClick={onClose} aria-label="ガイドを閉じる"><Icon name="close" size={14} /></button>
        </span>
      </div>
      <div className="text-[16px] font-bold mt-1.5">{step.title}</div>
      <p className="text-[13.5px] leading-relaxed t-2 mt-1">{step.body}</p>
      <div className="flex gap-2 mt-3">
        <button className="btn-primary" onClick={() => (last ? onClose() : setI(i + 1))}>
          <Icon name={last ? "check" : "chev"} size={16} />
          {step.action ?? (last ? "ガイドを終える" : "次へ")}
        </button>
        {i > 0 && (
          <button className="btn-ghost" onClick={() => setI(i - 1)} aria-label="前へ"><Icon name="back" size={18} /></button>
        )}
      </div>
    </div>
  );
}

export function GuideMenu({ onStart }: { onStart: (t: Tour) => void }) {
  return (
    <div className="space-y-2">
      {TOURS.map((t) => (
        <button key={t.key} className="tile pressable flex items-center justify-between" onClick={() => onStart(t)}>
          <span>
            <span className="block font-bold text-[14px]">{t.title}</span>
            <span className="note block">{t.desc}（{t.steps.length}ステップ）</span>
          </span>
          <Icon name="chev" />
        </button>
      ))}
    </div>
  );
}
