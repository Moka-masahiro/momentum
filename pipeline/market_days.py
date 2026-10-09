"""東証の取引日（休場日）と、次の更新の予定。標準ライブラリだけで動く。

休場日は、土日・国民の祝日（振替休日と国民の休日を含む）・年末年始（12/31〜1/3）。
祝日は法律の規則から計算する（2022年以降の規則。それより前はオリンピックの特例などがあり合わない）。
春分・秋分の日は 1980〜2099年に使える近似式で、正式には前年2月に官報で決まる。内閣府の一覧
（2022〜2027年）と一致することを tests で確かめている。

祝日のライブラリを使わないのは、check ジョブを pip なしで動かすためと、合言葉を扱うビルドに
第三者のパッケージを増やさないため。

誤って取引日を休場日とみなすと、その日の自動の更新がすべて止まる。規則に無い臨時の休場は
ここでは分からないので、取引日とみなす（その日は当日の日足が無いので、夕方の実行は公開せずに終わる）。
"""
from datetime import date, datetime, timedelta

# データが公開される予定の時刻（外部のタイマーが 11:53・17:17 に起動し、作るのに8分ほどかかる）
PUBLISH = ((12, 5), (17, 30))


def _nth_monday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(7 - first.weekday()) % 7 + 7 * (n - 1))


def _equinox(year: int, spring: bool) -> int:
    k = year - 1980
    return int((20.8431 if spring else 23.2488) + 0.242194 * k - k // 4)


def national_holidays(year: int) -> set[date]:
    """その年の国民の祝日と休日（振替休日・国民の休日を含む）。"""
    named = {
        date(year, 1, 1), _nth_monday(year, 1, 2), date(year, 2, 11), date(year, 2, 23),
        date(year, 3, _equinox(year, True)), date(year, 4, 29), date(year, 5, 3), date(year, 5, 4),
        date(year, 5, 5), _nth_monday(year, 7, 3), date(year, 8, 11), _nth_monday(year, 9, 3),
        date(year, 9, _equinox(year, False)), _nth_monday(year, 10, 2), date(year, 11, 3), date(year, 11, 23),
    }
    days = set(named)
    for d in named:
        if d.weekday() == 6:                      # 振替休日: 祝日が日曜なら、その後の最初の祝日でない日
            s = d + timedelta(days=1)
            while s in named:
                s += timedelta(days=1)
            days.add(s)
        mid = d + timedelta(days=1)               # 国民の休日: 前後を祝日に挟まれた平日（2026-09-22 など）
        if mid + timedelta(days=1) in named and mid not in named and mid.weekday() != 6:
            days.add(mid)
    return days


def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5 or (d.month, d.day) in ((12, 31), (1, 1), (1, 2), (1, 3)):
        return False
    return d not in national_holidays(d.year)


def previous_trading_day(d: date) -> date:
    """d より前の、直近の取引日。"""
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def next_trading_day(d: date) -> date:
    """d より後の、直近の取引日。"""
    d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def premium_days(trade: date) -> int:
    """その約定日の逆日歩（品貸料）が何日分か。

    受渡しは2取引日後。その日の受渡しから、次の取引日の約定分の受渡しまでの暦日数になる。ふだんは1日、
    水曜の約定は週末をまたいで3日、連休の前はもっと長い（2026-10-07 は祝日をまたいで4日）。
    JPX の品貸料のファイルは「1日1株あたり」と注記しているが、載っている額はこの日数分の合計だった
    （両日に逆日歩のあった348銘柄のうち297銘柄で、10/7 の額が 10/8 のちょうど4倍）。
    """
    def settle(d: date) -> date:
        return next_trading_day(next_trading_day(d))
    return (settle(next_trading_day(trade)) - settle(trade)).days


def next_update(now: datetime) -> datetime:
    """いま作ったデータの次に、データが公開される予定の時刻（取引日の 12:05 と 17:30）。

    30分以内の回は数えない（昼の実行が 12:01 に終わったとき、自分自身の 12:05 を次の予定にしないため）。
    """
    after = now + timedelta(minutes=30)
    d = now.date()
    while True:
        if is_trading_day(d):
            for h, m in PUBLISH:
                t = now.replace(year=d.year, month=d.month, day=d.day, hour=h, minute=m, second=0, microsecond=0)
                if t > after:
                    return t
        d += timedelta(days=1)
