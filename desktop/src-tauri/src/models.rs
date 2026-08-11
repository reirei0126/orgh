//! desktop/API.md / desktop/src/types.ts の型定義をRust側に写したもの。
//!
//! orgh CLIの `--json` 出力はsnake_case、フロントエンドへ返す値はcamelCase
//! (desktop/API.md 2章)。同じ構造体でserialize/deserializeの名前を
//! フィールドごとに出し分けて、CLI直読み→TS向け返却を1構造体で往復させる。

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// orgh CLIが `{"error": "..."}` を返したときの共通形。
#[derive(Debug, Deserialize)]
pub struct CliError {
    pub error: String,
}

/// `orgh list --json` の要素。types.ts の `MissionSummary` に対応。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct MissionSummary {
    #[serde(rename(serialize = "missionId", deserialize = "mission_id"))]
    pub mission_id: String,
    pub intent: String,
    pub status: String,
    #[serde(rename(serialize = "costUsd", deserialize = "cost_usd"))]
    pub cost_usd: f64,
    #[serde(rename(serialize = "tasksDone", deserialize = "tasks_done"))]
    pub tasks_done: u32,
    #[serde(rename(serialize = "tasksTotal", deserialize = "tasks_total"))]
    pub tasks_total: u32,
}

/// `orgh list --json` で読み飛ばされた壊れたmission.jsonの情報。
/// types.ts の `SkippedMission` に対応。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SkippedMission {
    pub path: String,
    pub reason: String,
}

/// `orgh list --json` の生レスポンス全体。フロントへは missions と skipped を
/// そのまま渡す(壊れたデータを黙殺して「0件」と誤表示しないため)。
/// `skipped` は旧CLIとの互換のため欠落を許容する。
#[derive(Debug, Serialize, Deserialize)]
pub struct ListPayload {
    pub missions: Vec<MissionSummary>,
    #[serde(default)]
    pub skipped: Vec<SkippedMission>,
}

/// `orgh status <id> --json` の `tasks[]` 要素。types.ts の `TaskStatus`。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TaskStatus {
    pub id: String,
    pub title: String,
    pub status: String,
    pub attempts: u32,
    pub worker: String,
    pub deps: Vec<String>,
}

/// `orgh status <id> --json` の `approval_brief.gated_tasks[]` 要素。
/// types.ts の `GatedTask`。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct GatedTask {
    pub id: String,
    pub title: String,
    pub workdir: String,
    pub reason: String,
}

/// `orgh status <id> --json` の `approval_brief`。types.ts の `ApprovalBrief`。
/// オーナー裁定PROD-001: 承認接点は一文(summary)を先に見せ、詳細
/// (gated_tasks)は展開時のみ見せる。awaiting_approvalタスクが1件以上ある
/// ときのみサーバ側(orgh/status_json.py)が付与する。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ApprovalBrief {
    pub summary: String,
    #[serde(rename(serialize = "gatedTasks", deserialize = "gated_tasks"))]
    pub gated_tasks: Vec<GatedTask>,
    #[serde(rename(serialize = "pendingTaskCount", deserialize = "pending_task_count"))]
    pub pending_task_count: u32,
}

/// `orgh status <id> --json` の戻り値そのもの。types.ts の `MissionStatus`。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct MissionStatus {
    #[serde(rename(serialize = "missionId", deserialize = "mission_id"))]
    pub mission_id: String,
    pub intent: String,
    pub status: String,
    pub tasks: Vec<TaskStatus>,
    #[serde(rename(serialize = "costUsd", deserialize = "cost_usd"))]
    pub cost_usd: f64,
    #[serde(rename(serialize = "budgetUsd", deserialize = "budget_usd"))]
    pub budget_usd: Option<f64>,
    /// 旧CLI互換のため欠落を許容(approval_briefキー自体が無いことがある)。
    #[serde(
        default,
        rename(serialize = "approvalBrief", deserialize = "approval_brief")
    )]
    pub approval_brief: Option<ApprovalBrief>,
}

