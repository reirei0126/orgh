//! orgh CLI呼び出しの共通ラッパ。
//!
//! 方針(タスク指示): Rust側はorghのPythonロジックを再実装せず、`orgh` を
//! サブプロセスとして起動しJSON出力をパースする薄いブリッジに徹する。

use crate::models::{CliError, MissionLogEvent, MissionUpdatedEvent};
use crate::settings::Settings;
use serde::de::DeserializeOwned;
use std::io::{BufRead, BufReader};
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread;
use tauri::{AppHandle, Emitter};

/// `orgh <cmd> ... --json` の生の実行結果(stdout/stderr/終了成否)を、
/// 期待する構造体 `T` か、`{"error": "..."}` 形式か、
/// どちらにも当てはまらない場合はstderr/終了コードから
/// 人間可読なメッセージへ解釈する。プロセス実行から切り離した純関数にして
/// あるので、固定文字列を入力にした単体テストが書ける。
///
/// 判定はまず「stdoutがTとしてパースできるか」を試す。doctorのように
/// `ok: false` でも終了コードが非0になりつつ完全な構造化JSONを吐くコマンド
/// (desktop/API.md 1.3)があるため、終了コードより先にJSON形状で成否を
/// 判定する。
pub fn interpret_response<T: DeserializeOwned>(
    stdout: &str,
    stderr: &str,
    success: bool,
) -> Result<T, String> {
    let trimmed = stdout.trim();

    if let Ok(value) = serde_json::from_str::<T>(trimmed) {
        return Ok(value);
    }
    if let Ok(err) = serde_json::from_str::<CliError>(trimmed) {
        return Err(err.error);
    }

    let stderr_trimmed = stderr.trim();
    if !stderr_trimmed.is_empty() {
        return Err(stderr_trimmed.to_string());
    }
    if success {
        Err(format!("orghの出力をJSONとして解釈できない: {trimmed}"))
    } else if trimmed.is_empty() {
        Err("orghが非0終了コードで終了した(stdout/stderrともに空)".to_string())
    } else {
        Err(format!("orghが非0終了コードで終了した。stdout: {trimmed}"))
    }
}

/// 読み取り系コマンド(list/status/events/doctor)の共通実行部。
/// `orgh --config <configPath> <args...>` を同期実行しJSONをデシリアライズする。
pub fn run_json<T: DeserializeOwned>(settings: &Settings, args: &[&str]) -> Result<T, String> {
    let output = Command::new(&settings.orgh_bin)
        .arg("--config")
        .arg(&settings.config_path)
        .args(args)
        .output()
        .map_err(|e| format!("'{}' の起動に失敗: {e}", settings.orgh_bin))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    interpret_response(&stdout, &stderr, output.status.success())
}

/// JSON出力を持たない短命コマンド(cancel等)の共通実行部。
/// 非0終了時はstderr(なければ終了コード)を含む`Err`を返す。
pub fn run_sync(settings: &Settings, args: &[&str]) -> Result<(), String> {
    let output = Command::new(&settings.orgh_bin)
        .arg("--config")
        .arg(&settings.config_path)
        .args(args)
        .output()
        .map_err(|e| format!("'{}' の起動に失敗: {e}", settings.orgh_bin))?;

    if output.status.success() {
        return Ok(());
    }
    let stderr = String::from_utf8_lossy(&output.stderr);
    if !stderr.trim().is_empty() {
        Err(stderr.trim().to_string())
    } else {
        Err(format!("orgh exited with status {}", output.status))
    }
}

