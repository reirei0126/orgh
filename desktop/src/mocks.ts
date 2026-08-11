// ブラウザ単体実行(Tauri外)用のモックデータ・モック実装。
// desktop/src/api.ts がTauri未検出時にここへフォールバックする。

import type {
  CriteriaPayload,
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
    createdTs: NOW - 10800,
    finishedTs: NOW - 600,
  },
  {
    missionId: "f9e8d7c6",
    intent: "通知バッチのリトライ処理を冪等化し、重複送信インシデントの再発を防ぐ",
    status: "running",
    costUsd: 0.9127,
    tasksDone: 2,
    tasksTotal: 5,
    createdTs: NOW - 14400,
    finishedTs: null,
  },
  {
    missionId: "5a4b3c2d",
    intent: "検索APIのレイテンシ改善(p95 800ms→200ms目標)とインデックス再設計",
    status: "running",
    costUsd: 0.4310,
    tasksDone: 1,
    tasksTotal: 3,
    createdTs: NOW - 18000,
    finishedTs: null,
  },
  {
    missionId: "b1c2d3e4",
    intent: "ログ基盤のPIIマスキング処理を追加し、既存ダッシュボードへの影響を検証する",
    status: "done",
    costUsd: 1.2050,
    tasksDone: 3,
    tasksTotal: 3,
    createdTs: NOW - 21600,
    finishedTs: NOW - 2400,
  },
  {
    missionId: "c1d2e3f4",
    intent: "決済Webhookの署名検証を追加し、リプレイ攻撃を防止する",
    status: "done",
    costUsd: 0.7742,
    tasksDone: 2,
    tasksTotal: 2,
    createdTs: NOW - 25200,
    finishedTs: NOW - 3000,
  },
  {
    missionId: "d1e2f3a4",
    intent: "本番DBのマイグレーション実行(破壊的操作のため人手での実行が必要)",
    status: "awaiting_human",
    costUsd: 0.3120,
    tasksDone: 1,
    tasksTotal: 2,
    createdTs: NOW - 28800,
    finishedTs: null,
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
  // (a) done かつ未裁定: ownerVerdict導線の初期表示確認用(verdictsキー自体が無い)
  b1c2d3e4: [
    { id: "t1", title: "ログ出力箇所の棚卸しとPII該当フィールドの特定", status: "done", attempts: 1, worker: "claude_code", deps: [] },
    { id: "t2", title: "マスキング処理の実装とユニットテスト追加", status: "done", attempts: 1, worker: "claude_code", deps: ["t1"] },
    { id: "t3", title: "既存ダッシュボードの回帰確認", status: "done", attempts: 1, worker: "codex", deps: ["t2"] },
  ],
  // (b) done かつ verdicts に1件記録済み: ownerVerdict完了後の表示確認用
  c1d2e3f4: [
    { id: "t1", title: "Webhook署名検証ロジックの実装", status: "done", attempts: 1, worker: "claude_code", deps: [] },
    { id: "t2", title: "リプレイ攻撃を想定した統合テスト追加", status: "done", attempts: 1, worker: "claude_code", deps: ["t1"] },
  ],
  // (c) awaiting_human タスクを持つミッション: humanDone導線の表示確認用
  d1e2f3a4: [
    { id: "t1", title: "マイグレーションSQLのドライラン結果の確認", status: "done", attempts: 1, worker: "claude_code", deps: [] },
    {
      id: "t2",
      title: "本番DBへのマイグレーション実行",
      status: "awaiting_human",
      attempts: 1,
      worker: "claude_code",
      deps: ["t1"],
      humanRequest: "本番DBへのDDL実行はorghの自己改変ガード対象外の破壊的操作のため、人間が直接実行して完了報告すること",
      humanRequestBody:
        "# 人間対応依頼: 本番DBマイグレーション実行\n\n" +
        "## 背景\n" +
        "ドライラン(t1)は成功したが、本番DBへのDDL実行はorghのworker権限では行わない方針のため、\n" +
        "人間が直接実行する必要がある。\n\n" +
        "## 実施手順\n" +
        "1. `runs/d1e2f3a4/artifacts/migration.sql` の内容を確認する\n" +
        "2. メンテナンスウィンドウ内で本番DBに対して実行する\n" +
        "3. 実行結果(成功/失敗、所要時間)を `orgh humandone d1e2f3a4 t2 --note \"...\"` で報告する\n",
    },
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
    status: "awaiting_approval",
    tasks: MOCK_TASKS.f9e8d7c6,
    costUsd: 0.9127,
    budgetUsd: 2.5,
    // PROD-001承認ブリーフの視覚確認用(承認ダイアログはブラウザモックモードで
    // このミッションを開いて確認する: #/mission/f9e8d7c6)
    approvalBrief: {
      summary:
        "タスク「リトライワーカーに冪等キーチェックを実装する」がorgh自身のパッケージ (/Users/mock/org-harness/orgh) を書き換えるため停止中。承認すると残り3件のタスクが実行される(消費済み 0.91 USD)。",
      gatedTasks: [
        {
          id: "t3",
          title: "リトライワーカーに冪等キーチェックを実装する",
          workdir: "/Users/mock/org-harness",
          reason: "orgh自身のパッケージ (/Users/mock/org-harness/orgh) を書き換える",
        },
      ],
      pendingTaskCount: 3,
    },
  },
  "5a4b3c2d": {
    missionId: "5a4b3c2d",
    intent: "検索APIのレイテンシ改善(p95 800ms→200ms目標)とインデックス再設計",
    status: "running",
    tasks: MOCK_TASKS["5a4b3c2d"],
    costUsd: 0.4310,
    budgetUsd: null,
  },
  // (a) done かつ未裁定: verdictsキー自体を省略する(旧CLI互換のgraceful
  // degradationと同じ経路を、そのまま「まだ裁定していない」表示にも使う)。
  b1c2d3e4: {
    missionId: "b1c2d3e4",
    intent: "ログ基盤のPIIマスキング処理を追加し、既存ダッシュボードへの影響を検証する",
    status: "done",
    tasks: MOCK_TASKS.b1c2d3e4,
    costUsd: 1.2050,
    budgetUsd: 2.0,
  },
  // (b) done かつ verdicts に1件記録済み
  c1d2e3f4: {
    missionId: "c1d2e3f4",
    intent: "決済Webhookの署名検証を追加し、リプレイ攻撃を防止する",
    status: "done",
    tasks: MOCK_TASKS.c1d2e3f4,
    costUsd: 0.7742,
    budgetUsd: 1.5,
    verdicts: [
      { ts: NOW - 300, passed: true, reason: "要件どおり実装され、統合テストも回帰も無かった" },
    ],
  },
  // (c) awaiting_human タスクを持つミッション
  d1e2f3a4: {
    missionId: "d1e2f3a4",
    intent: "本番DBのマイグレーション実行(破壊的操作のため人手での実行が必要)",
    status: "awaiting_human",
    tasks: MOCK_TASKS.d1e2f3a4,
    costUsd: 0.3120,
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
  b1c2d3e4: buildLedger("b1c2d3e4"),
  c1d2e3f4: buildLedger("c1d2e3f4"),
  d1e2f3a4: buildLedger("d1e2f3a4"),
};

export const MOCK_DOCTOR: DoctorReport = {
  ok: true,
  checks: [
    { name: "worker:claude_code", ok: true, detail: "1.2.3 / 認証: 確認済み", kind: "connectivity", authState: "ok" },
    { name: "worker:codex", ok: true, detail: "0.9.1 / 認証: 未確認(このワーカー種別は認証確認に非対応)", kind: "connectivity", authState: "unverified" },
    { name: "role:planner", ok: true, detail: "(= claude)", kind: "connectivity", authState: "n/a" },
    { name: "config", ok: true, detail: "検証済み", kind: "connectivity", authState: "n/a" },
    { name: "prompts_dir", ok: true, detail: "/Users/mock/org-harness/prompts", kind: "connectivity", authState: "n/a" },
    { name: "vault", ok: false, detail: "未設定(watch/scanを使わないなら問題なし)", kind: "connectivity", authState: "n/a" },
    { name: "runs_dir", ok: true, detail: "/Users/mock/org-harness/runs", kind: "connectivity", authState: "n/a" },
  ],
};

export const MOCK_SETTINGS: Settings = {
  orghBin: "orgh",
  configPath: "/Users/mock/org-harness/config.yaml",
  runsDir: "/Users/mock/org-harness/runs",
};

// (d) 判断基準台帳: 本台帳エントリ複数カテゴリ + _drafts 下書き2件以上。
// criteriaApprove/criteriaRejectのモックはこの配列自体を破壊的に操作する
// (呼ぶとdraftsから該当エントリが消える。api.tsのモック実装から参照される)。
export const MOCK_CRITERIA: CriteriaPayload = {
  entries: [
    {
      category: "design",
      id: "DESIGN-001",
      strength: "norm",
      text: "承認接点は判断内容を一文(summary)で先に提示し、詳細は展開時のみ見せる",
      sourceMission: "4d048081",
      date: "2026-08-10",
    },
    {
      category: "design",
      id: "DESIGN-002",
      strength: "pref",
      text: "ステータスの内部値は英語のまま変更せず、表示ラベルのみ日本語化する",
      sourceMission: "4d048081",
      date: "2026-08-10",
    },
    {
      category: "process",
      id: "PROCESS-001",
      strength: "norm",
      text: "後続タスクは前段タスクの完了報告を鵜呑みにせず、実装コードを読んで実在確認してから着手する",
      sourceMission: "3af738a2",
      date: "2026-08-11",
    },
  ],
  drafts: [
    {
      name: "c1d2e3f4-1",
      path: "/Users/mock/org-harness/criteria/_drafts/c1d2e3f4-1.json",
      category: "process",
      strength: "pref",
      text: "Webhook系タスクは署名検証の単体テストを必ず含める",
      raw: {
        category: "process",
        prefix: "PROCESS",
        strength: "pref",
        text: "Webhook系タスクは署名検証の単体テストを必ず含める",
      },
    },
    {
      name: "c1d2e3f4-2",
      path: "/Users/mock/org-harness/criteria/_drafts/c1d2e3f4-2.json",
      category: "design",
      strength: "norm",
      text: "破壊的操作(本番DB変更等)は人間対応(awaiting_human)へ委譲し、workerに直接実行させない",
      raw: {
        category: "design",
        prefix: "DESIGN",
        strength: "norm",
        text: "破壊的操作(本番DB変更等)は人間対応(awaiting_human)へ委譲し、workerに直接実行させない",
      },
    },
  ],
  skipped: [],
};
