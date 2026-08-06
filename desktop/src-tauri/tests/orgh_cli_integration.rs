//! `orgh` CLIを実際に子プロセスとして起動し、`--json` 出力を
//! `orgh_desktop_lib::cli` でパースできることを検証する統合テスト
//! (desktop/API.md 1章の契約を実物のCLIに対して確認する)。
//!
//! orghがPATHに見つからない場合はスキップせず、リポジトリの `.venv/bin/orgh`
//! を試したうえで、それも無ければ環境不備としてテストを失敗させる。

use orgh_desktop_lib::cli;
use orgh_desktop_lib::models::{EventsPayload, ListPayload};
use orgh_desktop_lib::settings::Settings;
use std::path::PathBuf;

fn command_exists_in_path(name: &str) -> bool {
    std::env::var_os("PATH")
        .map(|paths| std::env::split_paths(&paths).any(|dir| dir.join(name).is_file()))
        .unwrap_or(false)
}

/// PATH上の`orgh`、無ければ`desktop/src-tauri`から見たリポジトリルートの
/// `.venv/bin/orgh` を探す。どちらも無ければテストを失敗させる
/// (タスク指示: 「テストをskipするのではなく...失敗させてよい」)。
fn resolve_orgh_bin() -> String {
    if command_exists_in_path("orgh") {
        return "orgh".to_string();
    }
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let candidate = manifest_dir.join("../../.venv/bin/orgh");
    assert!(
        candidate.is_file(),
        "orgh実行可能ファイルが見つからない。PATHにも{}にも無い。\
         リポジトリルートで `python3 -m venv .venv && .venv/bin/pip install -e .` を実行すること。",
        candidate.display()
    );
    candidate.to_string_lossy().to_string()
}

fn write_minimal_config(dir: &std::path::Path) -> String {
    let config_path = dir.join("config.yaml");
    let runs_dir = dir.join("runs");
    std::fs::create_dir_all(&runs_dir).unwrap();
    // runs_dirは相対パスだとcargo testのCWD基準で解決されてしまうため、
    // フィクスチャの隔離を保つために絶対パスで書く。
    std::fs::write(
        &config_path,
        format!("workers: {{}}\nruns_dir: {:?}\n", runs_dir.to_string_lossy()),
    )
    .unwrap();
    config_path.to_string_lossy().to_string()
}

fn settings_for(dir: &std::path::Path) -> Settings {
    Settings {
        orgh_bin: resolve_orgh_bin(),
        config_path: write_minimal_config(dir),
        runs_dir: dir.join("runs").to_string_lossy().to_string(),
    }
}

#[test]
fn list_missions_on_empty_runs_dir_returns_empty_array() {
    let tmp = tempfile::tempdir().unwrap();
    let settings = settings_for(tmp.path());

    let payload: ListPayload =
        cli::run_json(&settings, &["list", "--json"]).expect("orgh list --json should succeed");
    assert!(payload.missions.is_empty());
}

#[test]
fn list_missions_parses_a_real_mission_json_fixture() {
    let tmp = tempfile::tempdir().unwrap();
    let settings = settings_for(tmp.path());

    let mission_dir = tmp.path().join("runs").join("test1234");
    std::fs::create_dir_all(&mission_dir).unwrap();
    std::fs::write(
        mission_dir.join("mission.json"),
        r#"{
            "id": "test1234",
            "intent": "Test intent for bridge integration test",
            "tasks": [{"id": "t1", "status": "done"}],
            "budget": {"spent_usd": 0.42}
        }"#,
    )
    .unwrap();

    let payload: ListPayload =
        cli::run_json(&settings, &["list", "--json"]).expect("orgh list --json should succeed");
    assert_eq!(payload.missions.len(), 1);
    let m = &payload.missions[0];
    assert_eq!(m.mission_id, "test1234");
    assert_eq!(m.intent, "Test intent for bridge integration test");
    assert_eq!(m.status, "done");
    assert_eq!(m.cost_usd, 0.42);
    assert_eq!(m.tasks_done, 1);
    assert_eq!(m.tasks_total, 1);
}

#[test]
fn mission_events_for_missing_mission_dir_is_an_error() {
    let tmp = tempfile::tempdir().unwrap();
    let settings = settings_for(tmp.path());

    let result: Result<EventsPayload, String> = cli::run_json(
        &settings,
        &["events", "does-not-exist", "--json", "--tail", "100"],
    );
    let err = result.expect_err("nonexistent mission dir should be an error");
    assert!(err.contains("does-not-exist"));
    assert!(err.contains("not found"));
}

#[test]
fn mission_events_without_ledger_file_returns_empty_events() {
    let tmp = tempfile::tempdir().unwrap();
    let settings = settings_for(tmp.path());

    let mission_dir = tmp.path().join("runs").join("m2");
    std::fs::create_dir_all(&mission_dir).unwrap();

    let payload: EventsPayload = cli::run_json(
        &settings,
        &["events", "m2", "--json", "--tail", "100"],
    )
    .expect("events for a mission dir with no ledger.jsonl should still succeed");
    assert!(payload.events.is_empty());
}

#[test]
fn mission_events_parses_ledger_lines_including_unknown_fields() {
    let tmp = tempfile::tempdir().unwrap();
    let settings = settings_for(tmp.path());

    let mission_dir = tmp.path().join("runs").join("m3");
    std::fs::create_dir_all(&mission_dir).unwrap();
    std::fs::write(
        mission_dir.join("ledger.jsonl"),
        "{\"ts\": 1733500000.123, \"event\": \"task.start\", \"task\": \"t1\", \"worker\": \"claude_code\", \"attempt\": 1}\n\
         {\"ts\": 1733500012.456, \"event\": \"task.output\", \"task\": \"t1\", \"ok\": true, \"cost\": 0.0031}\n",
    )
    .unwrap();

    let payload: EventsPayload = cli::run_json(
        &settings,
        &["events", "m3", "--json", "--tail", "100"],
    )
    .expect("orgh events --json should succeed");
    assert_eq!(payload.events.len(), 2);
    assert_eq!(payload.events[0].event, "task.start");
    assert_eq!(
        payload.events[0].extra.get("worker").and_then(|v| v.as_str()),
        Some("claude_code")
    );
    assert_eq!(payload.events[1].event, "task.output");
    assert_eq!(payload.events[1].extra.get("ok").and_then(|v| v.as_bool()), Some(true));
}

#[test]
fn doctor_real_invocation_parses_into_doctor_report() {
    let tmp = tempfile::tempdir().unwrap();
    let settings = settings_for(tmp.path());

    let report: orgh_desktop_lib::models::DoctorReport =
        cli::run_json(&settings, &["doctor", "--json"])
            .expect("orgh doctor --json should always return a structured report");
    assert!(!report.checks.is_empty());
}
