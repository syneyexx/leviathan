use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

use serde::Serialize;

use crate::envbuild::build_child_env;
use crate::paths::{self, frontend_index, is_loopback_host, venv_python};
use crate::redaction::redact_line;

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PreflightCheck {
    pub id: String,
    pub status: String,
    pub detail: String,
    pub remediation: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PreflightReport {
    pub ok: bool,
    pub checks: Vec<PreflightCheck>,
    pub host: String,
    pub port: u16,
    pub python_version: Option<String>,
    pub native_status: Option<String>,
    pub workers_expected: bool,
    pub env_created: bool,
}

pub struct CommandOutput {
    pub code: Option<i32>,
    pub stdout: String,
    pub stderr: String,
}

pub trait CommandRunner {
    fn run(&mut self, program: &Path, args: &[String], cwd: &Path) -> CommandOutput;
}

pub struct SystemCommandRunner;

impl CommandRunner for SystemCommandRunner {
    fn run(&mut self, program: &Path, args: &[String], cwd: &Path) -> CommandOutput {
        let mut command = Command::new(program);
        command
            .args(args)
            .current_dir(cwd)
            .env("PYTHONUNBUFFERED", "1")
            .env(
                "PYTHONPATH",
                build_child_env(&std::env::vars().collect(), cwd, false)
                    .get("PYTHONPATH")
                    .cloned()
                    .unwrap_or_default(),
            )
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            command.creation_flags(CREATE_NO_WINDOW);
        }
        match command.output() {
            Ok(output) => CommandOutput {
                code: output.status.code(),
                stdout: String::from_utf8_lossy(&output.stdout).to_string(),
                stderr: String::from_utf8_lossy(&output.stderr).to_string(),
            },
            Err(err) => CommandOutput {
                code: None,
                stdout: String::new(),
                stderr: err.to_string(),
            },
        }
    }
}

fn check(id: &str, ok: bool, detail: impl Into<String>, remediation: impl Into<String>) -> PreflightCheck {
    PreflightCheck {
        id: id.into(),
        status: if ok { "PASS".into() } else { "FAIL".into() },
        detail: redact_line(&detail.into()),
        remediation: remediation.into(),
    }
}

