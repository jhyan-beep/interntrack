use std::net::{SocketAddr, TcpStream};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, RunEvent, Url, WindowEvent,
};
use tauri_plugin_autostart::MacosLauncher;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;


const API_PORT: u16 = 8765;
const API_URL: &str = "http://127.0.0.1:8765";

struct ApiSidecar(Mutex<Option<CommandChild>>);

fn show_main_window(app_handle: &tauri::AppHandle) {
    if let Some(window) = app_handle.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn wait_for_api(app_handle: tauri::AppHandle, show_on_ready: bool) {
    std::thread::spawn(move || {
        let address = SocketAddr::from(([127, 0, 0, 1], API_PORT));
        for _ in 0..150 {
            if TcpStream::connect_timeout(&address, Duration::from_millis(200)).is_ok() {
                if let Some(window) = app_handle.get_webview_window("main") {
                    if let Ok(url) = Url::parse(API_URL) {
                        let _ = window.navigate(url);
                    }
                    if show_on_ready {
                        show_main_window(&app_handle);
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
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec!["--hidden"]),
        ))
        .setup(|app| {
            let start_hidden = std::env::args().any(|argument| argument == "--hidden");
            let data_directory = app.path().app_local_data_dir()?;
            std::fs::create_dir_all(&data_directory)?;

            let open_item = MenuItem::with_id(
                app,
                "open",
                "Open InternTrack",
                true,
                None::<&str>,
            )?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let tray_menu = Menu::with_items(app, &[&open_item, &quit_item])?;
            let mut tray = TrayIconBuilder::new()
                .tooltip("InternTrack · local deadline reminders")
                .menu(&tray_menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app_handle, event| match event.id.as_ref() {
                    "open" => show_main_window(app_handle),
                    "quit" => app_handle.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_main_window(tray.app_handle());
                    }
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;

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

            if start_hidden {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.hide();
                }
            }
            wait_for_api(app.handle().clone(), !start_hidden);
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
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
