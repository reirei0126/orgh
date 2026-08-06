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
pub struct DoctorCheck {
    pub name: String,
    pub ok: bool,
    pub detail: String,
}

/// `orgh doctor --json` の戻り値そのもの。types.ts の `DoctorReport`。
/// `ok: false` でもCLIの終了コードは非0になるが、stdoutは引き続き
/// このスキーマの完全なJSONを出す(desktop/API.md 1.3)。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DoctorReport {
    pub ok: bool,
    pub checks: Vec<DoctorCheck>,
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
