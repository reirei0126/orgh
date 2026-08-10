//! `#[tauri::command]` 本体。desktop/API.md 2章のコマンドをここに置く。
//!
//! 読み取り系(list_missions/mission_status/mission_events/doctor)は
//! `cli::run_json` で同期実行してJSONをそのまま返す。
//! 長時間コマンドは `cli` の非同期ブリッジで実行し
//! イベント(mission-log/mission-updated)を発火する(desktop/API.md 3章)。

use tauri::AppHandle;

use crate::cli;
use crate::models::{
    DoctorReport, EventsPayload, LedgerEvent, ListPayload, MissionStatus, PlaybookPayload,
    ReportPayload,
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

#[tauri::command]
pub fn start_mission(
    app: AppHandle,
    intent: Option<String>,
    note: Option<String>,
) -> Result<String, String> {
    let settings = settings::load_settings(&app)?;
    let args = build_run_args(&settings, intent, note)?;
    cli::spawn_and_bridge(app, settings.orgh_bin.clone(), args, None, "ORGH_MISSION_ID=")
}

#[tauri::command]
pub fn approve_mission(app: AppHandle, mission_id: String) -> Result<(), String> {
    let settings = settings::load_settings(&app)?;
    let args = vec![
        "--config".to_string(),
        settings.config_path.clone(),
        "approve".to_string(),
        mission_id.clone(),
    ];
    cli::spawn_and_bridge(app, settings.orgh_bin.clone(), args, Some(mission_id), "ORGH_APPROVED=")
        .map(|_| ())
}

#[tauri::command]
pub fn resume_mission(
    app: AppHandle,
    mission_id: String,
    retry_failed: bool,
) -> Result<(), String> {
    let settings = settings::load_settings(&app)?;
    let args = build_resume_args(&settings, &mission_id, retry_failed);
    // resumeもapproveと同様に確認行(ORGH_RESUMED=)の検出まで成功を返さない。
    // 即Okだとロック競合等の失敗が成功として画面に見え、再クリックで失敗
    // プロセスを量産する
    cli::spawn_and_bridge(app, settings.orgh_bin.clone(), args, Some(mission_id), "ORGH_RESUMED=")
        .map(|_| ())
}

#[tauri::command]
pub fn cancel_mission(app: AppHandle, mission_id: String) -> Result<(), String> {
    let settings = settings::load_settings(&app)?;
    cli::run_sync(&settings, &["cancel", &mission_id])
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
}
