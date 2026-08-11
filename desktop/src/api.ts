// desktop/API.md の9コマンド + 2イベントに対応する型付きラッパ。
// Tauri内(window.__TAURI_INTERNALS__ が存在)ではinvoke()を使い、
// それ以外(素のブラウザ / VITE_MOCK=1)ではdesktop/src/mocks.tsのデータで
// 自動的にモック動作へフォールバックする。呼び出し側はどちらのモードかを
// 意識する必要がない。

import type {
  CriteriaPayload,
  DoctorReport,
  LedgerEvent,
  ListPayload,
  MissionLogEvent,
  MissionStatus,
  MissionUpdatedEvent,
  Settings,
  Verdict,
} from "./types";
import {
  MOCK_CRITERIA,
  MOCK_DOCTOR,
  MOCK_EVENTS,
  MOCK_MISSIONS,
  MOCK_SETTINGS,
  MOCK_STATUS,
} from "./mocks";

function isTauriRuntime(): boolean {
  if (import.meta.env.VITE_MOCK === "1") return false;
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

// --- モックモード: mission-log / mission-updated を模擬発火するための簡易バス ---

type Unlisten = () => void;

const mockBus = new EventTarget();

function mockEmit<T>(event: string, payload: T): void {
  mockBus.dispatchEvent(new CustomEvent(event, { detail: payload }));
}

function mockListen<T>(event: string, handler: (payload: T) => void): Unlisten {
  const listener = (e: Event) => handler((e as CustomEvent<T>).detail);
  mockBus.addEventListener(event, listener);
  return () => mockBus.removeEventListener(event, listener);
}

export function onMissionLog(handler: (payload: MissionLogEvent) => void): Promise<Unlisten> {
  if (isTauriRuntime()) {
    return import("@tauri-apps/api/event").then(({ listen }) =>
      listen<MissionLogEvent>("mission-log", (e) => handler(e.payload)),
    );
  }
  return Promise.resolve(mockListen<MissionLogEvent>("mission-log", handler));
}

export function onMissionUpdated(handler: (payload: MissionUpdatedEvent) => void): Promise<Unlisten> {
  if (isTauriRuntime()) {
    return import("@tauri-apps/api/event").then(({ listen }) =>
      listen<MissionUpdatedEvent>("mission-updated", (e) => handler(e.payload)),
    );
  }
  return Promise.resolve(mockListen<MissionUpdatedEvent>("mission-updated", handler));
}

// --- コマンド ---

async function invokeReal<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<T>(cmd, args);
}

export async function listMissions(): Promise<ListPayload> {
  if (isTauriRuntime()) return invokeReal<ListPayload>("list_missions");
  await mockDelay();
  return { missions: MOCK_MISSIONS, skipped: [] };
}

export async function missionStatus(missionId: string): Promise<MissionStatus> {
  if (isTauriRuntime()) return invokeReal<MissionStatus>("mission_status", { missionId });
  await mockDelay();
  const status = MOCK_STATUS[missionId];
  if (!status) throw new Error(`mission '${missionId}' not found`);
  return status;
}

export async function missionEvents(missionId: string, tail: number): Promise<LedgerEvent[]> {
  if (isTauriRuntime()) return invokeReal<LedgerEvent[]>("mission_events", { missionId, tail });
  await mockDelay();
  const events = MOCK_EVENTS[missionId];
  if (!events) throw new Error(`mission '${missionId}' not found`);
  return tail <= 0 ? [] : events.slice(-tail);
}

// ORGH_MISSION_ID確定前のplanningログはmissionId: nullで届き、logStoreは
// 単一のpendingバッファで保持する。確定前に2件目を起動すると両者のログが
// 混在して誤帰属するため、ID確定までアプリ全体で新規起動を直列化する
let startInFlight = false;

