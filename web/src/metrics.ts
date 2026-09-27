/** 指標の説明と、値の読み方。詳細画面のカードと説明シートで使う。
 *
 * 「実測で分かっていること」は、期間を変えても崩れなかった傾向だけを書く
 * （2025-11〜2026-09 の1年分と、2024-12〜2026-08 の約2年分の両方で確認）。
 * 数字そのものは検証画面で毎日計算し直している。
 */
import type { Metrics, Rank } from "./types";

export type Tone = "normal" | "warn";

export interface MetricInfo {
  key: keyof Metrics;
  label: string;
  short: string;       // カードの見出し
  unit?: string;
  digits: number;
  what: string;        // 何を測っているか
  how: string;         // 読み方
  compare: string;     // 何と比べた値か
  evidence: string;    // 実測で分かっていること
  read: (v: number) => { text: string; tone: Tone };
}

export const RANK_TEXT: Record<Rank, string> = {
  S: "強い上昇トレンド",
  A: "上昇トレンド",
  B: "やや上向き",
  C: "中立",
  D: "下降トレンド",
};

export const METRICS: MetricInfo[] = [
  {
    key: "score",
    label: "モメンタム度",
    short: "モメンタム度",
    digits: 0,
    what:
      "直近1か月・3か月・6か月の値上がり（値下がり）を、その銘柄の普段の値動きの大きさで割って合成し、0〜100に直したもの。",
    how: "50が中立。85以上がランクS、70以上A、55以上B、40以上C、40未満D。値動きの荒い銘柄が同じ+10%でも高く出すぎないよう、ばらつきで割っている。",
    compare: "自分自身の値動きと比べた絶対的な値。相場全体が強い日は多くの銘柄が高くなる（順位ではない）。",
    evidence:
      "これまでの検証では、この値が高い銘柄がその後20日で市場平均を上回るとは言えなかった。期間によって効く時期と逆になる時期があり、向きが安定しない。「今どれだけ強いか」の記述として使う。",
    read: (v) => ({ text: v >= 85 ? "強い上昇トレンド" : v >= 70 ? "上昇トレンド" : v >= 55 ? "やや上向き" : v >= 40 ? "中立" : "下降トレンド", tone: "normal" }),
  },
  {
    key: "sr",
    label: "SR（シャープレシオ）",
    short: "SR",
    digits: 2,
    what: "直近60営業日の平均リターンを、リターンのばらつきで割って年率にしたもの。値上がりの「質」を表す。",
    how: "2以上なら値動きのブレに対して安定して上げている。0未満は下落傾向。",
    compare: "自分自身の値動き。レーダーでは、その日の全銘柄の中での位置（0〜100）に直して描いている。",
    evidence: "これまでの検証では、その後のリターンとの関係は有意ではなかった。モメンタム度と同じく、期間によって向きが変わる。",
    read: (v) => ({ text: v >= 3 ? "非常に質の高い上昇" : v >= 2 ? "質の良い上昇" : v >= 1 ? "上昇" : v >= 0 ? "横ばい" : "下落傾向", tone: "normal" }),
  },
  {
    key: "acc",
    label: "買い集め",
    short: "買い集め",
    digits: 0,
    what:
      "直近20日の出来高のうち「前日より上げた日」と「高値寄りで引けた日」に振り分けられた割合を、出来高の増え方で強めたもの。",
    how: "90以上なら全銘柄の上位10%。出来高を伴って引けにかけて買われている日が多いほど高い。",
    compare: "その日の全銘柄（終値100円以上）の中での順位（0〜100）。",
    evidence: "これまでの検証では、その後のリターンとの関係は有意ではなかった。「買い集め」シグナルの実績は検証画面を参照。",
    read: (v) => ({ text: v >= 90 ? "強い（上位10%）" : v >= 70 ? "やや強い" : v >= 30 ? "普通" : "売り優勢", tone: "normal" }),
  },
  {
    key: "power",
    label: "POWER",
    short: "POWER",
    digits: 2,
    what: "直近20日の値動きが、その銘柄の普段の値動き（1日のばらつき×√20）の何倍か。",
    how: "+2以上は普段ならまず起きない上げ幅（σ単位）。−2以下は同じく大きな下げ。",
    compare: "自分自身の普段の値動き。レーダーでは全銘柄の中での位置に直して描いている。",
    evidence: "これまでの検証では、その後のリターンとの関係は有意ではなかった。",
    read: (v) => ({ text: v >= 2 ? "急上昇" : v >= 1 ? "上昇" : v > -1 ? "普段並み" : v > -2 ? "下落" : "急落", tone: "normal" }),
  },
  {
    key: "stab",
    label: "安定度",
    short: "安定度",
    digits: 0,
    what: "直近20日の値動きの大きさが、その銘柄の過去1年の中でどれだけ穏やかか。",
    how: "100 = 過去1年で最も落ち着いている、0 = 最も荒れている。低いと1日の値幅が大きく、想定外の損失が出やすい。",
    compare: "自分自身の過去1年。",
    evidence:
      "6指標の中で唯一、どの期間で測っても「落ち着いている銘柄ほど、その後がやや良い」向きだった。ただし有意ではない。",
    read: (v) => ({ text: v <= 20 ? "変動拡大に注意" : v < 40 ? "やや荒い" : v < 70 ? "普段並み" : "落ち着いている", tone: v <= 20 ? "warn" : "normal" }),
  },
  {
    key: "rsi",
    label: "RSI（14日）",
    short: "RSI",
    digits: 0,
    what: "直近14日の値上がり幅と値下がり幅の比率（0〜100）。",
    how: "70以上は買われすぎ、30以下は売られすぎの目安。上昇トレンド中は70台が続くこともある。",
    compare: "自分自身の値動き。",
    evidence: "これまでの検証では、その後のリターンとの関係は有意ではなかった。",
    read: (v) => ({ text: v >= 80 ? "過熱" : v >= 70 ? "買われすぎ" : v >= 50 ? "強含み" : v > 30 ? "弱含み" : "売られすぎ", tone: v >= 80 ? "warn" : "normal" }),
  },
];

// Object.fromEntries は Chrome 73 以降。ビルド対象（chrome70）に合わせて使わない
export const METRIC_BY_KEY: Record<string, MetricInfo> = METRICS.reduce(
  (acc, m) => ({ ...acc, [m.key]: m }),
  {} as Record<string, MetricInfo>,
);

export const VERIFY_LABEL: Record<string, string> = {
  score: "モメンタム度",
  sr: "SR",
  power: "POWER",
  acc: "買い集め",
  stab: "安定度",
  rsi: "RSI",
};
