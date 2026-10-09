import { Component, useEffect, useState, type ReactNode } from "react";
import { invalidate, isUnlocked, onLocked } from "./data";
import { GuideMenu, GuideRunner, type Tour } from "./components/Guide";
import Lock from "./components/Lock";
import SearchSheet from "./components/SearchSheet";
import { Icon, Sheet } from "./components/ui";
import Disclosures from "./pages/Disclosures";
import Home from "./pages/Home";
import Margin from "./pages/Margin";
import Market from "./pages/Market";
import Movers from "./pages/Movers";
import Ranking from "./pages/Ranking";
import Settings from "./pages/Settings";
import Signals from "./pages/Signals";
import Stock from "./pages/Stock";
import Verify from "./pages/Verify";
import Watchlist from "./pages/Watchlist";
import { go, useRoute } from "./router";

export default function App() {
  const [locked, setLocked] = useState<boolean | null>(null); // null = 確認中
  useEffect(() => {
    isUnlocked()
      .then((ok) => setLocked(!ok))
      .catch(() => setLocked(false)); // 通信エラーなどは各画面で表示する
    return onLocked(() => setLocked(true));
  }, []);

  if (locked === null) {
    return (
      <main className="app">
        <div className="card mt-6"><div className="loading-bar mb-3" /><div className="t-2 text-sm">読み込み中…</div></div>
      </main>
    );
  }
  if (locked) {
    return <Lock onUnlocked={() => { invalidate(); setLocked(false); }} />;
  }
  return (
    <Boundary>
      <Main />
    </Boundary>
  );
}

/** 想定外のエラーで画面が真っ白にならないようにする */
class Boundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="app">
        <div className="card mt-6" role="alert">
          <div className="font-bold t-warn">表示に失敗しました</div>
          <p className="t-2 text-sm mt-2 break-all">{this.state.error.message}</p>
          <p className="note mt-2">データの更新直後に、古い画面と新しいデータが混ざると起きることがあります。</p>
          <button className="btn-primary w-full mt-3" onClick={() => location.reload()}>再読み込み</button>
        </div>
      </main>
    );
  }
}

function Main() {
  const [page, arg] = useRoute();
  const [search, setSearch] = useState(false);
  const [guideMenu, setGuideMenu] = useState(false);
  const [tour, setTour] = useState<Tour | null>(null);

  const startTour = (t: Tour) => {
    setGuideMenu(false);
    setSearch(false);
    setTour(t);
  };

  let view;
  switch (page) {
    case undefined:
      view = <Home onGuide={() => setGuideMenu(true)} />;
      break;
    case "stock":
      view = arg ? <Stock key={arg} code={arg} /> : <NotFound />;
      break;
    case "ranking":
      view = <Ranking />;
      break;
    case "signals":
      view = <Signals key={arg ?? "latest"} date={arg} />;
      break;
    case "market":
      view = <Market />;
      break;
    case "movers":
      view = <Movers />;
      break;
    case "margin":
      view = <Margin />;
      break;
    case "disclosures":
      view = <Disclosures />;
      break;
    case "verify":
      view = <Verify />;
      break;
    case "watchlist":
      view = <Watchlist />;
      break;
    case "settings":
      view = <Settings onStartTour={startTour} />;
      break;
    default:
      view = <NotFound />;
  }

  return (
    <>
      <main className="app">{view}</main>
      <nav className="bottom-bar" aria-label="メニュー">
        <div className="bottom-inner">
          <button className="round-btn" onClick={() => go("")} aria-label="ホーム"><Icon name="home" /></button>
          <button className="search-pill" data-guide="search" onClick={() => setSearch(true)}>
            <Icon name="search" size={18} />
            銘柄検索
          </button>
          <button className={`round-btn ${tour ? "on" : ""}`} onClick={() => setGuideMenu(true)} aria-label="使い方ガイド">
            <Icon name="guide" />
          </button>
        </div>
      </nav>
      <SearchSheet open={search} onClose={() => setSearch(false)} />
      <Sheet open={guideMenu} onClose={() => setGuideMenu(false)} title="使い方ガイド">
        <p className="note mb-3">画面の該当する場所を枠で示しながら、順番に説明します。</p>
        <GuideMenu onStart={startTour} />
      </Sheet>
      {tour && <GuideRunner key={tour.key} tour={tour} onClose={() => setTour(null)} />}
    </>
  );
}

function NotFound() {
  return (
    <div className="card mt-4">
      <p className="t-2">ページが見つかりません。</p>
      <button className="btn-ghost mt-3" onClick={() => go("")}>ホームへ</button>
    </div>
  );
}