/// `start_mission` / `approve_mission` 用の長時間子プロセス起動(desktop/API.md 3.1)。
///
/// `known_mission_id` が `None` (start_mission) の場合: stdoutを1行ずつ読み、
/// `ORGH_MISSION_ID=<id>` 行を検出するまでは `mission-log { missionId: null }` を
/// emitし続け、検出した時点で `mission-updated` を1回emitして戻り値を確定させる。
/// `Some(id)` (approve_mission) の場合: mission_idは既知なので、子プロセスを
/// spawnした直後に即座に確定値を返す。
///
/// 戻り値確定後も子プロセスはバックグラウンドで動き続け、stdout/stderrの残りを
/// `mission-log` として流し続け、プロセス終了時に `mission-updated` を最低1回
/// emitする(desktop/API.md 3.1の(4)(5))。
pub fn spawn_and_bridge(
    app: AppHandle,
    program: String,
    args: Vec<String>,
    known_mission_id: Option<String>,
) -> Result<String, String> {
    let mut child = Command::new(&program)
        .args(&args)
        // Pythonはpipe接続時にstdoutをブロックバッファリングするため、
        // ORGH_MISSION_ID行の即時受信には非バッファ出力の強制が必須
        .env("PYTHONUNBUFFERED", "1")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("'{program}' の起動に失敗: {e}"))?;

    let stdout = child
        .stdout
        .take()
        .expect("stdoutはStdio::pipedで確保済みのはず");
    let stderr = child
        .stderr
        .take()
        .expect("stderrはStdio::pipedで確保済みのはず");

    let mission_id: Arc<Mutex<Option<String>>> = Arc::new(Mutex::new(known_mission_id.clone()));
    // ID検出前に子プロセスが死んだとき、原因(config不正・note不在等)は
    // stderrにしか出ない。イベントとして流すだけだと失われるため末尾を保持する
    let stderr_tail: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
    let (id_tx, id_rx) = mpsc::channel::<Result<String, String>>();

    // mission_idが既知(approve_mission)なら、待受(id_rx.recv)がすぐ解決するよう
    // ここで確定させておく。
    if let Some(id) = &known_mission_id {
        let _ = id_tx.send(Ok(id.clone()));
    }

    // stderr: mission_idの検出はstdout側の役割。現在判明している値でそのままemit。
    {
        let app = app.clone();
        let mission_id = Arc::clone(&mission_id);
        let stderr_tail = Arc::clone(&stderr_tail);
        thread::spawn(move || {
            let reader = BufReader::new(stderr);
            for line in reader.lines().map_while(Result::ok) {
                {
                    let mut tail = stderr_tail.lock().expect("stderr_tail mutex poisoned");
                    tail.push(line.clone());
                    // 保持は末尾20行まで(エラー原因の特定に十分な範囲で無限成長を防ぐ)
                    if tail.len() > 20 {
                        tail.remove(0);
                    }
                }
                let mid = mission_id.lock().expect("mission_id mutex poisoned").clone();
                let _ = app.emit(
                    "mission-log",
                    MissionLogEvent {
                        mission_id: mid,
                        line,
                    },
                );
            }
        });
    }

    // stdout: ORGH_MISSION_ID=<id> 行を検出し、確定・mission-updated発火・id_tx通知を行う。
    {
        let app = app.clone();
        let mission_id = Arc::clone(&mission_id);
        let id_tx = id_tx.clone();
        let already_known = known_mission_id.is_some();
        thread::spawn(move || {
            let reader = BufReader::new(stdout);
            let mut detected_now = false;
            for line in reader.lines().map_while(Result::ok) {
                if !already_known && !detected_now {
                    if let Some(id) = line.strip_prefix("ORGH_MISSION_ID=") {
                        let id = id.trim().to_string();
                        *mission_id.lock().expect("mission_id mutex poisoned") = Some(id.clone());
                        let _ = app.emit(
                            "mission-updated",
                            MissionUpdatedEvent {
                                mission_id: id.clone(),
                            },
                        );
                        let _ = id_tx.send(Ok(id));
                        detected_now = true;
                    }
                }
                // このORGH_MISSION_ID行自体もconfirmation行として確定id付きで流す
                // (desktop/API.md 3.1: 「confirmationの行を含め、以降すべて確定したidを使う」)。
                let mid = mission_id.lock().expect("mission_id mutex poisoned").clone();
                let _ = app.emit(
                    "mission-log",
                    MissionLogEvent {
                        mission_id: mid,
                        line,
                    },
                );
            }
        });
    }

    // プロセス終了待ち。簡易実装: mission.jsonのポーリングではなく、
    // 子プロセスの終了(child.wait())をそのままmission-updatedの発火契機にする
    // (desktop/API.md 3.2が明示的に許容する最小保証のみを満たす実装)。
    // よりリアルタイムな進捗反映が要る場合は、ここをN秒おきの
    // `runs/<id>/mission.json` ポーリングに差し替える余地がある。
    {
        let app = app.clone();
        let mission_id = Arc::clone(&mission_id);
        thread::spawn(move || {
            let status = child.wait();
            let mid = mission_id.lock().expect("mission_id mutex poisoned").clone();
            match mid {
                Some(mid) => {
                    let _ = app.emit("mission-updated", MissionUpdatedEvent { mission_id: mid });
                }
                None => {
                    // ORGH_MISSION_ID行を一度も出さずに終了した(start_mission異常系)。
                    // stderr末尾を含めて本来の失敗理由(config不正・note不在等)を返す
                    let mut msg = match status {
                        Ok(s) if !s.success() => {
                            format!("orgh runがORGH_MISSION_IDを出力せずに終了した (status={s})")
                        }
                        Ok(_) => {
                            "orgh runがORGH_MISSION_IDを出力せずに正常終了した".to_string()
                        }
                        Err(e) => format!("子プロセスの終了待ちに失敗: {e}"),
                    };
                    let tail = stderr_tail
                        .lock()
                        .expect("stderr_tail mutex poisoned")
                        .join("\n");
                    if !tail.trim().is_empty() {
                        msg.push_str(&format!("\n--- stderr ---\n{tail}"));
                    }
                    let _ = id_tx.send(Err(msg));
                }
            }
        });
    }

    id_rx
        .recv()
        .map_err(|_| "orghプロセスとの通信が切断された".to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::{DoctorReport, ListPayload};

    #[test]
    fn parses_success_payload() {
        let stdout = r#"{"missions": []}"#;
        let result: Result<ListPayload, String> = interpret_response(stdout, "", true);
        assert!(result.is_ok());
        assert!(result.unwrap().missions.is_empty());
    }

    #[test]
    fn parses_error_object_on_failure() {
        let stdout = r#"{"error": "mission 'xyz' not found"}"#;
        let result: Result<ListPayload, String> = interpret_response(stdout, "", false);
        assert_eq!(result.unwrap_err(), "mission 'xyz' not found");
    }

    #[test]
    fn doctor_ok_false_still_parses_as_structured_report_despite_nonzero_exit() {
        // desktop/API.md 1.3: ok:falseのときCLIの終了コードは非0だが、
        // stdoutはerrorオブジェクトではなく完全なDoctorReportのまま。
        let stdout = r#"{"ok": false, "checks": [{"name": "config", "ok": false, "detail": "missing"}]}"#;
        let result: Result<DoctorReport, String> = interpret_response(stdout, "", false);
        let report = result.expect("ok:falseでもErrにならずDoctorReportとして返るべき");
        assert!(!report.ok);
        assert_eq!(report.checks.len(), 1);
        assert_eq!(report.checks[0].name, "config");
    }

    #[test]
    fn falls_back_to_stderr_when_stdout_is_unparseable() {
        let result: Result<ListPayload, String> =
            interpret_response("", "boom: something broke", false);
        assert_eq!(result.unwrap_err(), "boom: something broke");
    }

    #[test]
    fn falls_back_to_exit_status_message_when_no_stderr_and_empty_stdout() {
        let result: Result<ListPayload, String> = interpret_response("", "", false);
        assert!(result.unwrap_err().contains("非0終了コード"));
    }
}