export async function startMission(intent: string | null, note: string | null): Promise<string> {
  if (startInFlight) {
    throw new Error("別のミッションがplanning中です。ミッションIDが確定してから再実行してください");
  }
  startInFlight = true;
  try {
    if (isTauriRuntime()) return await invokeReal<string>("start_mission", { intent, note });
    return await mockStartOrApprove(null, intent ?? note ?? "(no intent)");
  } finally {
    startInFlight = false;
  }
}

export async function approveMission(missionId: string): Promise<void> {
  if (isTauriRuntime()) return invokeReal<void>("approve_mission", { missionId });
  await mockStartOrApprove(missionId, null);
}

export async function cancelMission(missionId: string): Promise<void> {
  if (isTauriRuntime()) return invokeReal<void>("cancel_mission", { missionId });
  await mockDelay();
  mockEmit<MissionLogEvent>("mission-log", { missionId, line: `[cancel] mission ${missionId} をキャンセルしました` });
  mockEmit<MissionUpdatedEvent>("mission-updated", { missionId });
}

export async function ownerVerdict(missionId: string, passed: boolean, reason: string): Promise<void> {
  if (isTauriRuntime()) {
    return invokeReal<void>("owner_verdict", { missionId, passed, reason });
  }
  await mockDelay();
  const status = MOCK_STATUS[missionId];
  if (!status) throw new Error(`mission '${missionId}' not found`);
  const verdict: Verdict = { ts: Date.now() / 1000, passed, reason };
  status.verdicts = [...(status.verdicts ?? []), verdict];
  mockEmit<MissionUpdatedEvent>("mission-updated", { missionId });
}

export async function criteriaList(): Promise<CriteriaPayload> {
  if (isTauriRuntime()) return invokeReal<CriteriaPayload>("criteria_list");
  await mockDelay();
  return MOCK_CRITERIA;
}

export async function criteriaApprove(name: string): Promise<void> {
  if (isTauriRuntime()) return invokeReal<void>("criteria_approve", { name });
  await mockDelay();
  MOCK_CRITERIA.drafts = MOCK_CRITERIA.drafts.filter((d) => d.name !== name);
}

export async function criteriaReject(name: string): Promise<void> {
  if (isTauriRuntime()) return invokeReal<void>("criteria_reject", { name });
  await mockDelay();
  MOCK_CRITERIA.drafts = MOCK_CRITERIA.drafts.filter((d) => d.name !== name);
}

export async function humanDone(missionId: string, taskId: string, note: string): Promise<void> {
  if (isTauriRuntime()) {
    return invokeReal<void>("human_done", { missionId, taskId, note });
  }
  await mockDelay();
  const status = MOCK_STATUS[missionId];
  if (!status) throw new Error(`mission '${missionId}' not found`);
  const task = status.tasks.find((t) => t.id === taskId);
  if (!task) throw new Error(`task '${taskId}' not found in mission '${missionId}'`);
  if (task.status !== "awaiting_human") {
    throw new Error(`task '${taskId}' は awaiting_human ではない(現在: ${task.status})`);
  }
  task.status = "done";
  task.humanRequest = "";
  task.humanRequestBody = null;
  const doneCount = status.tasks.filter((t) => t.status === "done").length;
  const allDone = doneCount === status.tasks.length;
  if (allDone) status.status = "done";
  const summary = MOCK_MISSIONS.find((m) => m.missionId === missionId);
  if (summary) {
    summary.tasksDone = doneCount;
    if (allDone) summary.status = "done";
  }
  mockEmit<MissionLogEvent>("mission-log", { missionId, line: `task ${taskId} を検収した(人間の完了報告に基づくレビュー合格)` });
  mockEmit<MissionUpdatedEvent>("mission-updated", { missionId });
}

export async function doctor(): Promise<DoctorReport> {
  if (isTauriRuntime()) return invokeReal<DoctorReport>("doctor");
  await mockDelay();
  return MOCK_DOCTOR;
}

export async function getSettings(): Promise<Settings> {
  if (isTauriRuntime()) return invokeReal<Settings>("get_settings");
  await mockDelay();
  return { ...MOCK_SETTINGS };
}