pub fn run_preflight(root: &Path, runner: &mut dyn CommandRunner, copy_env: bool) -> PreflightReport {
    let mut checks = Vec::new();
    let mut env_created = false;
    checks.push(check(
        "install_root",
        paths::is_install_root(root),
        format!("{}", root.display()),
        "Place the host inside the LEVIATHAN install root.",
    ));
    let python = venv_python(root);
    let python_ok = python.is_file();
    checks.push(check(
        "venv_python",
        python_ok,
        if python_ok {
            format!("{}", python.display())
        } else {
            format!("missing {}", python.display())
        },
        "Run installer.bat to create .venv.",
    ));

    let env_path = root.join(".env");
    let example = root.join(".env.example");
    if !env_path.is_file() && example.is_file() && copy_env {
        match fs::copy(&example, &env_path) {
            Ok(_) => {
                env_created = true;
                checks.push(check(
                    "env_file",
                    true,
                    "Created .env from .env.example",
                    "",
                ));
            }
            Err(err) => checks.push(check(
                "env_file",
                false,
                format!("failed to create .env: {err}"),
                "Copy .env.example to .env manually.",
            )),
        }
    } else if env_path.is_file() {
        checks.push(check("env_file", true, ".env present", ""));
    } else if example.is_file() {
        checks.push(check(
            "env_file",
            true,
            ".env missing; start will copy .env.example",
            "Start Leviathan to create .env, or copy it manually.",
        ));
    } else {
        checks.push(check(
            "env_file",
            false,
            "Missing .env and .env.example",
            "Restore .env.example from the repository.",
        ));
    }

    let index = frontend_index(root);
    checks.push(check(
        "frontend_dist",
        index.is_file(),
        if index.is_file() {
            format!("{}", index.display())
        } else {
            "Data/frontend/dist/index.html missing".into()
        },
        "Run installer.bat or npm run build in Data/frontend.",
    ));

    for relative in ["Data/backend", "Data/modules", "Data/native"] {
        let path = root.join(relative);
        checks.push(check(
            &format!("dir:{relative}"),
            path.is_dir(),
            format!("{}", path.display()),
            "Restore the missing directory from the repository.",
        ));
    }

    let mut python_version = None;
    let mut host = "127.0.0.1".to_string();
    let mut port = 8765_u16;
    let mut native_status = None;
    let mut workers_expected = true;

    if python_ok {
        let version = runner.run(
            &python,
            &["-c".into(), "import sys; print(sys.version.split()[0])".into()],
            root,
        );
        if version.code == Some(0) {
            python_version = Some(version.stdout.trim().to_string());
            checks.push(check(
                "python_runtime",
                true,
                python_version.clone().unwrap_or_default(),
                "",
            ));
        } else {
            checks.push(check(
                "python_runtime",
                false,
                format!("{}\n{}", version.stdout, version.stderr),
                "Recreate the virtualenv with installer.bat.",
            ));
        }

        let imports = runner.run(
            &python,
            &["-c".into(), "import fastapi, uvicorn".into()],
            root,
        );
        checks.push(check(
            "fastapi_import",
            imports.code == Some(0),
            if imports.code == Some(0) {
                "fastapi and uvicorn import".into()
            } else {
                format!("{}\n{}", imports.stdout, imports.stderr)
            },
            "Run installer.bat again to repair Python packages.",
        ));

        let app = runner.run(
            &python,
            &["-c".into(), "from Data.backend.main import app".into()],
            root,
        );
        checks.push(check(
            "app_import",
            app.code == Some(0),
            if app.code == Some(0) {
                "Data.backend.main:app importable".into()
            } else {
                format!("{}\n{}", app.stdout, app.stderr)
            },
            "Read the traceback. Do not hide import failures.",
        ));

        let config_script = r#"
import json
from Data.backend.config import load_settings
from Data.modules.workers.settings import load_worker_settings
s = load_settings()
w = load_worker_settings()
print(json.dumps({
  "host": s.runtime.host,
  "port": s.runtime.port,
  "loopbackOnly": bool(s.runtime.loopback_only),
  "workersEnabled": bool(w.enabled),
  "supervisorEnabled": bool(w.supervisor_enabled),
  "control": str(s.control_database_path),
  "knowledge": str(s.knowledge_database_path),
  "market": str(s.market_database_path),
}))
"#;
        let config = runner.run(&python, &["-c".into(), config_script.into()], root);
        if config.code == Some(0) {
            if let Ok(doc) = serde_json::from_str::<serde_json::Value>(config.stdout.trim()) {
                if let Some(value) = doc.get("host").and_then(|v| v.as_str()) {
                    host = value.to_string();
                }
                if let Some(value) = doc.get("port").and_then(|v| v.as_u64()) {
                    port = value as u16;
                }
                let loopback = doc.get("loopbackOnly").and_then(|v| v.as_bool()).unwrap_or(true);
                workers_expected = doc.get("workersEnabled").and_then(|v| v.as_bool()).unwrap_or(true)
                    && doc.get("supervisorEnabled").and_then(|v| v.as_bool()).unwrap_or(true);
                let host_ok = !loopback || is_loopback_host(&host);
                checks.push(check(
                    "runtime_config",
                    host_ok && port > 0,
                    format!("host={host} port={port} loopbackOnly={loopback}"),
                    "Set LEVIATHAN_HOST to a loopback address while LEVIATHAN_LOOPBACK_ONLY=true.",
                ));
                checks.push(check(
                    "worker_fabric",
                    true,
                    format!("workersEnabled={workers_expected}"),
                    "",
                ));
                for (id, key) in [
                    ("db_control", "control"),
                    ("db_knowledge", "knowledge"),
                    ("db_market", "market"),
                ] {
                    let raw = doc.get(key).and_then(|v| v.as_str()).unwrap_or("");
                    let path = PathBuf::from(raw);
                    let exists = path.is_file();
                    checks.push(PreflightCheck {
                        id: id.into(),
                        status: if exists { "PASS".into() } else { "NOT_CONFIGURED".into() },
                        detail: if exists {
                            format!("{} exists", path.display())
                        } else {
                            format!("{} missing until first backend start", path.display())
                        },
                        remediation: "The backend creates the SQLite file on startup if the directory is writable.".into(),
                    });
                }
            } else {
                checks.push(check(
                    "runtime_config",
                    false,
                    format!("config output was not JSON\n{}", config.stdout),
                    "Inspect Data/backend/config.py load errors.",
                ));
            }
        } else {
            checks.push(check(
                "runtime_config",
                false,
                format!("{}\n{}", config.stdout, config.stderr),
                "Fix the settings traceback before start.",
            ));
        }

        let native_script = r#"
import json
from Data.modules.workers.native_compute import probe_capabilities
print(json.dumps(probe_capabilities().public_dict()))
"#;
        let native = runner.run(&python, &["-c".into(), native_script.into()], root);
        if native.code == Some(0) {
            if let Ok(doc) = serde_json::from_str::<serde_json::Value>(native.stdout.trim()) {
                native_status = doc.get("status").and_then(|v| v.as_str()).map(|s| s.to_string());
                let status = native_status.clone().unwrap_or_else(|| "UNMEASURED".into());
                checks.push(PreflightCheck {
                    id: "native_data_plane".into(),
                    status: status.clone(),
                    detail: redact_line(doc.get("detail").and_then(|v| v.as_str()).unwrap_or("")),
                    remediation: "Native compute is an accelerator. BUILD_MISSING is honest until scripts/build_native_data_plane.py succeeds.".into(),
                });
            } else {
                checks.push(check("native_data_plane", false, native.stdout, "Probe output was not JSON."));
            }
        } else {
            checks.push(check(
                "native_data_plane",
                false,
                format!("{}\n{}", native.stdout, native.stderr),
                "Inspect the native probe traceback. Do not mark the data plane healthy.",
            ));
        }
    } else {
        checks.push(check(
            "python_runtime",
            false,
            "UNAVAILABLE",
            "Run installer.bat first.",
        ));
    }

    let hard_fail = checks.iter().any(|item| {
        item.status == "FAIL"
            && !matches!(
                item.id.as_str(),
                "native_data_plane"
            )
    });
    // Database NOT_CONFIGURED is not a hard failure: the backend creates files.
    // Native BUILD_MISSING / DISABLED is not a hard failure.
    let _ = Duration::from_secs(0);
    PreflightReport {
        ok: !hard_fail,
        checks,
        host,
        port,
        python_version,
        native_status,
        workers_expected,
        env_created,
    }
}

