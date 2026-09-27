//! Any command added to `tauri::generate_handler!` must also be added to
//! `COMMANDS` below and granted in `capabilities/default.json` when the
//! frontend is allowed to call it.
//!
//! Tauri generates `allow-<command>` and `deny-<command>` from this list,
//! with underscores turned into hyphens. Do not remove those capability grants
//! and do not replace them with a wildcard.

const COMMANDS: &[&str] = &[
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

fn main() {
    if let Err(err) = enforce_command_census() {
        panic!("host IPC command census failed: {err}");
    }
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(COMMANDS)),
    )
    .expect("failed to build Tauri application manifest");
}

fn enforce_command_census() -> Result<(), String> {
    let manifest_dir = std::path::PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").map_err(|err| err.to_string())?);
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed=src/lib.rs");
    println!("cargo:rerun-if-changed=src/commands.rs");
    println!("cargo:rerun-if-changed=capabilities/default.json");
    println!("cargo:rerun-if-changed=../host-core/src/lib.rs");

    let handler = command_names_from_handler(&read(&manifest_dir.join("src/lib.rs"))?)?;
    let functions = command_names_from_functions(&read(&manifest_dir.join("src/commands.rs"))?)?;
    let capability = allow_host_permissions(&read(&manifest_dir.join("capabilities/default.json"))?)?;
    let canonical = quoted_block(&read(&manifest_dir.join("../host-core/src/lib.rs"))?, "IPC_COMMANDS")?;
    let declared = COMMANDS.iter().map(|name| (*name).to_string()).collect::<Vec<_>>();

    if handler != declared {
        return Err(format!("generate_handler {handler:?} != AppManifest {declared:?}"));
    }
    if functions != declared {
        return Err(format!("commands.rs {functions:?} != AppManifest {declared:?}"));
    }
    if canonical != declared {
        return Err(format!("IPC_COMMANDS {canonical:?} != AppManifest {declared:?}"));
    }
    let expected_permissions = declared
        .iter()
        .map(|name| format!("allow-{}", name.replace('_', "-")))
        .collect::<Vec<_>>();
    if capability != expected_permissions {
        return Err(format!("capability grants {capability:?} != {expected_permissions:?}"));
    }
    Ok(())
}

fn read(path: &std::path::Path) -> Result<String, String> {
    std::fs::read_to_string(path).map_err(|err| format!("read {}: {err}", path.display()))
}

fn command_names_from_handler(source: &str) -> Result<Vec<String>, String> {
    let start = source
        .find("tauri::generate_handler!")
        .ok_or("generate_handler! missing from src/lib.rs")?;
    let rest = &source[start..];
    let open = rest.find('[').ok_or("generate_handler! has no '['")?;
    let close = rest.find(']').ok_or("generate_handler! has no ']'")?;
    let mut names = Vec::new();
    for item in rest[open + 1..close].split(',') {
        let item = item.trim().trim_end_matches(',');
        if item.is_empty() {
            continue;
        }
        let name = item
            .rsplit("::")
            .next()
            .unwrap_or(item)
            .trim();
        if !name.starts_with("host_") {
            return Err(format!("unexpected handler entry {item}"));
        }
        names.push(name.to_string());
    }
    Ok(names)
}

fn command_names_from_functions(source: &str) -> Result<Vec<String>, String> {
    let mut names = Vec::new();
    for line in source.lines() {
        let trimmed = line.trim();
        if let Some(rest) = trimmed.strip_prefix("pub fn ") {
            let name = rest.split('(').next().unwrap_or("").trim();
            if name.starts_with("host_") {
                names.push(name.to_string());
            }
        }
    }
    if names.is_empty() {
        return Err("commands.rs has no host_* functions".into());
    }
    Ok(names)
}

fn allow_host_permissions(source: &str) -> Result<Vec<String>, String> {
    let start = source.find("\"permissions\"").ok_or("capabilities/default.json has no permissions")?;
    let rest = &source[start..];
    let open = rest.find('[').ok_or("permissions array missing")?;
    let close = rest.find(']').ok_or("permissions array not closed")?;
    let mut host = Vec::new();
    for item in rest[open + 1..close].split(',') {
        let name = item.trim().trim_matches('"');
        if name.is_empty() {
            continue;
        }
        if name == "*" || name.contains('*') {
            return Err(format!("wildcard capability grant is not allowed: {name}"));
        }
        if name.contains("shell") || name.starts_with("fs:") || name.starts_with("process:") {
            return Err(format!("forbidden capability grant: {name}"));
        }
        if !(name.starts_with("core:") || name.starts_with("allow-host-") || name.starts_with("deny-host-")) {
            return Err(format!("unexpected capability grant: {name}"));
        }
        if name.starts_with("allow-host-") {
            host.push(name.to_string());
        }
    }
    Ok(host)
}

fn quoted_block(source: &str, const_name: &str) -> Result<Vec<String>, String> {
    let marker = format!("const {const_name}");
    let start = source.find(&marker).ok_or_else(|| format!("{const_name} missing"))?;
    let rest = &source[start..];
    let eq = rest.find('=').ok_or_else(|| format!("{const_name} has no '='"))?;
    let after = &rest[eq..];
    let open = after.find('[').ok_or_else(|| format!("{const_name} has no '['"))?;
    let close = after.find(']').ok_or_else(|| format!("{const_name} has no ']'"))?;
    let mut names = Vec::new();
    for item in after[open + 1..close].split(',') {
        let item = item.trim().trim_matches('"');
        if item.is_empty() {
            continue;
        }
        names.push(item.to_string());
    }
    Ok(names)
}
