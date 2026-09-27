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
    "host_trace",
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

#[cfg(test)]
mod ipc_census {
    use super::IPC_COMMANDS;
    use std::path::PathBuf;

    #[test]
    fn tauri_handler_manifest_and_capability_list_the_same_commands() {
        let tauri = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../src-tauri");
        let declared = IPC_COMMANDS.iter().map(|name| (*name).to_string()).collect::<Vec<_>>();
        let handler = names_from_handler(&read(&tauri.join("src/lib.rs")));
        let functions = names_from_functions(&read(&tauri.join("src/commands.rs")));
        let manifest = quoted_block(&read(&tauri.join("build.rs")), "COMMANDS");
        let grants = allow_host(&read(&tauri.join("capabilities/default.json")));
        let expected_grants = declared
            .iter()
            .map(|name| format!("allow-{}", name.replace('_', "-")))
            .collect::<Vec<_>>();
        assert_eq!(handler, declared, "generate_handler drifted from IPC_COMMANDS");
        assert_eq!(functions, declared, "commands.rs drifted from IPC_COMMANDS");
        assert_eq!(manifest, declared, "AppManifest COMMANDS drifted from IPC_COMMANDS");
        assert_eq!(grants, expected_grants, "capability grants drifted");
        assert!(declared.iter().all(|name| !name.contains("shell") && !name.contains("exec")));
    }

    fn read(path: &std::path::Path) -> String {
        std::fs::read_to_string(path).unwrap_or_else(|err| panic!("read {}: {err}", path.display()))
    }

    fn names_from_handler(source: &str) -> Vec<String> {
        let start = source.find("tauri::generate_handler!").expect("generate_handler");
        let rest = &source[start..];
        let open = rest.find('[').unwrap();
        let close = rest.find(']').unwrap();
        rest[open + 1..close]
            .split(',')
            .filter_map(|item| {
                let name = item.trim().rsplit("::").next().unwrap_or("").trim();
                if name.is_empty() { None } else { Some(name.to_string()) }
            })
            .collect()
    }

    fn names_from_functions(source: &str) -> Vec<String> {
        source
            .lines()
            .filter_map(|line| {
                let trimmed = line.trim();
                let rest = trimmed.strip_prefix("pub fn ")?;
                let name = rest.split('(').next()?.trim();
                name.starts_with("host_").then(|| name.to_string())
            })
            .collect()
    }

    fn quoted_block(source: &str, const_name: &str) -> Vec<String> {
        let marker = format!("const {const_name}");
        let start = source.find(&marker).unwrap_or_else(|| panic!("{const_name} missing"));
        let rest = &source[start..];
        let eq = rest.find('=').unwrap_or_else(|| panic!("{const_name} has no '='"));
        let after = &rest[eq..];
        let open = after.find('[').unwrap();
        let close = after.find(']').unwrap();
        after[open + 1..close]
            .split(',')
            .filter_map(|item| {
                let name = item.trim().trim_matches('"');
                if name.is_empty() { None } else { Some(name.to_string()) }
            })
            .collect()
    }

    fn allow_host(source: &str) -> Vec<String> {
        let start = source.find("\"permissions\"").expect("permissions");
        let rest = &source[start..];
        let open = rest.find('[').unwrap();
        let close = rest.find(']').unwrap();
        let mut host = Vec::new();
        for item in rest[open + 1..close].split(',') {
            let name = item.trim().trim_matches('"');
            if name.is_empty() {
                continue;
            }
            assert!(!name.contains('*'), "wildcard grant {name}");
            assert!(!name.contains("shell") && !name.starts_with("fs:") && !name.starts_with("process:"), "{name}");
            assert!(name.starts_with("core:") || name.starts_with("allow-host-") || name.starts_with("deny-host-"), "{name}");
            if name.starts_with("allow-host-") {
                host.push(name.to_string());
            }
        }
        host
    }
}
