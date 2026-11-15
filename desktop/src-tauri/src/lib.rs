mod startup;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use startup::StartupStatus;
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, RunEvent, Url, WebviewWindow, WindowEvent,
};
use tauri_plugin_autostart::MacosLauncher;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const API_PORT: u16 = 8765;
const API_URL: &str = "http://127.0.0.1:8765";

struct ApiSidecar {
    child: Mutex<Option<CommandChild>>,
    status: Mutex<StartupStatus>,
    startup_url: Url,
    stopping: AtomicBool,
}

fn require_startup_window(window: &WebviewWindow, runtime: &ApiSidecar) -> Result<(), String> {
    let url = window.url().map_err(|_| "Could not identify the startup window.")?;
    if window.label() != "main" || url != runtime.startup_url {
        return Err("Startup controls are only available in the bundled startup page.".into());
    }
    Ok(())
}

#[tauri::command]
fn desktop_startup_status(window: WebviewWindow, app_handle: tauri::AppHandle) -> Result<StartupStatus, String> {
    let runtime = app_handle.state::<ApiSidecar>();
    require_startup_window(&window, &runtime)?;
    let status = runtime.status.lock().map_err(|_| "Could not read startup status.")?;
    Ok(status.clone())
}

#[tauri::command]
fn retry_desktop_startup(window: WebviewWindow, app_handle: tauri::AppHandle) -> Result<(), String> {
    let runtime = app_handle.state::<ApiSidecar>();
    require_startup_window(&window, &runtime)?;
    {
        let status = runtime.status.lock().map_err(|_| "Could not read startup status.")?;
        if status.phase != "failed" {
            return Err("The workspace is still opening. Please wait.".into());
        }
    }
    request_restart(app_handle.clone());
    Ok(())
}

#[tauri::command]
fn quit_desktop_startup(window: WebviewWindow, app_handle: tauri::AppHandle) -> Result<(), String> {
    let runtime = app_handle.state::<ApiSidecar>();
    require_startup_window(&window, &runtime)?;
    app_handle.exit(0);
    Ok(())
}

fn request_restart(app_handle: tauri::AppHandle) {
    // A user-triggered restart should reopen visibly even after hidden autostart.
    std::env::set_var("INTERNTRACK_SHOW_ON_RESTART", "1");
    std::thread::spawn(move || {
        std::thread::sleep(Duration::from_millis(250));
        app_handle.request_restart();
    });
}

#[tauri::command]
fn restart_for_pending_restore(app_handle: tauri::AppHandle) -> Result<(), String> {
    let data_directory = app_handle.path().app_local_data_dir().map_err(|error| error.to_string())?;
    if !data_directory.join("pending-restore.db").is_file() {
        return Err("No verified restore is waiting to be applied.".to_string());
    }
    request_restart(app_handle);
    Ok(())
}

