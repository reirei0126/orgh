// ブラウザ単体実行(Tauri外)用のモックデータ・モック実装。
// desktop/src/api.ts がTauri未検出時にここへフォールバックする。

import type {
  DoctorReport,
  LedgerEvent,
  MissionStatus,
  MissionSummary,
  Settings,
  TaskStatus,
} from "./types";

const NOW = 1754524800; // 2026-08-07T00:00:00Z 相当の固定値(モックは決定的にする)

export const MOCK_MISSIONS: MissionSummary[] = [
  {
    missionId: "a1b2c3d4",
    intent: "料金プランページのレスポンシブ崩れを修正し、Stripe Checkoutの導線を整理する",
    status: "done",
    costUsd: 1.8342,
    tasksDone: 4,
    tasksTotal: 4,
  },
  {
    missionId: "f9e8d7c6",
    intent: "通知バッチのリトライ処理を冪等化し、重複送信インシデントの再発を防ぐ",
    status: "running",
    costUsd: 0.9127,
    tasksDone: 2,
    tasksTotal: 5,
  },
  {
    missionId: "5a4b3c2d",
    intent: "検索APIのレイテンシ改善(p95 800ms→200ms目標)とインデックス再設計",
    status: "running",
    costUsd: 0.4310,
    tasksDone: 1,
    tasksTotal: 3,
  },
];

const MOCK_TASKS: Record<string, TaskStatus[]> = {
  a1b2c3d4: [
    { id: "t1", title: "料金カードのグリッド崩れを再現し原因を特定する", status: "done", attempts: 1, worker: "claude_code", deps: [] },
    { id: "t2", title: "CSSグリッドをコンテナクエリベースに書き換える", status: "done", attempts: 1, worker: "claude_code", deps: ["t1"] },
    { id: "t3", title: "Checkout導線のボタン文言・遷移順を整理する", status: "done", attempts: 2, worker: "codex", deps: ["t1"] },
    { id: "t4", title: "主要ブレークポイントでの回帰確認とスクリーンショット添付", status: "done", attempts: 1, worker: "claude_code", deps: ["t2", "t3"] },
  ],
  f9e8d7c6: [
    { id: "t1", title: "重複送信ログを収集し発生条件を切り分ける", status: "done", attempts: 1, worker: "claude_code", deps: [] },
    { id: "t2", title: "冪等キー設計(idempotency key)を決定する", status: "done", attempts: 1, worker: "claude_code", deps: ["t1"] },
    { id: "t3", title: "リトライワーカーに冪等キーチェックを実装する", status: "awaiting_approval", attempts: 1, worker: "claude_code", deps: ["t2"] },
    { id: "t4", title: "既存キューのバックフィル移行スクリプトを書く", status: "pending", attempts: 0, worker: "codex", deps: ["t2"] },
    { id: "t5", title: "統合テストとカナリア投入手順の確認", status: "pending", attempts: 0, worker: "claude_code", deps: ["t3", "t4"] },
  ],
  "5a4b3c2d": [
    { id: "t1", title: "現行クエリのプロファイリングとボトルネック特定", status: "running", attempts: 1, worker: "claude_code", deps: [] },
    { id: "t2", title: "インデックス再設計案の作成とベンチマーク", status: "pending", attempts: 0, worker: "claude_code", deps: ["t1"] },
    { id: "t3", title: "段階的ロールアウト計画とロールバック手順の整備", status: "pending", attempts: 0, worker: "codex", deps: ["t2"] },
  ],
};

export const MOCK_STATUS: Record<string, MissionStatus> = {
  a1b2c3d4: {
    missionId: "a1b2c3d4",
    intent: "料金プランページのレスポンシブ崩れを修正し、Stripe Checkoutの導線を整理する",
    status: "done",
    tasks: MOCK_TASKS.a1b2c3d4,
    costUsd: 1.8342,
    budgetUsd: 3.0,
  },
  f9e8d7c6: {
    missionId: "f9e8d7c6",
    intent: "通知バッチのリトライ処理を冪等化し、重複送信インシデントの再発を防ぐ",
    status: "running",
    tasks: MOCK_TASKS.f9e8d7c6,
    costUsd: 0.9127,
    budgetUsd: 2.5,
  },
  "5a4b3c2d": {
    missionId: "5a4b3c2d",
    intent: "検索APIのレイテンシ改善(p95 800ms→200ms目標)とインデックス再設計",
    status: "running",
    tasks: MOCK_TASKS["5a4b3c2d"],
    costUsd: 0.4310,
    budgetUsd: null,
  },
};

function buildLedger(missionId: string): LedgerEvent[] {
  const base = NOW - 900;
  const events: LedgerEvent[] = [
    { ts: base, event: "mission.start", mission: missionId },
    { ts: base + 3, event: "plan.created", tasks: MOCK_TASKS[missionId]?.length ?? 0 },
  ];
  const tasks = MOCK_TASKS[missionId] ?? [];
  let t = base + 8;
  for (const task of tasks) {
    events.push({ ts: t, event: "task.start", task: task.id, worker: task.worker, attempt: 1 });
    t += 25;
    events.push({ ts: t, event: "task.output", task: task.id, ok: task.status !== "failed", cost: Number((Math.random() * 0.15 + 0.01).toFixed(4)) });
    t += 4;
    if (task.status === "awaiting_approval") {
      events.push({ ts: t, event: "task.review", task: task.id, verdict: "needs_approval" });
      t += 3;
      events.push({ ts: t, event: "mission.awaiting_approval", task: task.id });
    } else if (task.status === "done") {
      events.push({ ts: t, event: "task.review", task: task.id, verdict: "pass" });
    } else if (task.status === "running") {
      events.push({ ts: t, event: "task.progress", task: task.id, detail: "編集中: src/search/index.ts" });
    }
    t += 6;
  }
  events.push({ ts: t, event: "ledger.heartbeat", detail: "watcher alive" });
  return events.slice(-24);
}

export const MOCK_EVENTS: Record<string, LedgerEvent[]> = {
  a1b2c3d4: buildLedger("a1b2c3d4"),
  f9e8d7c6: buildLedger("f9e8d7c6"),
  "5a4b3c2d": buildLedger("5a4b3c2d"),
};

export const MOCK_DOCTOR: DoctorReport = {
  ok: true,
  checks: [
    { name: "worker:claude_code", ok: true, detail: "1.2.3" },
    { name: "worker:codex", ok: true, detail: "0.9.1" },
    { name: "role:planner", ok: true, detail: "(= claude)" },
    { name: "config", ok: true, detail: "検証済み" },
    { name: "prompts_dir", ok: true, detail: "/Users/mock/org-harness/prompts" },
    { name: "vault", ok: false, detail: "未設定(watch/scanを使わないなら問題なし)" },
    { name: "runs_dir", ok: true, detail: "/Users/mock/org-harness/runs" },
  ],
};

export const MOCK_SETTINGS: Settings = {
  orghBin: "orgh",
  configPath: "/Users/mock/org-harness/config.yaml",
  runsDir: "/Users/mock/org-harness/runs",
};
