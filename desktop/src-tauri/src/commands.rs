//! `#[tauri::command]` 本体。desktop/API.md 2章のコマンドをここに置く。
//!
//! 読み取り系(list_missions/mission_status/mission_events/doctor)は
//! `cli::run_json` で同期実行してJSONをそのまま返す。
//! 長時間コマンドは `cli` の非同期ブリッジで実行し
//! イベント(mission-log/mission-updated)を発火する(desktop/API.md 3章)。

use tauri::AppHandle;

use crate::cli;
use crate::models::{
    CriteriaPayload, DoctorReport, EventsPayload, LedgerEvent, ListPayload, MissionStatus,
    PlaybookPayload, ReportPayload,
};
use crate::settings::{self, Settings};

#[tauri::command]
pub fn list_missions(app: AppHandle) -> Result<ListPayload, String> {
    // missionsだけでなくskipped(読めなかったmission.json)も返す。
    // 破損データを黙殺すると「0件」とデータ消失をUIで区別できない
    let settings = settings::load_settings(&app)?;
    cli::run_json(&settings, &["list", "--json"])
}

#[tauri::command]
pub fn mission_status(app: AppHandle, mission_id: String) -> Result<MissionStatus, String> {
    let settings = settings::load_settings(&app)?;
    cli::run_json(&settings, &["status", &mission_id, "--json"])
}

#[tauri::command]
pub fn mission_events(
    app: AppHandle,
    mission_id: String,
    tail: u32,
) -> Result<Vec<LedgerEvent>, String> {
    let settings = settings::load_settings(&app)?;
    let tail_arg = tail.to_string();
    let payload: EventsPayload = cli::run_json(
        &settings,
        &["events", &mission_id, "--json", "--tail", &tail_arg],
    )?;
    Ok(payload.events)
}

#[tauri::command]
pub fn doctor(app: AppHandle) -> Result<DoctorReport, String> {
    let settings = settings::load_settings(&app)?;
    cli::run_json(&settings, &["doctor", "--json"])
}

#[tauri::command]
pub fn report(app: AppHandle, days: u32) -> Result<ReportPayload, String> {
    let settings = settings::load_settings(&app)?;
    let args = build_report_args(days);
    let refs: Vec<&str> = args.iter().map(String::as_str).collect();
    cli::run_json(&settings, &refs)
}

#[tauri::command]
pub fn playbooks(app: AppHandle) -> Result<PlaybookPayload, String> {
    let settings = settings::load_settings(&app)?;
    let args = build_playbooks_args();
    let refs: Vec<&str> = args.iter().map(String::as_str).collect();
    cli::run_json(&settings, &refs)
}

// start/approve/resumeは確認行の検出までブロックする長時間処理。Tauriの
// 同期コマンドはメインスレッドで実行されるため、そのまま書くとplanning完了
// (数分)までアプリのイベントループごと凍結し、GUIのローディングが永遠に
// 終わらない(実機で実測)。asyncコマンド+spawn_blockingで退避する
#[tauri::command]
pub async fn start_mission(
    app: AppHandle,
    intent: Option<String>,
    note: Option<String>,
) -> Result<String, String> {
    let settings = settings::load_settings(&app)?;
    let args = build_run_args(&settings, intent, note)?;
    let bin = settings.orgh_bin.clone();
    tauri::async_runtime::spawn_blocking(move || {
        cli::spawn_and_bridge(app, bin, args, None, "ORGH_MISSION_ID=")
    })
    .await
    .map_err(|e| format!("コマンド実行スレッドの失敗: {e}"))?
}

#[tauri::command]
pub async fn approve_mission(app: AppHandle, mission_id: String) -> Result<(), String> {
    let settings = settings::load_settings(&app)?;
    let args = vec![
        "--config".to_string(),
        settings.config_path.clone(),
        "approve".to_string(),
        mission_id.clone(),
        // GUIは非対話(TTY無し)なので本来--yes無しでも従来どおり即続行するが、
        // 明示しておくことでCLI側の対話確認ロジック変更に依存しない
        "--yes".to_string(),
    ];
    let bin = settings.orgh_bin.clone();
    tauri::async_runtime::spawn_blocking(move || {
        cli::spawn_and_bridge(app, bin, args, Some(mission_id), "ORGH_APPROVED=").map(|_| ())
    })
    .await
    .map_err(|e| format!("コマンド実行スレッドの失敗: {e}"))?
}

#[tauri::command]
pub async fn resume_mission(
    app: AppHandle,
    mission_id: String,
    retry_failed: bool,
) -> Result<(), String> {
    let settings = settings::load_settings(&app)?;
    let args = build_resume_args(&settings, &mission_id, retry_failed);
    // resumeもapproveと同様に確認行(ORGH_RESUMED=)の検出まで成功を返さない。
    // 即Okだとロック競合等の失敗が成功として画面に見え、再クリックで失敗
    // プロセスを量産する
    let bin = settings.orgh_bin.clone();
    tauri::async_runtime::spawn_blocking(move || {
        cli::spawn_and_bridge(app, bin, args, Some(mission_id), "ORGH_RESUMED=").map(|_| ())
    })
    .await
    .map_err(|e| format!("コマンド実行スレッドの失敗: {e}"))?
}

