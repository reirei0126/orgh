// 実行中プロセスのライブログ(mission-logイベント)の一元バッファ。
//
// 目的は2つ(Codexレビューr2指摘):
// 1. 新規起動時、詳細画面へ遷移する前にemitされたplanning出力が失われない
//    ようにする(購読はアプリ起動時に1回だけ開始し、画面はここから読む)
// 2. 行数をミッションごとに上限で打ち切り、長時間ミッションでメモリとDOMが
//    無制限に成長しないようにする(完全なログはledger/artifact側が真実源)
import { onMissionLog } from "./api";

const MAX_LINES = 2000;

type Listener = () => void;

const buffers = new Map<string, string[]>();
const listeners = new Map<string, Set<Listener>>();
const pendingListeners = new Set<Listener>();
// ORGH_MISSION_ID確定前(missionId: null)の行(planning出力)。
// 確定行 `ORGH_MISSION_ID=<id>` を含むログ行を受けたときに、そのidの
// バッファへ移す。mission-updatedを引き取り契機にすると、planning中に
// 無関係なバックグラウンドミッションが終了しただけで別ミッションへ
// 誤帰属する(Codexレビューr3指摘)
let pendingNullLines: string[] = [];
let started = false;

function adoptPending(missionId: string): void {
  if (pendingNullLines.length === 0) return;
  const buf = buffers.get(missionId) ?? [];
  buffers.set(missionId, [...pendingNullLines, ...buf].slice(-MAX_LINES));
  pendingNullLines = [];
  pendingListeners.forEach((l) => l());
}

function notify(missionId: string): void {
  listeners.get(missionId)?.forEach((l) => l());
}

/** アプリ起動時に1回だけ呼ぶ(App.tsx)。 */
export function startLogStore(): void {
  if (started) return;
  started = true;
  void onMissionLog((p) => {
    if (p.missionId === null) {
      pendingNullLines.push(p.line);
      if (pendingNullLines.length > MAX_LINES) pendingNullLines.shift();
      pendingListeners.forEach((l) => l());
      return;
    }
    // 確定行そのもの(Rust側がid付きで流し直すORGH_MISSION_ID行)が、
    // 直前まで貯めたplanning出力の帰属先を一意に示す
    if (p.line.startsWith("ORGH_MISSION_ID=")) {
      adoptPending(p.missionId);
    }
    const buf = buffers.get(p.missionId) ?? [];
    buf.push(p.line);
    if (buf.length > MAX_LINES) buf.splice(0, buf.length - MAX_LINES);
    buffers.set(p.missionId, buf);
    notify(p.missionId);
  });
}

export function getLiveLines(missionId: string): string[] {
  return buffers.get(missionId) ?? [];
}

/** ORGH_MISSION_ID確定前のplanning出力(新規起動画面の進行表示用)。 */
export function getPendingLines(): string[] {
  return pendingNullLines;
}

/** 新規起動の直前に呼ぶ。前回の起動失敗時に残ったplanning出力を持ち越すと、
 * 次の正常起動の確定行が旧失敗ログごと新ミッションへ誤帰属するため。 */
export function clearPendingLines(): void {
  pendingNullLines = [];
  pendingListeners.forEach((l) => l());
}

export function subscribeLiveLog(missionId: string, listener: Listener): () => void {
  let set = listeners.get(missionId);
  if (!set) {
    set = new Set();
    listeners.set(missionId, set);
  }
  set.add(listener);
  return () => {
    set.delete(listener);
  };
}

export function subscribePendingLog(listener: Listener): () => void {
  pendingListeners.add(listener);
  return () => {
    pendingListeners.delete(listener);
  };
}
