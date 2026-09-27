"""モメンタム分析（GitHub Actions で毎日動かし、静的なデータファイルを書き出す）。

    data.py        取得した日足を「日付×銘柄」の表に整える（ゴミ値の除去・分割段差の補正）
    indicators.py  モメンタム度・SR・POWER・買い集め・安定度・RSI
    signals.py     シグナルの検知と、発動後の値動き（市場平均との差）
    report.py      1銘柄のテクニカル整理（時間軸・局面・節目）
    validate.py    指標が将来のリターンを説明できていたかの検証
    compute.py     上記をまとめて計算する
    export.py      画面が読むデータ（JSON）に組み立てる
"""
