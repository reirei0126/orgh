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
 * タスク0件="empty"。全件done="done"。1件でもfailed="failed"。
 * 1件でもawaiting_approval="awaiting_approval"。
 * 1件でもawaiting_human="awaiting_human"(awaiting_approvalより優先度は下)。
 * 全件終端(done/cancelled/skipped)でdone以外を含む="cancelled"。
 * それ以外(pending/running混在)="running"。 */
export type MissionListStatus =
  | "empty"
  | "running"
  | "done"
  | "failed"
  | "awaiting_approval"
  | "awaiting_human"
  | "cancelled";

/** list_missions() で読み飛ばされた壊れた mission.json の情報。
 * 破損データを黙殺すると「0件」とデータ消失を区別できないため明示する。 */
export interface SkippedMission {
  path: string;
  reason: string;
}

/** list_missions() の戻り値全体。orgh list --json 由来。 */
export interface ListPayload {
  missions: MissionSummary[];
  skipped: SkippedMission[];
}

/** mission_status(missionId) の戻り値。orgh status <id> --json 由来。 */
export interface MissionStatus {
  missionId: string;
  intent: string;
  status: MissionRunStatus;
  tasks: TaskStatus[];
  costUsd: number;
  /** 予算上限。config未設定(無制限)なら null。 */
  budgetUsd: number | null;
  /** 承認待ちタスクが1件以上あるときのみ存在(orgh/status_json.py
   * `approval_brief`。オーナー裁定PROD-001)。旧CLI/旧データでは欠落するため
   * undefined/nullを許容し、その場合GUIは詳細確認ダイアログを出さず
   * 従来どおり即時承認にフォールバックする(graceful degradation)。 */
  approvalBrief?: ApprovalBrief | null;
}

/** 承認ブリーフ: 「何を承認するのか」をsummaryの一文で先に提示し、詳細
 * (gatedTasks)はオーナーが「詳細を見る」を開いたときだけ見せる
 * (台帳PROD-001: 判断材料を探させるUIは不合格)。 */
export interface ApprovalBrief {
  summary: string;
  gatedTasks: GatedTask[];
  /** 承認すると動き出すタスク数(awaiting_approval + pending の合計)。 */
  pendingTaskCount: number;
}

/** approval_brief.gated_tasks[] の1要素。自己改変ガードに引っかかった
 * タスク1件分(orgh/guard.py approval_reason() が理由文言を決定)。 */
export interface GatedTask {
  id: string;
  title: string;
  workdir: string;
  reason: string;
}

/** 実行中ミッションのステータス派生規則(orgh/status_json.py 準拠)。
 * listing._derive_status と完全に同一規則(0タスクなら "empty")。 */
export type MissionRunStatus =
  | "empty"
  | "running"
  | "done"
  | "failed"
  | "awaiting_approval"
  | "awaiting_human"
  | "cancelled";

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

/** DoctorCheckが何を検査しているかの分類(第2期 P0-1で追加)。
 * 現行の全チェックは"connectivity"(バイナリ疎通・パス到達性・書き込み権限等)。
 * "auth"は将来、疎通を介さない純粋な認証専用チェック行を追加する場合の
 * 予約値で、第2期時点ではCLIはこの値を出力しない(認証状態はworker行に
 * 付与するauthStateフィールドで表現する)。 */
export type DoctorCheckKind = "connectivity" | "auth";

/** 認証確認の結果(第2期 P0-1で追加)。worker:<name>行にのみ意味のある値が
 * 入り、それ以外の行(role:<name>, config, prompts_dir, vault, runs_dir等)は
 * 常に "n/a"。 */
export type DoctorCheckAuthState =
  | "ok"
  | "unverified"
  | "failed"
  | "n/a";

export interface DoctorCheck {
  /** 例: "worker:claude_code" "role:planner" "config" "prompts_dir" "vault" "runs_dir" */
  name: string;
  /** この行の総合可否。authStateが"failed"のときは必ずfalse(認証切れを
   * 「OK」と嘘表示しないため)。authStateが"unverified"/"n/a"のときは
   * 疎通確認のみの結果を反映する(true/falseどちらもありうる)。 */
  ok: boolean;
  detail: string;
  kind: DoctorCheckKind;
  /** "ok"=認証確認に成功。"unverified"=このワーカー種別は認証状態を確認
   * する手段が無い、または未実装(疎通自体はok/detailで別途判定済みで
   * あり、これは失敗ではない)。"failed"=認証切れ・認証エラーを検出
   * (疎通=okでも起こりうる)。"n/a"=このチェック行に認証という概念が
   * 適用されない。 */
  authState: DoctorCheckAuthState;
}

/** get_settings() / set_settings() で読み書きするGUI設定。
 * 永続化方式(tauri-plugin-store等)の選定はRustブリッジ実装タスクの裁量。 */
