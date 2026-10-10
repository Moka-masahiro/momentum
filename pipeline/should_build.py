"""自動の実行で、データを作り直すかどうかを決める（.github/workflows/daily.yml の check ジョブが使う）。

自動の実行は2通りある。外部のタイマー（timer/timer.gs。Google Apps Script）が平日の決まった時刻に
頼む workflow_dispatch（auto=true）と、GitHub 自身の定時実行（schedule）。GitHub の定時実行は
2026-08-27 ごろから5〜7時間遅れて届くので予備にしてあり、どの回の分かは予定の時刻ではなく
届いた時刻で決める（遅れて届いた昼の分が、夕方の回の予備になる）。

全体の更新（株価を取り直す。full）
- 平日 11:30〜12:30（前場の引け後）: 今日 11:30 以降に作ったデータがまだ無ければ作る
- 平日 17:00〜24:00（大引け後）: 今日 17:00 以降に作ったデータがまだ無ければ作る
- それ以外（朝・取引時間中・夜中・土日）: 作らない。夜中に遅れて届いた定時実行が、
  前日の分を作り直していた（2026-09-30 01:07）
- 平日の休場日（祝日・年末年始。market_days.py）: 作らない。タイマーは祝日を知らずに頼んでくるので、
  以前は中身が前の取引日と同じデータを1日に2回作っていた（年に17日ほど）。ただし前の取引日の
  大引けのデータがまだ出来ていなければ、上の時間帯に限って作る

開示だけの更新（株価は大引け後に取得した分を使い回し、適時開示だけ取り直す。light）
全体の更新をしないと決まったときに、次をすべて満たせば行う（夕方の更新のあとに出た開示を、夜と翌朝に拾うため）。
- 取引日の 9:00〜17:00 ではない（その間は昼と夕方の全体の更新に任せる）
- 公開中のデータが、直近の大引けのもの（古いデータに新しい時刻を付けて、更新が届いたように見せない）
- そのときに取得した結果が残してある（実行記録の kept。build.py --keep が Actions のキャッシュに置く名前）
- 新しい開示が出ている見込みがある: 取引日の 8:00 以降は前の公開から10分以上、それより前と休場日は
  前の取引日の分をまだ取り直していないときだけ（開示が出るのは取引日の 8:00〜24:00）

手で動かした分（Run workflow。auto を付けない）は、いつでも作り直す（light を付ければ開示だけ。
取得した結果が残っていなければ、何も作らずに失敗で終える）。
全体の更新の判定そのものに失敗したときは、作る側に倒す（ここで止まると手動の実行まで動かなくなる）。
開示だけの更新は逆に、判定に失敗したら行わない。

    git show FETCH_HEAD:pipeline/last_run.json | python3 pipeline/should_build.py
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import market_days

JST = timezone(timedelta(hours=9))
AM = ("11:30", "12:30")   # 前場の引け後（build.py の SESSION_AM と同じ）
CLOSE_FROM = "17:00"      # 大引け後の回。JPX の信用残・品貸料（16時ごろ公表）がそろってから
LIGHT_OFF = ("09:00", "17:00")       # 取引日のこの間は、開示だけの更新をしない
TDNET_FROM = "08:00"                 # 適時開示が出始める時刻（実測 2026-09-08〜10-09 で最も早い開示は 08:00）
LIGHT_GAP = timedelta(minutes=10)    # 公開した直後に重ねて届いた分では取り直さない


def decide(now: datetime, built: str, manual: bool) -> tuple[bool, str]:
    """全体の更新をするか。(作るか, 理由)。now は日本時間、built は last_run.json の built（"YYYY-MM-DD HH:MM"）。"""
    if manual:
        return True, "手動の実行"
    if now.weekday() >= 5:
        return False, "土日"
    day, hm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    if AM[0] <= hm < AM[1]:
        since = f"{day} {AM[0]}"
    elif hm >= CLOSE_FROM:
        since = f"{day} {CLOSE_FROM}"
    else:
        return False, f"{hm} は前場の引け後・大引け後のどちらの回の時間帯でもない"
    if not market_days.is_trading_day(now.date()):
        prev = market_days.previous_trading_day(now.date())
        if built >= f"{prev} {CLOSE_FROM}":
            return False, f"休場日（前の取引日 {prev} の大引けのデータは公開済み）"
        return True, f"休場日だが、前の取引日（{prev}）の大引けのデータがまだ無い（最後は {built or '不明'}）"
    if built >= since:
        return False, f"{since} 以降に作ったデータが公開済み（{built}）"
    return True, f"{since} 以降に作ったデータがまだ無い（最後は {built or '不明'}）"


def light(now: datetime, last: dict) -> tuple[bool, str]:
    """開示だけ取り直すか。(取り直すか, 理由)。last は last_run.json の中身。"""
    day, hm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    trading = market_days.is_trading_day(now.date())
    if trading and LIGHT_OFF[0] <= hm < LIGHT_OFF[1]:
        return False, "取引日の 9:00〜17:00 は取り直さない"
    prev = str(market_days.previous_trading_day(now.date()))
    want = day if trading and hm >= CLOSE_FROM else prev
    if last.get("session") != "close" or last.get("as_of") != want:
        return False, f"{want} の大引けのデータが公開されていない"
    if not kept_name(last):
        return False, "そのときに取得した結果が残っていない"
    published = max(last.get("built") or "", (last.get("refreshed") or {}).get("at") or "")
    if not published:
        return False, "前の公開の時刻が分からない"
    if (not trading or hm < TDNET_FROM) and published[:10] > prev:
        return False, f"{prev} までの開示は取り直し済み（{published}）"
    if now - datetime.strptime(published, "%Y-%m-%d %H:%M").replace(tzinfo=JST) < LIGHT_GAP:
        return False, f"公開したばかり（{published}）"
    return True, f"前の公開（{published}）より後の開示を取り直す"


def plan(now: datetime, last: dict, manual: bool, want_light: bool = False) -> tuple[str, str]:
    """(full = 全体の更新 / light = 開示だけの更新 / skip = 何もしない / error = 頼まれたことができない, 理由)"""
    if manual and want_light:
        if not kept_name(last):
            return "error", "開示だけ取り直すための取得結果が残っていません。先に全体の更新（light を外した Run workflow）を行ってください"
        return "light", "手動の実行（開示だけ）"
    go, why = decide(now, last.get("built") or "", manual)
    if go:
        return "full", why
    try:
        ok, why_light = light(now, last)
    except Exception as e:   # 全体の更新とは逆に、判定できなければ行わない（株価は変わらないので急がない）
        ok, why_light = False, f"判定に失敗（{type(e).__name__}: {e}）"
    return ("light", why_light) if ok else ("skip", f"{why}／開示だけの更新: {why_light}")


def kept_key(built: str) -> str:
    """その回に取得した結果を Actions のキャッシュに置くときの名前（"2026-10-09 17:25" → "kept-2026-10-09-17-25"）。
    build.py --keep が実行記録の kept に書き、開示だけの更新はその名前で取り出す。"""
    return "kept-" + re.sub(r"[^0-9]+", "-", built).strip("-")


def kept_name(last: dict) -> str | None:
    """実行記録にある、残した取得結果の名前。kept_key の形でなければ、無いものとして扱う。"""
    name = last.get("kept")
    return name if isinstance(name, str) and re.fullmatch(r"kept-[0-9-]+", name) else None


def main() -> int:
    try:
        last = json.loads(sys.stdin.read() or "{}")
        last = last if isinstance(last, dict) else {}
    except ValueError:
        last = {}   # 記録が読めなければ、作る側に倒す
    built = last.get("built") or ""
    event, auto = os.environ.get("EVENT", ""), os.environ.get("AUTO", "")
    now = datetime.now(JST)
    try:
        mode, why = plan(now, last, manual=event == "workflow_dispatch" and auto != "true",
                         want_light=os.environ.get("LIGHT", "") == "true")
    except Exception as e:   # 暦の計算などで想定外のことが起きても、更新を止めない
        mode, why = "full", f"判定に失敗したので作る（{type(e).__name__}: {e}）"
    words = {"full": "作る", "light": "開示だけ取り直す", "skip": "作らない", "error": "できない"}[mode]
    print(f"event={event} cron={os.environ.get('CRON', '')} auto={auto} now={now:%Y-%m-%d %H:%M} "
          f"built={built} → {words}: {why}")
    if mode == "error":
        return 1    # check ジョブが失敗で終わり、build は動かない
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"mode={mode}\n")
            if mode == "light":
                f.write(f"kept={kept_name(last)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
