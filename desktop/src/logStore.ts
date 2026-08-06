// 実行中プロセスのライブログ(mission-logイベント)の一元バッファ。
//
// 目的は2つ(Codexレビューr2指摘):
// 1. 新規起動時、詳細画面へ遷移する前にemitされたplanning出力が失われない
//    ようにする(購読はアプリ起動時に1回だけ開始し、画面はここから読む)
// 2. 行数をミッションごとに上限で打ち切り、長時間ミッションでメモリとDOMが
//    無制限に成長しないようにする(完全なログはledger/artifact側が真実源)
import { onMissionLog, onMissionUpdated } from "./api";

const MAX_LINES = 2000;

type Listener = () => void;

const buffers = new Map<string, string[]>();
const listeners = new Map<string, Set<Listener>>();
// ORGH_MISSION_ID確定前(missionId: null)の行。確定を知らせる最初の
// mission-updatedで該当ミッションのバッファへ移す
let pendingNullLines: string[] = [];
let started = false;

function adoptPending(missionId: string): void {
  if (pendingNullLines.length === 0) return;
  const buf = buffers.get(missionId) ?? [];
  buffers.set(missionId, [...pendingNullLines, ...buf].slice(-MAX_LINES));
  pendingNullLines = [];
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
      return;
    }
    adoptPending(p.missionId);
    const buf = buffers.get(p.missionId) ?? [];
    buf.push(p.line);
    if (buf.length > MAX_LINES) buf.splice(0, buf.length - MAX_LINES);
    buffers.set(p.missionId, buf);
    notify(p.missionId);
  });
  void onMissionUpdated((p) => {
    if (pendingNullLines.length > 0) {
      adoptPending(p.missionId);
      notify(p.missionId);
    }
  });
}

export function getLiveLines(missionId: string): string[] {
  return buffers.get(missionId) ?? [];
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