export interface Settings {
  /** orghバイナリの絶対パス、またはPATH解決可能なコマンド名。 */
  orghBin: string;
  /** orgh --config に渡す config.yaml の絶対パス。 */
  configPath: string;
  /** runs_dir の絶対パス。**表示用キャッシュであり、実際のCLI呼び出しには
   * 一切使用しない**(第2期PRD P0-2で「表示区分のみ」を採用。既存CLI
   * 利用者への非破壊を優先するための方針。理由の詳細はdesktop/API.md参照)。
   * 実際に効くruns_dirはconfigPathが指すconfig.yamlのruns_dirキーが正。
   * SettingsPage実装では、実際にCLI呼び出しへ反映されるorghBin/configPath
   * とは異なる視覚的区分(セクション分け・注記アイコン等)で表示すること。 */
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

// ---------------------------------------------------------------------------
// 第2期(GUI Phase 2)で追加した契約。以下は resume_mission / report() /
// playbooks() に関する型。resume_mission 自体は戻り値なし(void)なので
// 専用の型は無い(desktop/API.md §2, §3.1.1参照)。
// ---------------------------------------------------------------------------

/** report(days) の戻り値。orgh report --days <days> --json 由来。
 * 各集計値はテキスト版(orgh report、orgh/report.py)と完全に同じ計算式
 * (丸め処理含む)で算出済みの値をそのまま渡す契約。GUI側で独自に
 * 再計算・再丸めしないこと(フロントとCLI出力の数値が食い違うことを
 * 防ぐため。P1-2受け入れ基準: 同一期間・同一データでCLI出力と一致)。 */
export interface ReportPayload {
  /** 呼び出し時に指定した集計期間(日数)。そのままエコーバックする。 */
  days: number;
  weekly: WeeklyReportStat[];
  missions: MissionReportLine[];
  workers: WorkerFailureStat[];
  /** 集計から隔離した壊れたミッションデータ(1件の破損で全体を落とさない)。 */
  skipped: SkippedMission[];
}

/** 週次の初回attempt合格率・差し戻し率。orgh/report.py _weekly_stats 由来。 */
export interface WeeklyReportStat {
  /** ISO週表記。例: "2026-W32"(Python datetime.strftime("%G-W%V")由来)。 */
  week: string;
  /** その週に初回task.reviewが記録されたタスク数。 */
  total: number;
  firstPass: number;
  /** round(firstPass / total * 100)。total=0のとき0。 */
  firstPassPct: number;
  rework: number;
  /** round(rework / total * 100)。total=0のとき0。 */
  reworkPct: number;
}

/** ミッション別のコスト・所要時間サマリ。orgh/report.py _mission_line 由来。 */
export interface MissionReportLine {
  missionId: string;
  /** ListPayload側の60文字切り詰めとは異なり、ここは切り詰めない全文。 */
  intent: string;
  costUsd: number;
  /** 最初のイベント〜mission.finished(無ければ最後のイベント)の秒数。
   * イベントが1件も無いミッションは0。 */
  durationSec: number;
  tasksDone: number;
  tasksTotal: number;
}

/** worker別の失敗率。orgh/report.py _worker_stats 由来。worker未割当
 * (null)のタスクは集計から除外する(テキスト版の未整理な挙動を
 * JSON版では踏襲しない、という明示的な仕様)。 */
export interface WorkerFailureStat {
  worker: string;
  failed: number;
  total: number;
  /** round(failed / total * 100)。total=0のとき0(理論上発生しない)。 */
  failedPct: number;
}

/** playbooks() の戻り値。orgh playbooks --json 由来。
 * playbooksディレクトリが存在しない、または *.md が1件も無い場合も
 * エラーにはせず { playbooks: [] } を返す契約(P1-3受け入れ基準: 空状態
 * はエラーではなく「まだ記録がありません」等の表示にする)。 */
export interface PlaybookPayload {
  playbooks: PlaybookFile[];
}

/** 1つのplaybookファイル(例: playbooks/coding.md)。_backup/_archive配下
 * (orgh/gc.pyがバックアップ・退避に使うサブディレクトリ)は含まない
 * (playbooks_dir直下の *.md のみを対象とする)。 */
export interface PlaybookFile {
  /** 拡張子を除いたファイル名。例: "coding" "planning" "st-test" "README"。 */
  name: string;
  /** 絶対パス。 */
  path: string;
  /** ファイル全文(見出し・地の文含む)。entriesに分解できない内容の
   * フォールバック表示用。 */
  body: string;
  /** "-"で始まる行のみを抽出したエントリ一覧(見出し等の行は含まない)。 */
  entries: PlaybookEntry[];
}

/** playbookファイル中の1エントリ(1つの"-"始まり行)。retroが自動追記
 * した行は末尾に `<!-- m:<mission_id> d:<date> -->` が付与される
 * (orgh/planner.py retro())。手動追記された行にはこれが無く、
 * missionId/dateはnullになる。P1-3受け入れ基準の「どのミッションが
 * どのplaybookエントリを追記したか」はmissionIdで判別する。 */
export interface PlaybookEntry {
  /** 行頭の"- "と末尾のHTMLコメントタグを除いた本文。 */
  text: string;
  missionId: string | null;
  /** ISO日付文字列(例: "2026-08-05")。 */
  date: string | null;
}
