import { api, paths, useData } from "../data";
import { Card, Delta, ErrorBox, Icon, Loading, RankBadge } from "../components/ui";
import { num, yen } from "../format";
import { back, go } from "../router";
import type { Home } from "../types";

export default function Watchlist() {
  const { data, error, loading, reload } = useData<Home>(paths.home, api.home);
  const rows = data?.watchlist ?? [];
  return (
    <div>
      <div className="top-bar">
        <button className="icon-btn" onClick={back} aria-label="戻る"><Icon name="back" /></button>
        <h1>ウォッチリスト</h1>
        <span />
      </div>
      {loading && !data && <Loading />}
      {error && !data && <ErrorBox message={error} onRetry={reload} />}
      {data && (
        <Card sub="この端末の中に保存しています（外には送りません）。追加・削除は銘柄詳細の ☆ から。まとめて追加は設定から">
          <div className="list-head" style={{ gridTemplateColumns: "1fr 70px 52px 52px 34px" }}>
            <span>銘柄名</span><span className="text-right">株価</span><span className="text-right">前日比</span><span className="text-right">1か月</span><span className="text-center">ランク</span>
          </div>
          {rows.map((r) =>
            r.missing ? (
              <div key={r.code} className="list-row"><span className="t-3 text-[12px]">{r.code} 日足なし</span></div>
            ) : (
              <button key={r.code} className="list-row" style={{ gridTemplateColumns: "1fr 70px 52px 52px 34px" }} onClick={() => go(`stock/${r.code}`)}>
                <span className="list-name">
                  <b>{r.name}</b>
                  <small>{r.code} · モメンタム度 {num(r.score)}{r.position ? ` · ${num(r.position)}位` : ""}</small>
                </span>
                <span className="text-right text-[13px] num">{yen(r.close)}</span>
                <span className="text-right text-[12px]"><Delta v={r.chg1} /></span>
                <span className="text-right text-[12px]"><Delta v={r.chg20} /></span>
                <span className="text-center"><RankBadge rank={r.rank} /></span>
              </button>
            ),
          )}
          {rows.length === 0 && <p className="note">まだ登録がありません。</p>}
        </Card>
      )}
    </div>
  );
}
