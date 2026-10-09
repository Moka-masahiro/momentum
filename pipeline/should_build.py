"""自動の実行で、データを作り直すかどうかを決める（.github/workflows/daily.yml の check ジョブが使う）。

自動の実行は2通りある。外部のタイマー（timer/timer.gs。Google Apps Script）が平日 11:53・17:17・18:47 に
頼む workflow_dispatch（auto=true）と、GitHub 自身の定時実行（schedule）。GitHub の定時実行は
2026-08-27 ごろから5〜7時間遅れて届くので予備にしてあり、どの回の分かは予定の時刻ではなく
届いた時刻で決める（遅れて届いた昼の分が、夕方の回の予備になる）。

- 平日 11:30〜12:30（前場の引け後）: 今日 11:30 以降に作ったデータがまだ無ければ作る
- 平日 17:00〜24:00（大引け後）: 今日 17:00 以降に作ったデータがまだ無ければ作る
- それ以外（朝・取引時間中・夜中・土日）: 作らない。夜中に遅れて届いた定時実行が、
  前日の分を作り直していた（2026-09-30 01:07）
- 平日の休場日（祝日・年末年始。market_days.py）: 作らない。タイマーは祝日を知らずに頼んでくるので、
  以前は中身が前の取引日と同じデータを1日に2回作っていた（年に17日ほど）。ただし前の取引日の
  大引けのデータがまだ出来ていなければ、上の時間帯に限って作る
手で動かした分（Run workflow。auto を付けない）は、いつでも作り直す。
判定そのものに失敗したときは、作る側に倒す（ここで止まると手動の実行まで動かなくなる）。

    git show FETCH_HEAD:pipeline/last_run.json | python3 pipeline/should_build.py
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import market_days

JST = timezone(timedelta(hours=9))
AM = ("11:30", "12:30")   # 前場の引け後（build.py の SESSION_AM と同じ）
CLOSE_FROM = "17:00"      # 大引け後の回。JPX の信用残・品貸料（16時ごろ公表）がそろってから


def decide(now: datetime, built: str, manual: bool) -> tuple[bool, str]:
    """(作るか, 理由)。now は日本時間、built は last_run.json の built（"YYYY-MM-DD HH:MM"）。"""
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


def main() -> int:
    try:
        built = json.loads(sys.stdin.read() or "{}").get("built", "")
    except ValueError:
        built = ""   # 記録が読めなければ、作る側に倒す
    event, auto = os.environ.get("EVENT", ""), os.environ.get("AUTO", "")
    now = datetime.now(JST)
    try:
        go, why = decide(now, built, manual=event == "workflow_dispatch" and auto != "true")
    except Exception as e:   # 暦の計算などで想定外のことが起きても、更新を止めない
        go, why = True, f"判定に失敗したので作る（{type(e).__name__}: {e}）"
    print(f"event={event} cron={os.environ.get('CRON', '')} auto={auto} now={now:%Y-%m-%d %H:%M} "
          f"built={built} → {'作る' if go else '作らない'}: {why}")
    if not go and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write("skip=true\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