/// `orgh events <id> --json` の `events[]` 要素。types.ts の `LedgerEvent`。
/// イベント種別ごとにts/event以外のキーが変わる自由形式のため、
/// 未知キーはすべて`extra`にflattenして素通しする。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct LedgerEvent {
    pub ts: f64,
    pub event: String,
    #[serde(flatten)]
    pub extra: BTreeMap<String, serde_json::Value>,
}

/// `orgh events <id> --json` の生レスポンス全体(deserialize専用の中間形)。
#[derive(Debug, Deserialize)]
pub struct EventsPayload {
    #[allow(dead_code)]
    pub mission_id: String,
    pub events: Vec<LedgerEvent>,
}

/// `orgh doctor --json` の `checks[]` 要素。types.ts の `DoctorCheck`。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct DoctorCheck {
    pub name: String,
    pub ok: bool,
    pub detail: String,
    #[serde(default = "default_doctor_check_kind")]
    pub kind: String,
    #[serde(
        default = "default_doctor_auth_state",
        rename(serialize = "authState", deserialize = "auth_state")
    )]
    pub auth_state: String,
}

fn default_doctor_check_kind() -> String {
    "connectivity".to_string()
}
fn default_doctor_auth_state() -> String {
    "n/a".to_string()
}

/// `orgh doctor --json` の戻り値そのもの。types.ts の `DoctorReport`。
/// `ok: false` でもCLIの終了コードは非0になるが、stdoutは引き続き
/// このスキーマの完全なJSONを出す(desktop/API.md 1.3)。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct DoctorReport {
    pub ok: bool,
    pub checks: Vec<DoctorCheck>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct WeeklyReportStat {
    pub week: String,
    pub total: u32,
    #[serde(rename(deserialize = "first_pass"))]
    pub first_pass: u32,
    #[serde(rename(deserialize = "first_pass_pct"))]
    pub first_pass_pct: u32,
    pub rework: u32,
    #[serde(rename(deserialize = "rework_pct"))]
    pub rework_pct: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct MissionReportLine {
    #[serde(rename(deserialize = "mission_id"))]
    pub mission_id: String,
    pub intent: String,
    #[serde(rename(deserialize = "cost_usd"))]
    pub cost_usd: f64,
    #[serde(rename(deserialize = "duration_sec"))]
    pub duration_sec: u64,
    #[serde(rename(deserialize = "tasks_done"))]
    pub tasks_done: u32,
    #[serde(rename(deserialize = "tasks_total"))]
    pub tasks_total: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct WorkerFailureStat {
    pub worker: String,
    pub failed: u32,
    pub total: u32,
    #[serde(rename(deserialize = "failed_pct"))]
    pub failed_pct: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ReportPayload {
    pub days: u32,
    pub weekly: Vec<WeeklyReportStat>,
    pub missions: Vec<MissionReportLine>,
    pub workers: Vec<WorkerFailureStat>,
    /// 集計から隔離した壊れたミッションデータ(旧CLI互換のため欠落許容)
    #[serde(default)]
    pub skipped: Vec<SkippedMission>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PlaybookEntry {
    pub text: String,
    #[serde(rename(deserialize = "mission_id"))]
    pub mission_id: Option<String>,
    pub date: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PlaybookFile {
    pub name: String,
    pub path: String,
    pub body: String,
    pub entries: Vec<PlaybookEntry>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PlaybookPayload {
    pub playbooks: Vec<PlaybookFile>,
}

/// "mission-log" イベントのペイロード。types.ts の `MissionLogEvent`。
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MissionLogEvent {
    pub mission_id: Option<String>,
    pub line: String,
}

/// "mission-updated" イベントのペイロード。types.ts の `MissionUpdatedEvent`。
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MissionUpdatedEvent {
    pub mission_id: String,
}
