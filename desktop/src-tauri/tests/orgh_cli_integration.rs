//! `orgh` CLIを実際に子プロセスとして起動し、`--json` 出力を
//! `orgh_desktop_lib::cli` でパースできることを検証する統合テスト
//! (desktop/API.md 1章の契約を実物のCLIに対して確認する)。
//!
//! orghがPATHに見つからない場合はスキップせず、リポジトリの `.venv/bin/orgh`
//! を試したうえで、それも無ければ環境不備としてテストを失敗させる。

use orgh_desktop_lib::cli;
use orgh_desktop_lib::commands::{build_playbooks_args, build_report_args, build_resume_args};
use orgh_desktop_lib::models::{
    DoctorReport, EventsPayload, ListPayload, PlaybookPayload, ReportPayload,
};
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
        format!(
            "workers: {{}}\nruns_dir: {:?}\n",
            runs_dir.to_string_lossy()
        ),
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

    let payload: EventsPayload =
        cli::run_json(&settings, &["events", "m2", "--json", "--tail", "100"])
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

    let payload: EventsPayload =
        cli::run_json(&settings, &["events", "m3", "--json", "--tail", "100"])
            .expect("orgh events --json should succeed");
    assert_eq!(payload.events.len(), 2);
    assert_eq!(payload.events[0].event, "task.start");
    assert_eq!(
        payload.events[0]
            .extra
            .get("worker")
            .and_then(|v| v.as_str()),
        Some("claude_code")
    );
    assert_eq!(payload.events[1].event, "task.output");
    assert_eq!(
        payload.events[1].extra.get("ok").and_then(|v| v.as_bool()),
        Some(true)
    );
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

#[test]
fn doctor_old_json_defaults_authentication_fields() {
    let report: DoctorReport = serde_json::from_str(
        r#"{"ok":true,"checks":[{"name":"config","ok":true,"detail":"valid"}]}"#,
    )
    .expect("old doctor JSON should remain parseable");

    assert_eq!(report.checks[0].kind, "connectivity");
    assert_eq!(report.checks[0].auth_state, "n/a");
}

#[test]
fn report_invokes_stub_with_days_and_parses_payload() {
    let tmp = tempfile::tempdir().unwrap();
    let (settings, args_file) = stub_settings(
        tmp.path(),
        r#"{"days":7,"weekly":[{"week":"2026-W32","total":4,"first_pass":3,"first_pass_pct":75,"rework":1,"rework_pct":25}],"missions":[{"mission_id":"m1","intent":"full intent","cost_usd":1.25,"duration_sec":42,"tasks_done":3,"tasks_total":4}],"workers":[{"worker":"codex","failed":1,"total":4,"failed_pct":25}]}"#,
    );
    let args = build_report_args(7);
    let refs: Vec<&str> = args.iter().map(String::as_str).collect();

    let payload: ReportPayload = cli::run_json(&settings, &refs).unwrap();

    assert_eq!(
        std::fs::read_to_string(args_file).unwrap(),
        "--config\nconfig.yaml\nreport\n--days\n7\n--json\n"
    );
    assert_eq!(payload.weekly[0].first_pass_pct, 75);
    assert_eq!(payload.missions[0].mission_id, "m1");
    assert_eq!(payload.workers[0].failed_pct, 25);
}

#[test]
fn playbooks_invokes_stub_and_parses_payload() {
    let tmp = tempfile::tempdir().unwrap();
    let (settings, args_file) = stub_settings(
        tmp.path(),
        r##"{"playbooks":[{"name":"coding","path":"/tmp/coding.md","body":"# Coding\n- Keep tests\n","entries":[{"text":"Keep tests","mission_id":null,"date":null}]}]}"##,
    );
    let args = build_playbooks_args();
    let refs: Vec<&str> = args.iter().map(String::as_str).collect();

    let payload: PlaybookPayload = cli::run_json(&settings, &refs).unwrap();

    assert_eq!(
        std::fs::read_to_string(args_file).unwrap(),
        "--config\nconfig.yaml\nplaybooks\n--json\n"
    );
    assert_eq!(payload.playbooks[0].name, "coding");
    assert_eq!(payload.playbooks[0].entries[0].mission_id, None);
}

#[test]
fn resume_args_include_config_and_optional_retry_flag() {
    let settings = Settings {
        orgh_bin: "orgh".into(),
        config_path: "/tmp/config.yaml".into(),
        runs_dir: "/tmp/runs".into(),
    };

    assert_eq!(
        build_resume_args(&settings, "m1", false),
        vec!["--config", "/tmp/config.yaml", "resume", "m1"]
    );
    assert_eq!(
        build_resume_args(&settings, "m1", true),
        vec![
            "--config",
            "/tmp/config.yaml",
            "resume",
            "m1",
            "--retry-failed"
        ]
    );
}

#[cfg(unix)]
fn stub_settings(dir: &std::path::Path, stdout_json: &str) -> (Settings, PathBuf) {
    use std::os::unix::fs::PermissionsExt;

    let script = dir.join("orgh-stub");
    let args_file = dir.join("args.txt");
    std::fs::write(
        &script,
        format!(
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > {:?}\nprintf '%s\\n' '{}'\n",
            args_file,
            stdout_json.replace('\'', "'\\''")
        ),
    )
    .unwrap();
    let mut permissions = std::fs::metadata(&script).unwrap().permissions();
    permissions.set_mode(0o755);
    std::fs::set_permissions(&script, permissions).unwrap();
    (
        Settings {
            orgh_bin: script.to_string_lossy().into_owned(),
            config_path: "config.yaml".into(),
            runs_dir: "runs".into(),
        },
        args_file,
    )
}
