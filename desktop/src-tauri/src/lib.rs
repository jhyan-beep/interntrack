use std::net::{SocketAddr, TcpStream};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{Manager, RunEvent, Url};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;


const API_PORT: u16 = 8765;
const API_URL: &str = "http://127.0.0.1:8765";

struct ApiSidecar(Mutex<Option<CommandChild>>);

fn wait_for_api(app_handle: tauri::AppHandle) {
    std::thread::spawn(move || {
        let address = SocketAddr::from(([127, 0, 0, 1], API_PORT));
        for _ in 0..150 {
            if TcpStream::connect_timeout(&address, Duration::from_millis(200)).is_ok() {
                if let Some(window) = app_handle.get_webview_window("main") {
                    if let Ok(url) = Url::parse(API_URL) {
                        let _ = window.navigate(url);
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                }
                return;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let data_directory = app.path().app_local_data_dir()?;
            std::fs::create_dir_all(&data_directory)?;

            let sidecar = app
                .shell()
                .sidecar("interntrack-api")?
                .args([
                    "--port".to_string(),
                    API_PORT.to_string(),
                    "--data-dir".to_string(),
                    data_directory.to_string_lossy().to_string(),
                ]);
            let (mut events, child) = sidecar.spawn()?;
            app.manage(ApiSidecar(Mutex::new(Some(child))));

            tauri::async_runtime::spawn(async move {
                while let Some(event) = events.recv().await {
                    if let CommandEvent::Stderr(bytes) = event {
                        eprintln!("{}", String::from_utf8_lossy(&bytes));
                    }
                }
            });

            wait_for_api(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building InternTrack");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            let state = app_handle.state::<ApiSidecar>();
            if let Ok(mut sidecar) = state.0.lock() {
                if let Some(child) = sidecar.take() {
                    let _ = child.kill();
                }
            };
        }
    });
}