#[tauri::command]
pub fn cancel_mission(app: AppHandle, mission_id: String) -> Result<(), String> {
    let settings = settings::load_settings(&app)?;
    cli::run_sync(&settings, &["cancel", &mission_id])
}

// owner_verdict/criteria_*/human_doneは確認行の待受(ORGH_APPROVED=等)を
// 必要としない同期コマンド(desktop/API.md 2.1のlist_missions等と同じ経路)。
// approve_mission/resume_missionの`spawn_and_bridge`契約には一切手を入れない。

#[tauri::command]
pub fn owner_verdict(
    app: AppHandle,
    mission_id: String,
    passed: bool,
    reason: String,
) -> Result<(), String> {
    let settings = settings::load_settings(&app)?;
    let args = build_verdict_args(&mission_id, passed, &reason);
    let refs: Vec<&str> = args.iter().map(String::as_str).collect();
    cli::run_sync(&settings, &refs)
}

#[tauri::command]
pub fn criteria_list(app: AppHandle) -> Result<CriteriaPayload, String> {
    let settings = settings::load_settings(&app)?;
    cli::run_json(&settings, &["criteria", "list", "--json"])
}

#[tauri::command]
pub fn criteria_approve(app: AppHandle, name: String) -> Result<(), String> {
    let settings = settings::load_settings(&app)?;
    cli::run_sync(&settings, &["criteria", "approve", &name])
}

#[tauri::command]
pub fn criteria_reject(app: AppHandle, name: String) -> Result<(), String> {
    let settings = settings::load_settings(&app)?;
    cli::run_sync(&settings, &["criteria", "reject", &name])
}

#[tauri::command]
pub fn human_done(
    app: AppHandle,
    mission_id: String,
    task_id: String,
    note: String,
) -> Result<(), String> {
    let settings = settings::load_settings(&app)?;
    let args = build_human_done_args(&mission_id, &task_id, &note);
    let refs: Vec<&str> = args.iter().map(String::as_str).collect();
    cli::run_sync(&settings, &refs)
}

#[tauri::command]
pub fn get_settings(app: AppHandle) -> Result<Settings, String> {
    settings::load_settings(&app)
}

#[tauri::command]
pub fn set_settings(app: AppHandle, settings: Settings) -> Result<(), String> {
    settings::save_settings(&app, &settings)
}

/// `orgh run --intent <...>` / `orgh run --note <...>` の引数組み立て。
/// intent/noteはどちらか一方が必須、両方nullはバリデーションエラーとする
/// (desktop/API.md 2章)。
fn build_run_args(
    settings: &Settings,
    intent: Option<String>,
    note: Option<String>,
) -> Result<Vec<String>, String> {
    let mut args = vec![
        "--config".to_string(),
        settings.config_path.clone(),
        "run".to_string(),
    ];
    match (intent, note) {
        (None, None) => Err("intentとnoteのどちらか一方を指定すること".to_string()),
        (Some(_), Some(_)) => Err("intentとnoteは同時に指定できない".to_string()),
        (Some(intent), None) => {
            args.push("--intent".to_string());
            args.push(intent);
            Ok(args)
        }
        (None, Some(note)) => {
            args.push("--note".to_string());
            args.push(note);
            Ok(args)
        }
    }
}

pub fn build_resume_args(settings: &Settings, mission_id: &str, retry_failed: bool) -> Vec<String> {
    let mut args = vec![
        "--config".to_string(),
        settings.config_path.clone(),
        "resume".to_string(),
        mission_id.to_string(),
    ];
    if retry_failed {
        args.push("--retry-failed".to_string());
    }
    args
}

pub fn build_report_args(days: u32) -> Vec<String> {
    vec![
        "report".to_string(),
        "--days".to_string(),
        days.to_string(),
        "--json".to_string(),
    ]
}

pub fn build_playbooks_args() -> Vec<String> {
    vec!["playbooks".to_string(), "--json".to_string()]
}

/// `orgh verdict <id> --pass|--fail --reason <text>` の引数組み立て。
/// `--reason` は `--reason=<value>` 形式(等号つき単一トークン)で渡す。
/// 空白区切りの `--reason` "-値" 形式だと、Python argparseが値の先頭が
/// `-` の場合にオプションと誤認し `expected one argument` で落ちる
/// (argparseの既知の挙動)。等号形式なら値の内容(先頭ハイフン・改行・
/// 空白・日本語いずれも)に関わらず1トークンとして安全に渡せる。
pub fn build_verdict_args(mission_id: &str, passed: bool, reason: &str) -> Vec<String> {
    vec![
        "verdict".to_string(),
        mission_id.to_string(),
        if passed {
            "--pass".to_string()
        } else {
            "--fail".to_string()
        },
        format!("--reason={reason}"),
    ]
}

