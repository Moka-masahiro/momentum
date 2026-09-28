/** 画面が読むデータの型（pipeline/momentum/export.py が書き出すものと対応） */

export type Rank = "S" | "A" | "B" | "C" | "D";

/** 値動きの理由（pipeline/momentum/reasons.py）。目立って動いた日だけに付く */
export type Why = "news" | "supply" | "market" | "unknown";

export interface Series {
  dates: string[];
  values: (number | null)[];
}

export interface StockRow {
  code: string;
  name: string | null;
  segment: string | null;
  sector33: string | null;
  close: number | null;
  chg1: number | null;
  chg5: number | null;
  chg20: number | null;
  chg60: number | null;
  score: number | null;
  rank: Rank | null;
  score_d1: number | null;
  score_d5: number | null;
  score_d20: number | null;
  position: number | null;
  universe: number;
  turnover20: number | null;
  liquid: boolean;
  traded_today: boolean;
  last_date: string | null;
  signals_today: string[];
  base?: boolean;       // 終値100円以上（ランキングの母集団）
  t?: number | null;    // モメンタム度の元になる合成z値（同点のときの並び順に使う）
  missing?: boolean;
  why?: Why | null;         // 値動きの理由（シグナル一覧では、その日の理由に置き換える）
  why_text?: string | null; // 短い文言（開示の要約・手がかり）
  idio?: number | null;     // 業種の中央値との差（%）
  vr?: number | null;       // 出来高 ÷ 直前20日平均
}

export interface Disclosure {
  time: string;             // "2026-09-25 08:30"
  title: string;
  category: string;         // 決算・業績修正・増資・売出し…
  kind: "news" | "supply" | "routine";
  url: string | null;       // TDnet の PDF（31日で消える）
  day: string | null;       // その開示が効いた取引日（null = まだ来ていない）
  ret?: number | null;      // その日の騰落率（%）
  idio?: number | null;     // その日の業種の中央値との差（%）
}

export interface Reason {
  date: string;
  label: Why | null;
  text: string | null;
  notable: boolean;         // 目立って動いたか
  checked: boolean;         // 開示を確かめられたか（取れなかった日を含むと false）
  ret: number | null;
  idio: number | null;
  z: number | null;         // 業種との差 ÷ 普段のばらつき
  vr: number | null;
  sector: string | null;
  sector_ret: number | null;
  market_ret: number | null;
  disclosures: Disclosure[];                // 判定の窓（前の取引日の引け後〜当日の引け）の開示
  clues: { key: string; text: string }[];   // 需給の手がかり
  short: { now: number; prev: number; change: number; holders: number; date: string } | null;
  premium: { rate: number; max: number | null; date: string | null } | null;
  flags: string[];
  margin?: Margin | null;   // 全銘柄の信用残（JPX。2026-09-28 から毎日。古いデータには無い）
}

/** 信用残（株数）。date は申込日（最新日の前の取引日）。ratio は信用倍率＝買い残÷売り残 */
export interface Margin {
  date: string | null;
  buy: number;
  buy_chg: number | null;
  buy_ratio: number | null;   // 上場株式数に対する%
  sell: number;
  sell_chg: number | null;
  sell_ratio: number | null;
  ratio: number | null;
  buy_days: number | null;    // 買い残が直前20日平均の出来高の何日分か
  sell_days: number | null;
}

export interface SourceStatus {
  ok: boolean;
  date: string | null;
  error: string | null;
}

export interface ReasonStatus {
  date: string;
  disclosures: { ok: boolean; count: number; latest: string | null; days_failed: number; error: string | null };
  short: SourceStatus;
  flags: SourceStatus;
  premium: SourceStatus;
  margin?: SourceStatus;
  counts: Record<Why, number>;
  unchecked: number;
}

export interface MoversResponse {
  as_of: string;
  status: ReasonStatus | null;
  items: StockRow[];        // 理由の付いた銘柄（業種との差の大きい順）
}

export interface IndexSummary {
  score: number | null;
  rank: Rank | null;
  delta5: number | null;
  close: number | null;
  change_pct: number | null;
  date: string;
}

export interface SegmentSummary {
  name: string;
  median: number | null;
  rank: Rank | null;
  delta5: number | null;
  count: number;
}

export interface Breadth {
  b_plus: number | null;
  s_share: number | null;
  count: number;
  b_plus_percentile: number | null;
}

export interface SignalTypeCount {
  key: string;
  label: string;
  tone: "up" | "warn";
  count: number;
  excess20: number | null;
  win20: number | null;
}

