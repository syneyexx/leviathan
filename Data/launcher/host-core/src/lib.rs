//! Portable control core for `run_leviathan.exe`.
//!
//! The Tauri shell is a window around this crate. Process policy, preflight,
//! redaction, and the host state machine live here so they can be tested
//! without a WebView.

pub mod controller;
pub mod envbuild;
pub mod http_probe;
pub mod logbuf;
pub mod paths;
pub mod preflight;
pub mod process_port;
pub mod redaction;
pub mod single_instance;

pub use controller::{HostController, HostError, HostSnapshot, OwnershipKind, UiPreferences};
pub use logbuf::ConsoleLine;
pub use envbuild::{build_child_env, SAFE_MODE_ENV};
pub use paths::{discover_install_root, runtime_endpoint};
pub use preflight::{PreflightCheck, PreflightReport};
pub use redaction::redact_line;

/// IPC commands the shell is allowed to register. There is no shell-exec command.
pub const IPC_COMMANDS: &[&str] = &[
    "host_snapshot",
    "host_preflight",
    "host_start",
    "host_stop",
    "host_restart",
    "host_emergency",
    "host_confirm_close",
    "host_open",
    "host_console",
    "host_preferences_get",
    "host_preferences_set",
];

pub fn ipc_command_allowed(name: &str) -> bool {
    IPC_COMMANDS.contains(&name)
        && !name.contains("shell")
        && !name.contains("exec")
        && !name.contains("cmd")
}

/// Windows Job Object integration is compiled only on Windows and is not
/// executed by the Linux test suite.
pub const WINDOWS_JOB_OBJECT_EXECUTED_IN_THIS_BUILD: bool = cfg!(windows);
