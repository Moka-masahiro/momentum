/**
 * モメンタムの定時実行の「時計」（Google Apps Script。Google のサーバーで動くので PC は要らない）。
 *
 * GitHub 自身の定時実行（schedule）は 2026-08-27 ごろから5〜7時間遅れて届くので、決まった時刻に
 * GitHub Actions の daily を workflow_dispatch（auto=true）で頼む役だけをここで持つ。
 * 何をするか（全体を作り直す・開示だけ取り直す・何もしない）は GitHub 側（pipeline/should_build.py）が
 * 届いた時刻で決める。ここは時刻が来たら頼むだけ。
 *
 * 準備（README の「外部のタイマー」の節）:
 *   1. スクリプト プロパティ GITHUB_TOKEN に、momentum リポジトリだけに絞った
 *      fine-grained personal access token（Actions: Read and write）を入れる
 *   2. setup を1回実行する（5分ごとに tick を動かすトリガーを作る）
 *   3. testDispatch を実行し、GitHub の Actions に daily の実行が1件増えるのを確かめる
 */

const REPO = 'Moka-masahiro/momentum';
const WORKFLOW = 'daily.yml';
// 平日に頼む時刻（日本時間）。daily.yml の cron と同じ。
//   11:53 前場の引け後・17:17 大引け後（全体の更新）、18:47 その予備と開示だけの更新、
//   20:17・翌朝 08:37 開示だけの更新（夕方の更新のあとに出た開示を拾う。2026-10-10 に追加）
const SLOTS = ['08:37', '11:53', '17:17', '18:47', '20:17'];
const RETRY_MINUTES = 30;                   // 頼めなかったときは、この間は5分ごとにやり直す

/** 5分ごとに動く。平日の頼む時刻を過ぎていて、その回をまだ頼んでいなければ頼む */
function tick() {
  const now = new Date();
  const day = Utilities.formatDate(now, 'Asia/Tokyo', 'yyyy-MM-dd');
  const hm = Utilities.formatDate(now, 'Asia/Tokyo', 'HH:mm');
  if (isWeekend_(day)) return;
  const props = PropertiesService.getScriptProperties();
  for (const slot of SLOTS) {
    const key = 'sent ' + day + ' ' + slot;
    const late = minutes_(hm) - minutes_(slot);
    if (late < 0 || late >= RETRY_MINUTES || props.getProperty(key)) continue;
    dispatch_();  // 頼めなければ例外で止まり、次の tick でやり直す（失敗は Google からメールで届く）
    props.setProperty(key, hm);
    forgetOtherDays_(props, day);
  }
}

/** 最初に1回だけ実行する: tick を5分ごとに動かすトリガーを作る（何度実行しても1つだけになる） */
function setup() {
  for (const t of ScriptApp.getProjectTriggers()) {
    if (t.getHandlerFunction() === 'tick') ScriptApp.deleteTrigger(t);
  }
  ScriptApp.newTrigger('tick').timeBased().everyMinutes(5).create();
  Logger.log('5分ごとのトリガーを作りました');
}

/** トークンの確認用に、いま1回だけ頼む。GitHub 側は時刻を見て、作る必要が無ければすぐに終わる */
function testDispatch() {
  Logger.log(dispatch_() || '（応答の中身なし）');
  Logger.log('頼みました。GitHub の Actions に daily の実行（workflow_dispatch）が1件増えていれば成功です');
}

function dispatch_() {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('スクリプト プロパティ GITHUB_TOKEN がありません');
  const res = UrlFetchApp.fetch(
    'https://api.github.com/repos/' + REPO + '/actions/workflows/' + WORKFLOW + '/dispatches', {
      method: 'post',
      contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' },
      payload: JSON.stringify({ ref: 'main', inputs: { auto: 'true' } }),
      muteHttpExceptions: true,
    });
  const code = res.getResponseCode();
  // 成功は 200（実行の URL が返る）か 204（以前の仕様）。401 はトークンの期限切れ・取り消し、
  // 403・404 はトークンの権限（Actions: Read and write）かリポジトリの選び方の誤り
  if (code !== 200 && code !== 204) {
    throw new Error('GitHub に頼めませんでした: HTTP ' + code + ' ' + res.getContentText().slice(0, 300));
  }
  return res.getContentText();  // 200 のときは起動した実行の URL（html_url）が入っている
}

function isWeekend_(day) {
  const [y, m, d] = day.split('-').map(Number);
  const dow = new Date(Date.UTC(y, m - 1, d)).getUTCDay();  // 0 = 日曜
  return dow === 0 || dow === 6;
}

function minutes_(hm) {
  const [h, m] = hm.split(':').map(Number);
  return h * 60 + m;
}

/** 頼んだ記録は当日の分だけ残す */
function forgetOtherDays_(props, day) {
  for (const key of props.getKeys()) {
    if (key.startsWith('sent ') && !key.startsWith('sent ' + day)) props.deleteProperty(key);
  }
}
