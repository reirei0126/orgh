//! GUI設定 (`orghBin`/`configPath`/`runsDir`) の永続化。
//!
//! 永続化先はTauriのアプリconfigディレクトリ(`AppHandle::path().app_config_dir()`)
//! 配下の `settings.json`。全コマンドはこの設定の `orgh_bin` を使ってCLIを起動する
//! (desktop/API.md 2章)。

use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use tauri::Manager;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Settings {
    pub orgh_bin: String,
    pub config_path: String,
    pub runs_dir: String,
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            orgh_bin: "orgh".to_string(),
            config_path: "config.yaml".to_string(),
            runs_dir: "runs".to_string(),
        }
    }
}

fn settings_file_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_config_dir()
        .map_err(|e| format!("設定ディレクトリの解決に失敗: {e}"))?;
    Ok(dir.join("settings.json"))
}

pub fn load_settings(app: &tauri::AppHandle) -> Result<Settings, String> {
    let path = settings_file_path(app)?;
    if !path.exists() {
        return Ok(Settings::default());
    }
    let data = std::fs::read_to_string(&path).map_err(|e| format!("設定の読み込みに失敗: {e}"))?;
    serde_json::from_str(&data).map_err(|e| format!("設定ファイルの形式が不正: {e}"))
}

/// 保存前の妥当性検証。壊れた接続設定を無検証で永続化すると、以後
/// list/doctor/runを含む全コマンドが起動不能になり設定画面以外が使えなくなる。
fn validate_settings(settings: &Settings) -> Result<(), String> {
    let orgh_bin = settings.orgh_bin.trim();
    let config_path = settings.config_path.trim();
    let runs_dir = settings.runs_dir.trim();
    if orgh_bin.is_empty() {
        return Err("orghBin が空です".to_string());
    }
    if config_path.is_empty() {
        return Err("configPath が空です".to_string());
    }
    if runs_dir.is_empty() {
        return Err("runsDir が空です".to_string());
    }
    let bin_path = std::path::Path::new(orgh_bin);
    if bin_path.is_absolute() && !bin_path.is_file() {
        return Err(format!("orghBin が存在しません: {orgh_bin}"));
    }
    // 相対名(PATH解決)の実在確認は起動時のdoctorに委ねる。
    // configPathは絶対パス指定なら通常ファイルであることを確認する
    let cfg_path = std::path::Path::new(config_path);
    if cfg_path.is_absolute() && !cfg_path.is_file() {
        return Err(format!("configPath が存在しません: {config_path}"));
    }
    Ok(())
}

/// 前後空白を除去した正規形。検証と保存は必ずこの正規形に対して行う
/// (trim後の値で検証して未加工値を保存すると、空白付きパスが永続化されて
/// 以後の全CLI起動が失敗する)。
fn normalized(settings: &Settings) -> Settings {
    Settings {
        orgh_bin: settings.orgh_bin.trim().to_string(),
        config_path: settings.config_path.trim().to_string(),
        runs_dir: settings.runs_dir.trim().to_string(),
    }
}

pub fn save_settings(app: &tauri::AppHandle, settings: &Settings) -> Result<(), String> {
    let settings = normalized(settings);
    validate_settings(&settings)?;
    let path = settings_file_path(app)?;
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("設定ディレクトリの作成に失敗: {e}"))?;
    }
    let data = serde_json::to_string_pretty(&settings)
        .map_err(|e| format!("設定のシリアライズに失敗: {e}"))?;
    std::fs::write(&path, data).map_err(|e| format!("設定の書き込みに失敗: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_settings_match_cli_defaults() {
        let s = Settings::default();
        assert_eq!(s.orgh_bin, "orgh");
        assert_eq!(s.config_path, "config.yaml");
        assert_eq!(s.runs_dir, "runs");
    }

    #[test]
    fn validate_rejects_empty_fields() {
        for (bin, cfg, runs) in [
            ("", "config.yaml", "runs"),
            ("orgh", "  ", "runs"),
            ("orgh", "config.yaml", ""),
        ] {
            let s = Settings {
                orgh_bin: bin.to_string(),
                config_path: cfg.to_string(),
                runs_dir: runs.to_string(),
            };
            assert!(
                validate_settings(&s).is_err(),
                "should reject {bin:?}/{cfg:?}/{runs:?}"
            );
        }
    }

    #[test]
    fn validate_rejects_missing_absolute_paths() {
        let s = Settings {
            orgh_bin: "/no/such/orgh-bin".to_string(),
            config_path: "config.yaml".to_string(),
            runs_dir: "runs".to_string(),
        };
        assert!(validate_settings(&s).is_err());
        let s2 = Settings {
            orgh_bin: "orgh".to_string(),
            config_path: "/no/such/config.yaml".to_string(),
            runs_dir: "runs".to_string(),
        };
        assert!(validate_settings(&s2).is_err());
    }

    #[test]
    fn validate_accepts_relative_command_names() {
        assert!(validate_settings(&Settings::default()).is_ok());
    }

    #[test]
    fn normalized_strips_surrounding_whitespace() {
        let s = Settings {
            orgh_bin: "  orgh ".to_string(),
            config_path: "\tconfig.yaml\n".to_string(),
            runs_dir: " runs ".to_string(),
        };
        assert_eq!(normalized(&s), Settings::default());
    }

    #[test]
    fn settings_roundtrip_camel_case_json() {
        let s = Settings {
            orgh_bin: "/usr/local/bin/orgh".to_string(),
            config_path: "/tmp/config.yaml".to_string(),
            runs_dir: "/tmp/runs".to_string(),
        };
        let json = serde_json::to_string(&s).unwrap();
        assert!(json.contains("\"orghBin\""));
        assert!(json.contains("\"configPath\""));
        assert!(json.contains("\"runsDir\""));
        let back: Settings = serde_json::from_str(&json).unwrap();
        assert_eq!(back, s);
    }
}