export async function setSettings(settings: Settings): Promise<void> {
  if (isTauriRuntime()) return invokeReal<void>("set_settings", { settings });
  await mockDelay();
}

function mockDelay(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 120 + Math.random() * 180));
}

// 新規/承認ミッションの疑似実行: mission-logを数行流してからmission-updatedを1回emitする
// (API.md §3.1のフロー — mission_id判明直後にmission-updated、終了時にもう1回 — を模す)。
// 新規IDはMOCK_MISSIONS/MOCK_STATUS/MOCK_EVENTSにも登録する(登録しないと
// 遷移直後のmissionStatus/missionEventsがnot foundになり詳細画面が壊れる)。
async function mockStartOrApprove(existingId: string | null, intentForLog: string | null): Promise<string> {
  const missionId = existingId ?? Math.random().toString(16).slice(2, 10);
  await mockDelay();
  if (existingId) {
    // 承認の状態遷移を模す(遷移しないと承認後もawaiting_approvalのままで
    // 承認ボタンが何度でも押せてしまう)
    const status = MOCK_STATUS[existingId];
    status?.tasks.forEach((t) => {
      if (t.status === "awaiting_approval") t.status = "running";
    });
    if (status) status.status = "running";
    const summary = MOCK_MISSIONS.find((m) => m.missionId === existingId);
    if (summary) summary.status = "running";
  }
  if (!existingId) {
    const intent = intentForLog ?? "(no intent)";
    const now = Date.now() / 1000;
    MOCK_STATUS[missionId] = {
      missionId,
      intent,
      status: "running",
      tasks: [
        { id: "t1", title: "モックタスク1", status: "running", attempts: 1, worker: "claude_code", deps: [] },
        { id: "t2", title: "モックタスク2", status: "pending", attempts: 0, worker: "claude_code", deps: ["t1"] },
      ],
      costUsd: 0,
      budgetUsd: null,
    };
    MOCK_EVENTS[missionId] = [{ ts: now, event: "task.start", task: "t1" }];
    MOCK_MISSIONS.push({
      missionId,
      intent,
      status: "running",
      costUsd: 0,
      tasksDone: 0,
      tasksTotal: 2,
      createdTs: Date.now() / 1000,
      finishedTs: null,
    });
    mockEmit<MissionLogEvent>("mission-log", { missionId: null, line: "== planning ==" });
    mockEmit<MissionLogEvent>("mission-log", { missionId: null, line: `intent: ${intent}` });
    mockEmit<MissionLogEvent>("mission-log", { missionId: null, line: `mission ${missionId}: 2 tasks` });
    mockEmit<MissionLogEvent>("mission-log", { missionId, line: `ORGH_MISSION_ID=${missionId}` });
    mockEmit<MissionUpdatedEvent>("mission-updated", { missionId });
  }
  mockEmit<MissionLogEvent>("mission-log", { missionId, line: "== executing ==" });
  void (async () => {
    await mockDelay();
    mockEmit<MissionLogEvent>("mission-log", { missionId, line: "[task t1] started" });
    await mockDelay();
    mockEmit<MissionLogEvent>("mission-log", { missionId, line: "[task t1] done" });
    const status = MOCK_STATUS[missionId];
    if (status) {
      const target = existingId
        ? status.tasks.find((t) => t.status === "running")
        : status.tasks[0];
      if (target) {
        target.status = "done";
        MOCK_EVENTS[missionId]?.push({ ts: Date.now() / 1000, event: "task.review", task: target.id, passed: true });
      }
      const doneCount = status.tasks.filter((t) => t.status === "done").length;
      const allDone = doneCount === status.tasks.length;
      if (allDone) status.status = "done";
      const summary = MOCK_MISSIONS.find((m) => m.missionId === missionId);
      if (summary) {
        summary.tasksDone = doneCount;
        if (allDone) summary.status = "done";
      }
    }
    mockEmit<MissionUpdatedEvent>("mission-updated", { missionId });
  })();
  return missionId;
}