export interface Home {
  as_of: string;
  computed_at: string;
  universe: number;
  market: {
    nikkei: IndexSummary | null;
    segments: SegmentSummary[];
    breadth: Breadth;
    breadth_spark: Series;
  };
  ranking: StockRow[];
  verify_summary: {
    from: string | null;
    to: string | null;
    days: number | null;
    metrics: number;
    metrics_significant: number;
    signals: number;
    signals_significant: number;
  };
  signals: { total: number; liquid: number; by_type: SignalTypeCount[] };
  reasons?: ReasonStatus | null;    // 値動きの理由の材料の取得状況（古いデータには無い）
  watchlist: StockRow[];
  movers: StockRow[];               // 流動性のある銘柄のうち、理由の付いたもの（画面側で作る）
}

export interface RankingResponse {
  as_of: string;
  count: number;
  items: StockRow[];
}

export interface HorizonStat {
  n: number;
  ret_mean: number | null;
  excess_mean: number | null;
  excess_median: number | null;
  win_rate: number;
  t: number | null;
  significant: boolean;
  first_half: number | null;
  second_half: number | null;
}

export interface SignalStats {
  events: number;
  horizons: Record<string, HorizonStat | null>;
}

export interface SignalGroup {
  key: string;
  label: string;
  tone: "up" | "warn";
  rule: string;
  count: number;
  items: StockRow[];
  stats: SignalStats | null;
}

export interface SignalsResponse {
  as_of: string;
  date: string;
  dates: string[];
  total: number;
  groups: SignalGroup[];
}

export interface StockSignal {
  date: string;
  key: string;
  label: string;
  tone: "up" | "warn";
  liquid: boolean;
  entry_date: string | null;
  entry: number | null;
  now_pct: number | null;
  horizons: Record<string, { ret: number | null; excess: number | null } | null>;
}

export interface Trend {
  label: "上昇" | "下降" | "レンジ";
  ma: number;
  slope_pct: number;
  above: boolean;
}

export interface Level {
  key: string;
  label: string;
  price: number;
  note: string;
}

export interface Report {
  available: boolean;
  reason?: string;
  timeframes: { daily: Trend | null; weekly: Trend | null; monthly: Trend | null };
  alignment: string;
  phase: { label: string; text: string };
  background: {
    position: number | null;
    position_window: number;
    high: number;
    low: number;
    vol_ratio: number | null;
    vol_state: string | null;
    dev25: number | null;
    dev75: number | null;
    atr: number;
    atr_pct: number;
  };
  levels: Level[];
  range: {
    resistance: number | null;
    support: number | null;
    upside_pct: number | null;
    downside_pct: number | null;
    ratio: number | null;
  };
  alerts: { level: "warn" | "info"; text: string }[];
  conclusion: string;
}

export interface RankBucket {
  rank: Rank;
  share: number;
  horizons: Record<string, { n: number; excess_mean: number | null; win_rate: number; t: number | null;
    first_half: number | null; second_half: number | null } | null>;
}

export interface Metrics {
  score: number | null;
  rank: Rank | null;
  t: number | null;
  score_d1: number | null;
  score_d5: number | null;
  score_d20: number | null;
  sr: number | null;
  power: number | null;
  rsi: number | null;
  acc: number | null;
  stab: number | null;
  relvol: number | null;
  turnover20: number | null;
  adjusted: boolean;
}

export interface StockDetail extends StockRow {
  as_of: string;
  watched: boolean;
  reason?: Reason | null;          // 古いデータには無い
  disclosures?: Disclosure[];      // 直近30日の開示（新しい順）
  metrics: Metrics;
  radar: { key: string; label: string; value: number | null }[];
  rank_history: RankBucket | null;
  signals: StockSignal[];
  report: Report;
  chart: {
    dates: string[];
    open: (number | null)[];
    high: (number | null)[];
    low: (number | null)[];
    close: (number | null)[];
    volume: (number | null)[];
    score: (number | null)[];
    ma25: (number | null)[];
    ma75: (number | null)[];
  };
}

export interface MarketResponse {
  as_of: string;
  nikkei: (IndexSummary & { series: Series; close_series: Series }) | null;
  segments: (SegmentSummary & { series: Series })[];
  breadth: Breadth & { b_plus_series: Series; s_share_series: Series };
}

export interface IcRow {
  key: string;
  horizons: Record<string, { days: number; ic: number; t: number | null; positive_share: number;
    first_half: number | null; second_half: number | null } | null>;
}

export interface VerifyResponse {
  as_of: string;
  computed_at: string;
  first_date: string;
  last_date: string;
  half_date: string;
  ic_first_date: string | null;
  ic_last_date: string | null;
  ic_days: number | null;
  ic: IcRow[];
  ranks: RankBucket[];
  deciles: { decile: number; excess_mean: number | null; first_half: number | null; second_half: number | null }[];
  rolling_ic: { dates: string[]; series: Record<string, (number | null)[]> };
  signal_stats: Record<string, SignalStats>;
  signal_defs: { key: string; label: string; tone: string; rule: string }[];
  adjustments: { date: string; code: string; prev_close: number; close: number; ratio: number; kind: string }[];
}

export interface EngineStatus {
  status: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  as_of: string | null;
  computed_at: string | null;
  elapsed_sec: number | null;
}