#[cfg(test)]
mod tests {
    use super::{run_preflight, CommandOutput, CommandRunner};
    use std::fs;
    use std::path::{Path, PathBuf};

    struct Scripted {
        fail_app: bool,
    }

    impl CommandRunner for Scripted {
        fn run(&mut self, _program: &Path, args: &[String], _cwd: &Path) -> CommandOutput {
            let script = args.get(1).map(String::as_str).unwrap_or("");
            if script.contains("sys.version") {
                return CommandOutput { code: Some(0), stdout: "3.12.3\n".into(), stderr: String::new() };
            }
            if script.contains("import fastapi") {
                return CommandOutput { code: Some(0), stdout: String::new(), stderr: String::new() };
            }
            if script.contains("import app") {
                if self.fail_app {
                    return CommandOutput {
                        code: Some(1),
                        stdout: String::new(),
                        stderr: "Traceback: ImportError: boom api_key=sekret\n".into(),
                    };
                }
                return CommandOutput { code: Some(0), stdout: String::new(), stderr: String::new() };
            }
            if script.contains("load_settings") {
                return CommandOutput {
                    code: Some(0),
                    stdout: "{\"host\":\"127.0.0.1\",\"port\":8765,\"loopbackOnly\":true,\"workersEnabled\":true,\"supervisorEnabled\":true,\"control\":\"/tmp/c.db\",\"knowledge\":\"/tmp/k.db\",\"market\":\"/tmp/m.db\"}\n".into(),
                    stderr: String::new(),
                };
            }
            if script.contains("probe_capabilities") {
                return CommandOutput {
                    code: Some(0),
                    stdout: "{\"status\":\"BUILD_MISSING\",\"detail\":\"binary not found\"}\n".into(),
                    stderr: String::new(),
                };
            }
            CommandOutput { code: Some(1), stdout: String::new(), stderr: "unexpected".into() }
        }
    }

    fn root() -> PathBuf {
        use std::sync::atomic::{AtomicU64, Ordering};
        static NEXT: AtomicU64 = AtomicU64::new(1);
        let id = NEXT.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!("leviathan-preflight-{}-{id}", std::process::id()));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(path.join("Data/backend")).unwrap();
        fs::create_dir_all(path.join("Data/modules")).unwrap();
        fs::create_dir_all(path.join("Data/native")).unwrap();
        fs::create_dir_all(path.join("Data/frontend/dist")).unwrap();
        fs::create_dir_all(path.join(".venv/bin")).unwrap();
        fs::create_dir_all(path.join(".venv/Scripts")).unwrap();
        fs::write(path.join("leviathan.py"), "").unwrap();
        fs::write(path.join("Data/backend/main.py"), "").unwrap();
        fs::write(path.join("Data/frontend/dist/index.html"), "<html></html>").unwrap();
        fs::write(path.join(".env.example"), "LEVIATHAN_PORT=8765\n").unwrap();
        let python = if cfg!(windows) {
            path.join(".venv/Scripts/python.exe")
        } else {
            path.join(".venv/bin/python")
        };
        fs::write(&python, "").unwrap();
        path
    }

    #[test]
    fn preflight_failure_keeps_traceback_and_redacts() {
        let path = root();
        let mut runner = Scripted { fail_app: true };
        let report = run_preflight(&path, &mut runner, false);
        assert!(!report.ok);
        let app = report.checks.iter().find(|c| c.id == "app_import").unwrap();
        assert_eq!(app.status, "FAIL");
        assert!(app.detail.contains("ImportError"));
        assert!(!app.detail.contains("sekret"));
        let _ = fs::remove_dir_all(path);
    }

    #[test]
    fn build_missing_native_does_not_fail_preflight() {
        let path = root();
        let mut runner = Scripted { fail_app: false };
        let report = run_preflight(&path, &mut runner, true);
        assert!(report.ok, "{:?}", report.checks);
        assert!(report.env_created);
        assert!(path.join(".env").is_file());
        assert_eq!(report.native_status.as_deref(), Some("BUILD_MISSING"));
        assert_eq!(report.python_version.as_deref(), Some("3.12.3"));
        let _ = fs::remove_dir_all(path);
    }
}
