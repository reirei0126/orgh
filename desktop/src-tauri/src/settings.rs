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

pub fn save_settings(app: &tauri::AppHandle, settings: &Settings) -> Result<(), String> {
    let path = settings_file_path(app)?;
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("設定ディレクトリの作成に失敗: {e}"))?;
    }
    let data =
        serde_json::to_string_pretty(settings).map_err(|e| format!("設定のシリアライズに失敗: {e}"))?;
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
