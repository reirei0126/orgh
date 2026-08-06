// このファイル以下 desktop/src-tauri/** は「Rustブリッジ実装タスク」が担当する。
// ここでは最小のhello(Tauriアプリを起動するだけ)を置く。
// Tauriコマンド・イベントの実装はdesktop/API.md契約に従うこと。
fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
