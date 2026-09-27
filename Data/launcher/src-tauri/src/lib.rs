mod commands;

use std::path::PathBuf;
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use leviathan_host_core::paths::{discover_install_root, launcher_log_dir};
use leviathan_host_core::single_instance::{InstanceLock, InstanceLockError};
use leviathan_host_core::{HostController, OwnershipKind};
use tauri::{Emitter, Manager, WindowEvent};

pub fn run() {
    let exe = std::env::current_exe().unwrap_or_else(|_| PathBuf::from("."));
    let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let root = discover_install_root(&exe, &cwd).unwrap_or(cwd);
    let lock_path = launcher_log_dir(&root).join("instance.lock");
    let lock = match InstanceLock::acquire(&lock_path) {
        Ok(lock) => lock,
        Err(InstanceLockError::AlreadyRunning { pid }) => {
            eprintln!(
                "run_leviathan is already running (pid={}). This process will exit without starting another backend.",
                pid.map(|value| value.to_string()).unwrap_or_else(|| "unknown".into())
            );
            std::process::exit(0);
        }
        Err(InstanceLockError::Io(err)) => {
            eprintln!("single-instance lock failed: {err}");
            std::process::exit(1);
        }
    };

    let controller = Arc::new(HostController::new(root, env!("CARGO_PKG_VERSION")));
    controller.probe_existing();
    let poller = Arc::clone(&controller);

    tauri::Builder::default()
        .manage(controller)
        .manage(lock)
        .setup(move |app| {
            let handle = app.handle().clone();
            if let Some(window) = app.get_webview_window("main") {
                let owned = Arc::clone(&poller);
                let emitter = handle.clone();
                window.on_window_event(move |event| {
                    if let WindowEvent::CloseRequested { api, .. } = event {
                        let snap = owned.snapshot();
                        let live = snap.ownership == OwnershipKind::Owned
                            && matches!(snap.state.as_str(), "RUNNING" | "STARTING" | "DEGRADED" | "PREFLIGHT" | "STOPPING");
                        if live {
                            api.prevent_close();
                            let _ = emitter.emit("host://close-requested", &snap);
                        }
                    }
                });
            }
            thread::spawn(move || {
                let mut seq = 0_u64;
                loop {
                    poller.poll_once();
                    let lines = poller.console_after(seq, 400);
                    if let Some(last) = lines.last() {
                        seq = last.seq;
                    }
                    if !lines.is_empty() {
                        let _ = handle.emit("host://console", &lines);
                    }
                    let snap = poller.snapshot();
                    let _ = handle.emit("host://state", &snap);
                    if snap.exit_when_stopped
                        && (snap.ownership != OwnershipKind::Owned
                            || snap.state == "STOPPED"
                            || snap.state == "FAILED")
                    {
                        handle.exit(0);
                    }
                    thread::sleep(Duration::from_millis(400));
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::host_snapshot,
            commands::host_preflight,
            commands::host_start,
            commands::host_stop,
            commands::host_restart,
            commands::host_emergency,
            commands::host_confirm_close,
            commands::host_open,
            commands::host_console,
            commands::host_preferences_get,
            commands::host_preferences_set
        ])
        .run(tauri::generate_context!())
        .expect("failed to run LEVIATHAN backend host");
}
