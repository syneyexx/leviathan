use std::collections::HashMap;
use std::path::{Path, PathBuf};

/// Walk the executable directory and the current directory for the install root.
/// The root is the directory that contains `leviathan.py` and `Data/backend/main.py`.
pub fn discover_install_root(exe: &Path, cwd: &Path) -> Result<PathBuf, String> {
    let mut candidates = Vec::new();
    push_ancestors(&mut candidates, exe);
    push_ancestors(&mut candidates, cwd);
    for candidate in candidates {
        if is_install_root(&candidate) {
            return Ok(candidate);
        }
    }
    Err(
        "Install root not found. run_leviathan must live inside a LEVIATHAN checkout that contains leviathan.py."
            .into(),
    )
}

fn push_ancestors(out: &mut Vec<PathBuf>, start: &Path) {
    let start = if start.is_file() {
        start.parent().unwrap_or(start)
    } else {
        start
    };
    let mut current = Some(start.to_path_buf());
    let mut guard = 0;
    while let Some(path) = current {
        if !out.iter().any(|existing| existing == &path) {
            out.push(path.clone());
        }
        guard += 1;
        if guard > 16 {
            break;
        }
        current = path.parent().map(Path::to_path_buf);
    }
}

pub fn is_install_root(path: &Path) -> bool {
    path.join("leviathan.py").is_file() && path.join("Data").join("backend").join("main.py").is_file()
}

pub fn venv_python(root: &Path) -> PathBuf {
    if cfg!(windows) {
        root.join(".venv").join("Scripts").join("python.exe")
    } else {
        root.join(".venv").join("bin").join("python")
    }
}

pub fn frontend_index(root: &Path) -> PathBuf {
    root.join("Data").join("frontend").join("dist").join("index.html")
}

pub fn launcher_log_dir(root: &Path) -> PathBuf {
    root.join("Data").join("logs").join("launcher")
}

pub fn canonical_env_file(root: &Path) -> PathBuf {
    let env = root.join(".env");
    if env.is_file() {
        env
    } else {
        root.join(".env.example")
    }
}

/// Parse a dotenv file without executing it and without expanding commands.
pub fn parse_env_assignments(text: &str) -> HashMap<String, String> {
    let mut map = HashMap::new();
    for raw in text.lines() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let line = line.strip_prefix("export ").unwrap_or(line);
        let Some((key, value)) = line.split_once('=') else {
            continue;
        };
        let key = key.trim();
        if key.is_empty() || key.contains(' ') || key.contains(';') {
            continue;
        }
        let mut value = value.trim().to_string();
        if value.len() >= 2 {
            let bytes = value.as_bytes();
            if (bytes[0] == b'"' && bytes[value.len() - 1] == b'"')
                || (bytes[0] == b'\'' && bytes[value.len() - 1] == b'\'')
            {
                value = value[1..value.len() - 1].to_string();
            }
        }
        if value.contains("$(") || value.contains('`') {
            continue;
        }
        map.insert(key.to_string(), value);
    }
    map
}

pub fn runtime_endpoint(env_text: &str) -> (String, u16) {
    let map = parse_env_assignments(env_text);
    let host = map
        .get("LEVIATHAN_HOST")
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "127.0.0.1".into());
    let port = map
        .get("LEVIATHAN_PORT")
        .and_then(|value| value.trim().parse::<u16>().ok())
        .filter(|port| *port > 0)
        .unwrap_or(8765);
    (host, port)
}

pub fn is_loopback_host(host: &str) -> bool {
    matches!(host, "127.0.0.1" | "localhost" | "::1")
}

/// Allow only the operator config file and the launcher log directory.
pub fn allowlisted_open_path(install: &Path, candidate: &Path) -> Result<PathBuf, String> {
    let root = install
        .canonicalize()
        .map_err(|err| format!("install root is not canonical: {err}"))?;
    let path = if candidate.exists() {
        candidate
            .canonicalize()
            .map_err(|err| format!("path is not canonical: {err}"))?
    } else if let (Some(parent), Some(name)) = (candidate.parent(), candidate.file_name()) {
        let parent = parent
            .canonicalize()
            .map_err(|err| format!("parent is not canonical: {err}"))?;
        parent.join(name)
    } else {
        return Err("path cannot be canonicalized".into());
    };
    if !path.starts_with(&root) {
        return Err("path is outside the install root".into());
    }
    let env = root.join(".env");
    let example = root.join(".env.example");
    let logs = root.join("Data").join("logs").join("launcher");
    if path == env || path == example || path == logs || path.starts_with(&logs) {
        return Ok(path);
    }
    Err("path is not an allowlisted operator target".into())
}

#[cfg(test)]
mod tests {
    use super::{
        allowlisted_open_path, discover_install_root, parse_env_assignments, runtime_endpoint,
    };
    use std::fs;
    use std::path::Path;

    fn scratch(name: &str) -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!("leviathan-host-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(path.join("Data/backend")).unwrap();
        fs::write(path.join("leviathan.py"), "print('x')\n").unwrap();
        fs::write(path.join("Data/backend/main.py"), "# app\n").unwrap();
        path
    }

    #[test]
    fn discovers_install_root_from_nested_exe() {
        let root = scratch("discover");
        let nested = root.join("dist").join("bin");
        fs::create_dir_all(&nested).unwrap();
        let found = discover_install_root(&nested.join("run_leviathan.exe"), &nested).unwrap();
        assert_eq!(found, root);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn rejects_unrelated_directory() {
        let path = std::env::temp_dir().join(format!("leviathan-empty-{}", std::process::id()));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(&path).unwrap();
        assert!(discover_install_root(&path, &path).is_err());
        let _ = fs::remove_dir_all(path);
    }

    #[test]
    fn parses_env_without_command_substitution() {
        let map = parse_env_assignments(
            "# comment\nexport LEVIATHAN_HOST=127.0.0.1\nLEVIATHAN_PORT=\"8765\"\nEVIL=$(rm -rf /)\n",
        );
        assert_eq!(map.get("LEVIATHAN_HOST").map(String::as_str), Some("127.0.0.1"));
        assert_eq!(map.get("LEVIATHAN_PORT").map(String::as_str), Some("8765"));
        assert!(!map.contains_key("EVIL"));
        assert_eq!(runtime_endpoint("LEVIATHAN_PORT=9000\n"), ("127.0.0.1".into(), 9000));
    }

    #[test]
    fn open_path_rejects_escape() {
        let root = scratch("allow");
        fs::write(root.join(".env"), "X=1\n").unwrap();
        fs::create_dir_all(root.join("Data/logs/launcher")).unwrap();
        assert!(allowlisted_open_path(&root, &root.join(".env")).is_ok());
        assert!(allowlisted_open_path(&root, Path::new("/etc/passwd")).is_err());
        assert!(allowlisted_open_path(&root, &root.join("leviathan.py")).is_err());
        let _ = fs::remove_dir_all(root);
    }
}
