use std::sync::Arc;

use leviathan_host_core::{ConsoleLine, HostController, HostSnapshot, UiPreferences};
use tauri::State;

/// Allowlisted host commands. There is intentionally no shell, exec, or arbitrary path command.
#[allow(non_snake_case)]

#[tauri::command]
pub fn host_snapshot(state: State<'_, Arc<HostController>>) -> HostSnapshot {
    state.snapshot()
}

#[tauri::command]
pub fn host_preflight(state: State<'_, Arc<HostController>>) -> HostSnapshot {
    let _ = state.preflight(false);
    state.snapshot()
}

#[tauri::command]
pub fn host_start(state: State<'_, Arc<HostController>>, safeMode: bool) -> Result<HostSnapshot, String> {
    state.start(safeMode).map_err(|err| err.message)
}

#[tauri::command]
pub fn host_stop(state: State<'_, Arc<HostController>>) -> Result<HostSnapshot, String> {
    state.stop().map_err(|err| err.message)
}

#[tauri::command]
pub fn host_restart(state: State<'_, Arc<HostController>>, safeMode: bool) -> Result<HostSnapshot, String> {
    state.restart(safeMode).map_err(|err| err.message)
}

#[tauri::command]
pub fn host_emergency(state: State<'_, Arc<HostController>>) -> Result<HostSnapshot, String> {
    state.emergency().map_err(|err| err.message)
}

#[tauri::command]
pub fn host_confirm_close(state: State<'_, Arc<HostController>>, stopOwned: bool) -> Result<HostSnapshot, String> {
    state.confirm_close(stopOwned).map_err(|err| err.message)
}

#[tauri::command]
pub fn host_open(state: State<'_, Arc<HostController>>, target: String) -> Result<String, String> {
    state.open_target(&target).map_err(|err| err.message)
}

#[tauri::command]
pub fn host_console(state: State<'_, Arc<HostController>>, after: u64, limit: u32) -> Vec<ConsoleLine> {
    state.console_after(after, limit as usize)
}

#[tauri::command]
pub fn host_preferences_get(state: State<'_, Arc<HostController>>) -> UiPreferences {
    state.preferences()
}

#[tauri::command]
pub fn host_preferences_set(state: State<'_, Arc<HostController>>, preferences: UiPreferences) -> HostSnapshot {
    let _ = state.set_preferences(preferences);
    state.snapshot()
}
