import { useEffect, useState } from "react";
import { api, forgetKey, invalidate } from "../data";
import { GuideMenu, type Tour } from "../components/Guide";
import { Card, Icon } from "../components/ui";
import { mdDate, mdTime, num, slashDate } from "../format";
import { back, setFlag } from "../router";
import type { ReasonStatus, SourceStatus } from "../types";
import { addMany, watchlist } from "../watch";

type Status = { built: string; prices_at: string; next: string | null; as_of: string; universe: number; stocks: number; reasons: ReasonStatus | null };

function source(s: SourceStatus | undefined, label: string) {
  if (!s) return "—";
  return s.ok ? `${label}${s.date ? `（${mdDate(s.date)}分）` : ""}` : "取得できず";
}

export default function Settings({ onStartTour }: { onStartTour: (t: Tour) => void }) {
  const [st, setSt] = useState<Status | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [added, setAdded] = useState<string | null>(null);
  const [count, setCount] = useState(() => watchlist().length);

  const load = () => {
    setErr(null);
    api.status().then(setSt).catch((e) => setErr(String(e.message ?? e)));
  };
  useEffect(load, []);

  const reload = () => {
    invalidate();
    setSt(null);
    load();
  };

  const bulkAdd = () => {
    const n = addMany(text);
    setAdded(n ? `${n} 銘柄を追加しました` : "新しく追加できる銘柄コードがありませんでした");
    setCount(watchlist().length);
    setText("");
    invalidate("home");
  };

  const forget = () => {
    if (!confirm("この端末に保存した鍵を消します。次に開くときは合言葉の入力が必要です。")) return;
    forgetKey();
    location.reload();
  };

  return (
    <div>
      <div className="top-bar">
        <button className="icon-btn" onClick={back} aria-label="戻る"><Icon name="back" /></button>
        <h1>設定・情報</h1>
        <span />
      </div>

      <Card title="データの状態">
        <table className="tbl">
          <tbody>
            <tr><td>データ日付（最新の日足）</td><td>{st ? slashDate(st.as_of) : "—"}</td></tr>
            <tr><td>株価を取得した時刻</td><td>{st?.prices_at ?? "—"}</td></tr>
            <tr><td>開示を取得した時刻</td><td>{st ? st.reasons?.disclosures.fetched ?? st.built : "—"}</td></tr>
            <tr><td>次の株価の更新の予定</td><td>{st?.next ? `${mdTime(st.next)} ごろ` : "—"}</td></tr>
            <tr><td>銘柄数（うち流動性あり）</td><td>{st ? `${num(st.stocks)}（${num(st.universe)}）` : "—"}</td></tr>
            {st && (
              <>
                <tr>
                  <td>適時開示（値動きの理由）</td>
                  <td>
                    {!st.reasons ? "作れず"
                      : st.reasons.disclosures.ok
                        ? `${num(st.reasons.disclosures.count)}件${st.reasons.disclosures.days_failed ? `（${st.reasons.disclosures.days_failed}日分取得できず）` : ""}`
                        : "取得できず"}
                  </td>
                </tr>
                <tr><td>空売り残高</td><td>{source(st.reasons?.short, "取得")}</td></tr>
                <tr><td>日々公表銘柄など</td><td>{source(st.reasons?.flags, "取得")}</td></tr>
                <tr><td>逆日歩</td><td>{source(st.reasons?.premium, "取得")}</td></tr>
                <tr><td>信用残（全銘柄）</td><td>{source(st.reasons?.margin, "取得")}</td></tr>
              </>
            )}
          </tbody>
        </table>
        {err && <p className="t-warn text-[12px] mt-2 break-all">{err}</p>}
        <p className="note mt-2">
          取引のある日の昼（12時ごろ。前場までの途中経過）と夕方（17時半ごろ）に、GitHub Actions が全銘柄の日足を
          取り直し、指標を計算してここに置き直します。夕方の更新のあとに出た開示は、夜（19時前と20時すぎ）と
          翌朝（8時40分ごろ）に開示だけ取り直して足します（株価と指標は夕方のまま）。
          PC の電源は要りません。土日・祝日・年末年始は更新しません。
          アプリを開いたままにしていても、戻ってきたときに新しいデータがあれば読み直します。
        </p>
        <button className="btn-ghost w-full mt-2" onClick={reload}>最新のデータを読み込み直す</button>
      </Card>

      <Card title="ウォッチリストをまとめて追加">
        <p className="note">
          銘柄コードを空白や改行で区切って貼り付けてください（例: 7203 6976 9432）。いまの登録は {count} 銘柄です。
          リストはこの端末の中にだけ保存されます（PC とスマホでは別々）。
        </p>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          className="tile w-full mt-2 text-[15px] t-1 outline-none"
          aria-label="銘柄コード"
        />
        <button className="btn-ghost w-full mt-2" onClick={bulkAdd} disabled={!text.trim()}>追加する</button>
        {added && <p className="text-[13px] t-accent mt-2">{added}</p>}
      </Card>

      <Card title="使い方ガイド">
        <GuideMenu onStart={onStartTour} />
        <button className="card-link mt-2" onClick={() => setFlag("m_welcome_done", false)}>ホームの「はじめに」をもう一度表示する</button>
      </Card>

      <Card title="スマホのホーム画面に置く">
        <p className="prose !text-[13px]">
          <b>Android（Chrome）</b>: 右上の「︙」→「アプリをインストール」（または「ホーム画面に追加」）。
          アドレスバーの無い、アプリと同じ全画面で開けます。
        </p>
        <p className="prose !text-[13px] mt-2">
          <b>iPhone（Safari）</b>: 共有ボタン →「ホーム画面に追加」。
        </p>
        <p className="note mt-2">一度開いたデータは端末に残るので、電波の無いところでも前回の内容は見られます。</p>
      </Card>

      <Card title="合言葉">
        <p className="note">
          合言葉から作った鍵をこの端末に保存しています。人に端末を貸すときなどは消しておけます。
          GitHub 側で合言葉を変えたときは、自動で入力画面に戻ります。
        </p>
        <button className="btn-ghost w-full mt-2" onClick={forget}>この端末から鍵を消す</button>
      </Card>

      <Card title="紹介動画のアプリとの違い">
        <ul className="note space-y-1.5 list-disc pl-4 !text-[12.5px]">
          <li><b className="t-2">PTSシグナルは無し</b> — 夜間取引のデータを無料で取れる手段が無いため</li>
          <li><b className="t-2">「AI銘柄レポート」はルールによる整理</b> — 同じデータなら同じ結果になり、APIキーも費用も要らない</li>
          <li><b className="t-2">株価とモメンタム度は上下2段</b> — 2本の縦軸で重ねると、軸の合わせ方で連動して見せられてしまうため</li>
          <li><b className="t-2">シグナルの成績は「市場平均との差」</b> — 素のリターンは相場全体の上げを含み、良く見えすぎるため</li>
          <li><b className="t-2">検証画面を追加</b> — 指標やシグナルが本当に当たっていたかを毎日計算し直して見せる</li>
        </ul>
      </Card>

      <Card title="データの出どころ">
        <ul className="note space-y-1 list-disc pl-4">
          <li>株価: yfinance（無料・非公式）の日足。全約3,700銘柄の2年分を毎回取り直す</li>
          <li>銘柄名・市場区分・業種: JPX の東証上場銘柄一覧</li>
          <li>日経平均: yfinance（^N225）</li>
          <li>株式分割による価格の段差は、値幅制限を手がかりに自動で補正（検証画面に記録）</li>
          <li>
            値動きの理由の適時開示: やのしん TDnet WEB-API（個人運営の無料API）。東証の TDnet は自動取得を禁止しているため、
            直接は取りに行かない。表題のリンク先は TDnet の PDF
          </li>
          <li>空売り残高・日々公表銘柄など・品貸料（逆日歩）: JPX の公表ファイル（毎日）</li>
          <li>全銘柄の信用残: JPX「銘柄別信用取引残高」（毎日16時・PDF）。読み取った数字は「売り残＝一般信用＋制度信用」などの足し算で検算し、合わない銘柄は使わない。制度信用倍率は、このうち制度信用の買い残÷売り残</li>
          <li>新聞報道・アナリストの格付けは使っていない（無料で自動取得してよい入手先が無いため）</li>
          <li>公開のページに置くので、データはすべて合言葉で暗号化している</li>
        </ul>
      </Card>
    </div>
  );
}
