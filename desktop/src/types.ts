// GUI-CLI連携の契約(このファイルと desktop/API.md がセットで真実源)。
//
// 型定義のみ。実装(Rust側 #[tauri::command] 本体、React側の呼び出しコード)は
// 後続タスク(Rustブリッジ実装タスク/フロントエンドUI実装タスク)が行う。
// このファイルを編集してよいのはこの契約タスクのみ — 後続タスクは
// desktop/API.md と desktop/src/types.ts を編集してはならない。
//
// 命名規約: ここはすべてcamelCase。Rust側は同名フィールドを
// #[serde(rename_all = "camelCase")] で揃える。詳細は desktop/API.md 参照。

/** list_missions() の要素。orgh list --json の missions[] 由来。 */
export interface MissionSummary {
  missionId: string;
  /** 60文字超は "…" で切り詰め済み・改行は空白に置換済み(orgh側で加工済み)。 */
  intent: string;
  status: MissionListStatus;
  costUsd: number;
  tasksDone: number;
  tasksTotal: number;
}

/** list時点のステータス派生規則(orgh/listing.py _derive_status 準拠)。
 * タスク0件="empty"。1件でもfailed="failed"。全件done="done"。
 * それ以外(pending/running混在)="running"。 */
export type MissionListStatus = "empty" | "running" | "done" | "failed";

/** mission_status(missionId) の戻り値。orgh status <id> --json 由来。 */
export interface MissionStatus {
  missionId: string;
  intent: string;
  status: MissionRunStatus;
  tasks: TaskStatus[];
  costUsd: number;
  /** 予算上限。config未設定(無制限)なら null。 */
  budgetUsd: number | null;
}

/** 実行中ミッションのステータス派生規則(orgh/status_json.py 準拠)。
 * 全件done="done"。1件でもfailed="failed"。それ以外="running"。
 * ("empty" はここには出ない: statusはタスクが1件以上あるミッションに使う) */
export type MissionRunStatus = "running" | "done" | "failed";

export interface TaskStatus {
  id: string;
  title: string;
  /** pending/running/review/done/failed/cancelled/skipped/awaiting_approval等。
   * orgh側のTask.statusをそのまま文字列で通す。将来値が増えても壊れない
   * よう、リテラルUnionにはせずstringとする。 */
  status: string;
  attempts: number;
  worker: string;
  deps: string[];
}

/** mission_events(missionId, tail) の戻り値の要素。
 * orgh events <id> --json の events[] 由来 = ledger.jsonl の各行そのもの。
 * イベント種別ごとにts/event以外のフィールドが変わる自由形式のため、
 * 未知キーを許容するインデックスシグネチャを持つ。 */
export interface LedgerEvent {
  /** unix epoch seconds (Python time.time()) */
  ts: number;
  /** 例: "task.start" "task.output" "task.review" "mission.finished" 等。
   * orgh/orchestrator.py の store.log() 呼び出し一覧が全種別の出典。 */
  event: string;
  [key: string]: unknown;
}

/** doctor() の戻り値。orgh doctor --json 由来。 */
export interface DoctorReport {
  ok: boolean;
  checks: DoctorCheck[];
}

export interface DoctorCheck {
  /** 例: "worker:claude_code" "role:planner" "config" "prompts_dir" "vault" "runs_dir" */
  name: string;
  ok: boolean;
  detail: string;
}

/** get_settings() / set_settings() で読み書きするGUI設定。
 * 永続化方式(tauri-plugin-store等)の選定はRustブリッジ実装タスクの裁量。 */
export interface Settings {
  /** orghバイナリの絶対パス、またはPATH解決可能なコマンド名。 */
  orghBin: string;
  /** orgh --config に渡す config.yaml の絶対パス。 */
  configPath: string;
  /** runs_dir の絶対パス。 */
  runsDir: string;
}

/** "mission-log" イベントのペイロード。
 * start_mission/approve_mission が起動した `orgh run`/`orgh approve` の
 * stdout/stderrを1行ずつ流す。missionIdが判明する前
 * (ORGH_MISSION_ID=<id> 行が出る前)に出た行は missionId: null。 */
export interface MissionLogEvent {
  missionId: string | null;
  line: string;
}

/** "mission-updated" イベントのペイロード。
 * 発火タイミングの最小保証は desktop/API.md 参照
 * (missionId判明直後、および対象プロセス終了時に最低1回ずつ)。 */
export interface MissionUpdatedEvent {
  missionId: string;
}
