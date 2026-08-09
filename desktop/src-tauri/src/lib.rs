// desktop/src-tauri/** はRustブリッジ実装タスクが担当する。
// Tauriコマンド・イベントの実装はdesktop/API.md契約に従うこと。

pub mod cli;
pub mod commands;
pub mod models;
pub mod settings;

pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            commands::list_missions,
            commands::mission_status,
            commands::mission_events,
            commands::start_mission,
            commands::approve_mission,
            commands::cancel_mission,
            commands::doctor,
            commands::get_settings,
            commands::set_settings,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