fn show_main_window(app_handle: &tauri::AppHandle) {
    if let Some(window) = app_handle.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn startup_failed(app_handle: &tauri::AppHandle, code: &'static str, message: &'static str) {
    let runtime = app_handle.state::<ApiSidecar>();
    if runtime.stopping.load(Ordering::SeqCst) {
        return;
    }
    if let Ok(mut status) = runtime.status.lock() {
        if status.phase == "failed" {
            return;
        }
        *status = StartupStatus::failed(code, message);
    } else {
        return;
    }
    let ui_app = app_handle.clone();
    let _ = app_handle.run_on_main_thread(move || {
        let runtime = ui_app.state::<ApiSidecar>();
        if runtime.stopping.load(Ordering::SeqCst) {
            return;
        }
        if let Some(window) = ui_app.get_webview_window("main") {
            let _ = window.navigate(runtime.startup_url.clone());
            show_main_window(&ui_app);
        }
    });
}

fn wait_for_api(app_handle: tauri::AppHandle, show_on_ready: bool, instance_id: String) {
    std::thread::spawn(move || {
        let client = match startup::probe_client(Duration::from_secs(1)) {
            Ok(client) => client,
            Err(_) => {
                startup_failed(&app_handle, "readiness-check", "The local startup check could not be created. Retry opening InternTrack.");
                return;
            }
        };
        let version = app_handle.package_info().version.to_string();
        let deadline = Instant::now() + Duration::from_secs(60);
        loop {
            let runtime = app_handle.state::<ApiSidecar>();
            if runtime.stopping.load(Ordering::SeqCst) {
                return;
            }
            if runtime.status.lock().map(|status| status.phase != "starting").unwrap_or(true) {
                return;
            }
            if startup::api_ready(&client, API_URL, &version, &instance_id) {
                {
                    let mut status = match runtime.status.lock() {
                        Ok(status) => status,
                        Err(_) => return,
                    };
                    if status.phase != "starting" {
                        return;
                    }
                    *status = StartupStatus::ready();
                }
                let ui_app = app_handle.clone();
                let _ = app_handle.run_on_main_thread(move || {
                    let runtime = ui_app.state::<ApiSidecar>();
                    if runtime.stopping.load(Ordering::SeqCst)
                        || runtime.status.lock().map(|status| status.phase != "ready").unwrap_or(true)
                    {
                        return;
                    }
                    let navigated = ui_app.get_webview_window("main")
                        .and_then(|window| Url::parse(API_URL).ok().map(|url| window.navigate(url).is_ok()))
                        .unwrap_or(false);
                    if !navigated {
                        startup_failed(&ui_app, "window-navigation", "Your local service opened, but the tracker window could not load. Retry opening InternTrack.");
                    } else if show_on_ready {
                        show_main_window(&ui_app);
                    }
                });
                return;
            }
            if Instant::now() >= deadline {
                startup_failed(&app_handle, "startup-timeout", "Your local workspace did not finish opening within a minute. Retry, or quit and reopen InternTrack.");
                return;
            }
            std::thread::sleep(Duration::from_millis(200));
        }
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            restart_for_pending_restore, desktop_startup_status,
            retry_desktop_startup, quit_desktop_startup,
        ])
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show_main_window(app);
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_autostart::init(MacosLauncher::LaunchAgent, Some(vec!["--hidden"])))
        .setup(|app| {
            let show_on_restart = std::env::var_os("INTERNTRACK_SHOW_ON_RESTART").is_some();
            std::env::remove_var("INTERNTRACK_SHOW_ON_RESTART");
            let start_hidden = !show_on_restart && std::env::args().any(|argument| argument == "--hidden");
            let window = app.get_webview_window("main").ok_or("The main window is missing.")?;
            let startup_url = window.url()?;
            app.manage(ApiSidecar {
                child: Mutex::new(None),
                status: Mutex::new(StartupStatus::starting()),
                startup_url,
                stopping: AtomicBool::new(false),
            });
            if start_hidden {
                let _ = window.hide();
            }

            let open_item = MenuItem::with_id(app, "open", "Open InternTrack", true, None::<&str>)?;
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
                    if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                        show_main_window(tray.app_handle());
                    }
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;

            if !startup::port_available(API_PORT) {
                startup_failed(app.handle(), "port-unavailable", "Local port 8765 is already in use or unavailable. Close another InternTrack copy or the app using that port, then retry.");
                return Ok(());
            }
            let data_directory = match app.path().app_local_data_dir() {
                Ok(directory) => directory,
                Err(_) => {
                    startup_failed(app.handle(), "workspace-location", "Windows could not locate your local workspace folder. Retry opening InternTrack.");
                    return Ok(());
                }
            };
            if std::fs::create_dir_all(&data_directory).is_err() {
                startup_failed(app.handle(), "workspace-access", "Windows could not open your local workspace folder. Check that your Windows account can access it, then retry.");
                return Ok(());
            }

            // Correlate the HTTP response with this launch; this is not an account credential.
            let instance_id = format!("{}-{}", std::process::id(), SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos());
            let sidecar = match app.shell().sidecar("interntrack-api") {
                Ok(command) => command,
                Err(_) => {
                    startup_failed(app.handle(), "service-missing", "InternTrack's local service is missing. Reinstall the app from its trusted download and retry.");
                    return Ok(());
                }
            };
            let spawned = sidecar.args([
                "--port".to_string(), API_PORT.to_string(),
                "--data-dir".to_string(), data_directory.to_string_lossy().to_string(),
            ])
                .env("DESKTOP_INSTANCE_ID", &instance_id)
                .set_process_group(true)
                .kill_on_drop(true)
                .spawn();
            let (mut events, child) = match spawned {
                Ok(spawned) => spawned,
                Err(_) => {
                    startup_failed(app.handle(), "service-launch", "Windows could not start InternTrack's local service. Retry, or reinstall the app if this keeps happening.");
                    return Ok(());
                }
            };
            *app.state::<ApiSidecar>().child.lock().unwrap() = Some(child);

            let event_app = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                while let Some(event) = events.recv().await {
                    match event {
                        CommandEvent::Stderr(bytes) => eprintln!("{}", String::from_utf8_lossy(&bytes)),
                        CommandEvent::Terminated(_) | CommandEvent::Error(_) => {
                            startup_failed(&event_app, "service-stopped", "InternTrack's local service stopped. Retry to reopen the workspace. Your local account and records have not been reset.");
                            return;
                        }
                        _ => {}
                    }
                }
            });
            wait_for_api(app.handle().clone(), !start_hidden, instance_id);
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
            let runtime = app_handle.state::<ApiSidecar>();
            runtime.stopping.store(true, Ordering::SeqCst);
            if let Ok(mut child) = runtime.child.lock() {
                if let Some(child) = child.take() {
                    let _ = child.kill();
                }
            };
        }
    });
}
