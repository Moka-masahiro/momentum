import { useState, type FormEvent } from "react";
import { cryptoAvailable, unlock } from "../data";
import { Icon } from "./ui";

/**
 * 合言葉の入力画面。データは合言葉で暗号化してあり、鍵の計算も復号もこの端末の中で行う
 * （合言葉はどこにも送らない）。
 */
export default function Lock({ onUnlocked, message }: { onUnlocked: () => void; message?: string }) {
  const [pass, setPass] = useState("");
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(message ?? null);

  if (!cryptoAvailable()) {
    return (
      <main className="app">
        <div className="card mt-6" role="alert">
          <div className="flex items-center gap-2 t-warn font-bold"><Icon name="warn" size={18} />このブラウザでは開けません</div>
          <p className="prose !text-[13px] mt-2">
            暗号化されたデータを開くには、https のページ（GitHub Pages のアドレス）を新しめの Chrome か Safari で開いてください。
          </p>
        </div>
      </main>
    );
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!pass || busy) return;
    setBusy(true);
    setErr(null);
    try {
      await unlock(pass, remember);
      onUnlocked();
    } catch (x) {
      setErr(x instanceof Error && x.message ? x.message : "開けませんでした");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="app">
      <header className="flex items-center gap-2.5 py-3 mb-2">
        <img src="./icons/icon-192.png" width={38} height={38} alt="" style={{ borderRadius: 10 }} />
        <div className="text-[21px] font-extrabold tracking-wide">モメンタム</div>
      </header>
      <form className="card" onSubmit={submit}>
        <div className="text-[17px] font-bold">合言葉を入力</div>
        <p className="prose !text-[13px] mt-1">
          データは合言葉で暗号化してあります。GitHub に登録した合言葉を入れてください。
        </p>
        <input
          type="password"
          value={pass}
          onChange={(e) => setPass(e.target.value)}
          autoComplete="current-password"
          autoFocus
          className="tile w-full mt-3 !py-3 text-[16px] t-1 outline-none"
          aria-label="合言葉"
        />
        <label className="flex items-center gap-2 mt-3 text-[13px] t-2">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          この端末に記憶する（次回から入力不要）
        </label>
        <button className="btn-primary w-full mt-4" disabled={busy || !pass}>
          {busy ? "確認中…（数秒かかります）" : "開く"}
        </button>
        {err && <p className="t-warn text-[13px] mt-3" role="alert">{err}</p>}
      </form>
      <p className="note mt-3 px-1">
        合言葉はこの端末の外には送られません。鍵の計算も復号もこの端末の中で行います。
      </p>
    </main>
  );
}