/// `orgh humandone <mission_id> <task_id> --note <text>` の引数組み立て。
/// `--note` も build_verdict_args と同じ理由で `--note=<value>` 形式にする。
pub fn build_human_done_args(mission_id: &str, task_id: &str, note: &str) -> Vec<String> {
    vec![
        "humandone".to_string(),
        mission_id.to_string(),
        task_id.to_string(),
        format!("--note={note}"),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    fn settings() -> Settings {
        Settings {
            orgh_bin: "orgh".to_string(),
            config_path: "/tmp/config.yaml".to_string(),
            runs_dir: "/tmp/runs".to_string(),
        }
    }

    #[test]
    fn build_run_args_rejects_both_none() {
        assert!(build_run_args(&settings(), None, None).is_err());
    }

    #[test]
    fn build_run_args_rejects_both_some() {
        let result = build_run_args(
            &settings(),
            Some("do it".to_string()),
            Some("note".to_string()),
        );
        assert!(result.is_err());
    }

    #[test]
    fn build_run_args_uses_intent_flag() {
        let args = build_run_args(&settings(), Some("do it".to_string()), None).unwrap();
        assert_eq!(
            args,
            vec![
                "--config".to_string(),
                "/tmp/config.yaml".to_string(),
                "run".to_string(),
                "--intent".to_string(),
                "do it".to_string(),
            ]
        );
    }

    #[test]
    fn build_run_args_uses_note_flag() {
        let args = build_run_args(&settings(), None, Some("my note".to_string())).unwrap();
        assert_eq!(
            args,
            vec![
                "--config".to_string(),
                "/tmp/config.yaml".to_string(),
                "run".to_string(),
                "--note".to_string(),
                "my note".to_string(),
            ]
        );
    }

    #[test]
    fn build_verdict_args_pass() {
        let args = build_verdict_args("m123", true, "十分な品質だった");
        assert_eq!(
            args,
            vec![
                "verdict".to_string(),
                "m123".to_string(),
                "--pass".to_string(),
                "--reason=十分な品質だった".to_string(),
            ]
        );
    }

    #[test]
    fn build_verdict_args_fail() {
        let args = build_verdict_args("m123", false, "要件を満たしていない");
        assert_eq!(
            args,
            vec![
                "verdict".to_string(),
                "m123".to_string(),
                "--fail".to_string(),
                "--reason=要件を満たしていない".to_string(),
            ]
        );
    }

    // --reason/--noteの値は「1個の引数配列要素」として渡ることを検証する
    // (シェルを経由しないRustのCommand::argsは配列要素をそのまま子プロセスへ
    // 渡すため、値の中身に関わらずインジェクションは起こらない。ここで
    // 確認したいのは、値の先頭が"-"のときにPython argparseが別オプション
    // だと誤認しないための"--reason=<value>"形式になっていること)。
    #[test]
    fn build_verdict_args_reason_with_leading_hyphen_stays_one_token() {
        let args = build_verdict_args("m123", true, "-1件の懸念あり");
        assert_eq!(args[3], "--reason=-1件の懸念あり");
        assert_eq!(args.len(), 4, "reasonは分割されず単一トークンのまま");
    }

    #[test]
    fn build_verdict_args_reason_with_whitespace_and_newlines() {
        let reason = "1行目\n2行目 スペース入り\tタブ入り";
        let args = build_verdict_args("m123", false, reason);
        assert_eq!(args[3], format!("--reason={reason}"));
        assert_eq!(args.len(), 4);
    }

    #[test]
    fn build_human_done_args_basic() {
        let args = build_human_done_args("m123", "t1", "対応完了しました");
        assert_eq!(
            args,
            vec![
                "humandone".to_string(),
                "m123".to_string(),
                "t1".to_string(),
                "--note=対応完了しました".to_string(),
            ]
        );
    }

    #[test]
    fn build_human_done_args_note_with_leading_hyphen_stays_one_token() {
        let args = build_human_done_args("m123", "t1", "-手動で回避策を実施");
        assert_eq!(args[3], "--note=-手動で回避策を実施");
        assert_eq!(args.len(), 4, "noteは分割されず単一トークンのまま");
    }

    #[test]
    fn build_human_done_args_note_with_whitespace_and_newlines() {
        let note = "対応内容:\n  - 再起動\n  - ログ確認";
        let args = build_human_done_args("m123", "t1", note);
        assert_eq!(args[3], format!("--note={note}"));
        assert_eq!(args.len(), 4);
    }
}
