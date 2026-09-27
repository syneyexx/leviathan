use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

use crate::envbuild::build_child_env;
use crate::redaction::redact_line;
use crate::logbuf::{ConsoleLine, LogRing, RotatingLog};
use crate::paths::{self, allowlisted_open_path, canonical_env_file, launcher_log_dir, venv_python};
use crate::preflight::{self, PreflightReport, SystemCommandRunner};
use crate::process_port::{ProcessPort, SpawnSpec, SystemProcessPort};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Phase {
    Stopped,
    Preflight,
    Starting,
    Running,
    Degraded,
    Stopping,
    Failed,
    AttachedExternal,
}

impl Phase {
    fn as_str(self) -> &'static str {
        match self {
            Phase::Stopped => "STOPPED",
            Phase::Preflight => "PREFLIGHT",
            Phase::Starting => "STARTING",
            Phase::Running => "RUNNING",
            Phase::Degraded => "DEGRADED",
            Phase::Stopping => "STOPPING",
            Phase::Failed => "FAILED",
            Phase::AttachedExternal => "ATTACHED_EXTERNAL",
        }
    }

    fn busy(self) -> bool {
        matches!(self, Phase::Preflight | Phase::Starting | Phase::Stopping)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum OwnershipKind {
    None,
    Owned,
    External,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HostSnapshot {
    pub state: String,
    pub ownership: OwnershipKind,
    pub safe_mode_armed: bool,
    pub safe_mode_active: bool,
    pub pid: Option<u32>,
    pub exit_code: Option<i32>,
    pub clean_shutdown: Option<bool>,
    pub message: String,
    pub api_base: Option<String>,
    pub frontend_url: Option<String>,
    pub version: String,
    pub install_root: String,
    pub preflight: PreflightReport,
    pub started_at: Option<String>,
    pub python_version: Option<String>,
    pub supervisor_health: Option<String>,
    pub workers_expected: bool,
    pub exit_when_stopped: bool,
    /// System readiness is distinct from process lifecycle (`state`).
    /// STARTING | READY | DEGRADED | SAFE_MODE | NOT_CONFIGURED | UNMEASURED
    pub system_readiness: String,
}

#[derive(Clone, Debug)]
pub struct HostError {
    pub message: String,
}

impl HostError {
    fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UiPreferences {
    pub safe_mode: bool,
    pub auto_scroll: bool,
    pub paused: bool,
}

impl Default for UiPreferences {
    fn default() -> Self {
        Self {
            safe_mode: false,
            auto_scroll: true,
            paused: false,
        }
    }
}

struct Session {
    phase: Phase,
    ownership: OwnershipKind,
    safe_mode_armed: bool,
    safe_mode_active: bool,
    pid: Option<u32>,
    exit_code: Option<i32>,
    clean_shutdown: Option<bool>,
    message: String,
    host: String,
    port: u16,
    preflight: PreflightReport,
    started_at: Option<String>,
    python_version: Option<String>,
    supervisor_health: Option<String>,
    workers_expected: bool,
    deadline: Option<Instant>,
    polls: u32,
    exit_when_stopped: bool,
    restart_after_stop: bool,
    generation: u64,
}

pub struct HostController {
    root: PathBuf,
    version: String,
    session: Mutex<Session>,
    port: Mutex<Box<dyn ProcessPort>>,
    ring: Mutex<LogRing>,
    log: Mutex<Option<RotatingLog>>,
    startup_timeout: Duration,
    shutdown_timeout: Duration,
}

impl HostController {
    pub fn new(root: PathBuf, version: impl Into<String>) -> Self {
        Self::with_port(root, version, Box::new(SystemProcessPort::new()), Duration::from_secs(90), Duration::from_secs(20))
    }

    pub fn with_port(
        root: PathBuf,
        version: impl Into<String>,
        port: Box<dyn ProcessPort>,
        startup_timeout: Duration,
        shutdown_timeout: Duration,
    ) -> Self {
        let _ = fs::create_dir_all(launcher_log_dir(&root));
        let log = RotatingLog::open(&launcher_log_dir(&root).join("run_leviathan_host.log"), 2_000_000).ok();
        let prefs = read_preferences(&root);
        let session = Session {
            phase: Phase::Stopped,
            ownership: OwnershipKind::None,
            safe_mode_armed: prefs.safe_mode,
            safe_mode_active: false,
            pid: None,
            exit_code: None,
            clean_shutdown: None,
            message: "Backend host is stopped.".into(),
            host: "127.0.0.1".into(),
            port: 8765,
            preflight: empty_report(),
            started_at: None,
            python_version: None,
            supervisor_health: None,
            workers_expected: true,
            deadline: None,
            polls: 0,
            exit_when_stopped: false,
            restart_after_stop: false,
            generation: 0,
        };
        Self {
            root,
            version: version.into(),
            session: Mutex::new(session),
            port: Mutex::new(port),
            ring: Mutex::new(LogRing::new(20_000)),
            log: Mutex::new(log),
            startup_timeout,
            shutdown_timeout,
        }
    }

    pub fn client_trace(&self, event: &str, detail: &str) -> Result<(), String> {
        if event.is_empty()
            || event.len() > 48
            || !event.chars().all(|ch| ch.is_ascii_uppercase() || ch == '_')
        {
            return Err(format!("trace event rejected: {event}"));
        }
        let clean = redact_line(detail).replace(['\n', '\r'], " ");
        let clean = if clean.len() > 240 {
            format!("{}…", &clean[..240])
        } else {
            clean
        };
        self.push_line("ui", "info", "system", &format!("{event} {clean}"), None);
        Ok(())
    }

    pub fn install_root(&self) -> &Path {
        &self.root
    }

    pub fn snapshot(&self) -> HostSnapshot {
        self.session.lock().unwrap_or_else(|p| p.into_inner()).to_snapshot(&self.root, &self.version)
    }

    pub fn console_after(&self, seq: u64, limit: usize) -> Vec<ConsoleLine> {
        self.ring.lock().unwrap_or_else(|p| p.into_inner()).after(seq, limit.min(2_000))
    }

    pub fn preferences(&self) -> UiPreferences {
        let session = self.session.lock().unwrap_or_else(|p| p.into_inner());
        UiPreferences {
            safe_mode: session.safe_mode_armed,
            auto_scroll: read_preferences(&self.root).auto_scroll,
            paused: read_preferences(&self.root).paused,
        }
    }

    pub fn set_preferences(&self, prefs: UiPreferences) -> UiPreferences {
        {
            let mut session = self.session.lock().unwrap_or_else(|p| p.into_inner());
            session.safe_mode_armed = prefs.safe_mode;
        }
        write_preferences(&self.root, &prefs);
        prefs
    }

    pub fn preflight(&self, copy_env: bool) -> PreflightReport {
        let mut runner = SystemCommandRunner;
        let report = preflight::run_preflight(&self.root, &mut runner, copy_env);
        let mut session = self.session.lock().unwrap_or_else(|p| p.into_inner());
        session.host = report.host.clone();
        session.port = report.port;
        session.python_version = report.python_version.clone();
        session.workers_expected = report.workers_expected;
        session.preflight = report.clone();
        for check in &report.checks {
            self.push_line("preflight", &check.status, "system", &format!("{}: {}", check.id, check.detail), None);
        }
        report
    }

    pub fn probe_existing(&self) {
        let (host, port) = self.configured_endpoint();
        let probe = self.port.lock().unwrap_or_else(|p| p.into_inner()).probe_health(&host, port);
        let mut session = self.session.lock().unwrap_or_else(|p| p.into_inner());
        if session.phase != Phase::Stopped {
            return;
        }
        session.host = host;
        session.port = port;
        if probe.reachable && probe.ok == Some(true) {
            session.phase = Phase::AttachedExternal;
            session.ownership = OwnershipKind::External;
            session.message = "Attached to an already running LEVIATHAN instance. This host does not own it.".into();
            session.clean_shutdown = None;
            drop(session);
            self.push_line("state", "info", "system", "ATTACHED_EXTERNAL", None);
        }
    }

    pub fn start(&self, safe_mode: bool) -> Result<HostSnapshot, HostError> {
        self.ensure_startable()?;
        {
            let mut session = self.session.lock().unwrap_or_else(|p| p.into_inner());
            session.phase = Phase::Preflight;
            session.safe_mode_armed = safe_mode;
            session.message = "Running preflight.".into();
            session.generation = session.generation.saturating_add(1);
        }
        self.push_line("state", "info", "system", "PREFLIGHT", None);
        let report = self.preflight(true);
        self.start_from_report(report, safe_mode)
    }

    pub fn start_from_report(&self, report: PreflightReport, safe_mode: bool) -> Result<HostSnapshot, HostError> {
        self.ensure_startable_or_preflight()?;
        if !report.ok {
            let mut session = self.session.lock().unwrap_or_else(|p| p.into_inner());
            session.phase = Phase::Failed;
            session.ownership = OwnershipKind::None;
            session.safe_mode_armed = safe_mode;
            session.preflight = report.clone();
            session.message = "Preflight failed. See the failing check.".into();
            session.clean_shutdown = None;
            return Ok(session.to_snapshot(&self.root, &self.version));
        }
        let probe = self
            .port
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .probe_health(&report.host, report.port);
        if probe.reachable && probe.ok == Some(true) {
            let mut session = self.session.lock().unwrap_or_else(|p| p.into_inner());
            session.phase = Phase::AttachedExternal;
            session.ownership = OwnershipKind::External;
            session.host = report.host.clone();
            session.port = report.port;
            session.preflight = report;
            session.safe_mode_active = false;
            session.pid = None;
            session.message = "An external LEVIATHAN instance is already healthy. Start was not duplicated.".into();
            drop(session);
            self.push_line("state", "warning", "system", "ATTACHED_EXTERNAL — duplicate start refused", None);
            return Ok(self.snapshot());
        }
        let python = venv_python(&self.root);
        if !python.is_file() {
            return Err(HostError::new(format!("venv python missing at {}", python.display())));
        }
        let mut env = build_child_env(&std::env::vars().collect(), &self.root, safe_mode);
        env.insert("PYTHONUNBUFFERED".into(), "1".into());
        let spec = SpawnSpec {
            program: python,
            args: vec!["leviathan.py".into()],
            cwd: self.root.clone(),
            env,
        };
        let pid = self
            .port
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .spawn(spec)
            .map_err(HostError::new)?;
        let mut session = self.session.lock().unwrap_or_else(|p| p.into_inner());
        session.phase = Phase::Starting;
        session.ownership = OwnershipKind::Owned;
        session.pid = Some(pid);
        session.safe_mode_active = safe_mode;
        session.safe_mode_armed = safe_mode;
            session.host = report.host.clone();
            session.port = report.port;
            session.workers_expected = report.workers_expected && !safe_mode;
            session.python_version = report.python_version.clone();
            session.preflight = report;
        session.started_at = Some(now_iso());
        session.exit_code = None;
        session.clean_shutdown = None;
        session.deadline = Some(Instant::now() + self.startup_timeout);
        session.message = format!("Owned process {pid} is starting. Waiting for /api/host/liveness.");
        drop(session);
        self.push_line("state", "info", "system", &format!("STARTING pid={pid}"), Some(pid));
        Ok(self.snapshot())
    }

    pub fn stop(&self) -> Result<HostSnapshot, HostError> {
        let mut session = self.session.lock().unwrap_or_else(|p| p.into_inner());
        if session.ownership != OwnershipKind::Owned {
            return Err(HostError::new(
                "Stop is disabled because this host does not own the backend process.",
            ));
        }
        if !matches!(session.phase, Phase::Starting | Phase::Running | Phase::Degraded | Phase::Failed) {
            return Err(HostError::new(format!("Stop is not available from {}.", session.phase.as_str())));
        }
        if session.phase == Phase::Failed && session.pid.is_none() {
            session.phase = Phase::Stopped;
            session.message = "Nothing owned is still running.".into();
            return Ok(session.to_snapshot(&self.root, &self.version));
        }
        session.phase = Phase::Stopping;
        session.deadline = Some(Instant::now() + self.shutdown_timeout);
        session.message = "Requesting graceful shutdown of the owned process tree.".into();
        drop(session);
        let graceful = self.port.lock().unwrap_or_else(|p| p.into_inner()).request_graceful();
        if let Err(err) = graceful {
            self.push_line("state", "warning", "system", &format!("graceful signal unavailable: {err}"), None);
        } else {
            self.push_line("state", "info", "system", "STOPPING", None);
        }
        Ok(self.snapshot())
    }

    pub fn emergency(&self) -> Result<HostSnapshot, HostError> {
        let mut session = self.session.lock().unwrap_or_else(|p| p.into_inner());
        if session.ownership != OwnershipKind::Owned {
            return Err(HostError::new(
                "Emergency shutdown can only terminate the process tree owned by this host.",
            ));
        }
        session.phase = Phase::Stopping;
        session.message = "Emergency shutdown is terminating the owned process tree.".into();
        drop(session);
        self.port
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .terminate_owned()
            .map_err(HostError::new)?;
        let mut session = self.session.lock().unwrap_or_else(|p| p.into_inner());
        session.phase = Phase::Stopped;
        session.ownership = OwnershipKind::None;
        session.pid = None;
        session.clean_shutdown = Some(false);
        session.safe_mode_active = false;
        session.exit_code = None;
        session.message = "Owned process tree was force-terminated. This was not a clean shutdown.".into();
        drop(session);
        self.push_line("state", "error", "system", "EMERGENCY_STOP unclean", None);
        Ok(self.snapshot())
    }

    pub fn restart(&self, safe_mode: bool) -> Result<HostSnapshot, HostError> {
        let phase = self.session.lock().unwrap_or_else(|p| p.into_inner()).phase;
        let ownership = self.session.lock().unwrap_or_else(|p| p.into_inner()).ownership;
        if ownership == OwnershipKind::External {
            return Err(HostError::new("Restart is disabled while attached to an external instance."));
        }
        if matches!(phase, Phase::Running | Phase::Degraded | Phase::Starting) {
            {
                let mut session = self.session.lock().unwrap_or_else(|p| p.into_inner());
                session.restart_after_stop = true;
                session.safe_mode_armed = safe_mode;
            }
            self.stop()?;
            let deadline = Instant::now() + self.shutdown_timeout + Duration::from_secs(2);
            while Instant::now() < deadline {
                self.poll_once();
                let phase = self.session.lock().unwrap_or_else(|p| p.into_inner()).phase;
                if matches!(phase, Phase::Stopped | Phase::Failed) {
                    break;
                }
                thread::sleep(Duration::from_millis(30));
            }
            let phase = self.session.lock().unwrap_or_else(|p| p.into_inner()).phase;
            if phase == Phase::Stopping {
                self.emergency()?;
            }
        }
        {
            let mut session = self.session.lock().unwrap_or_else(|p| p.into_inner());
            session.restart_after_stop = false;
            if session.phase == Phase::Failed {
                session.phase = Phase::Stopped;
                session.ownership = OwnershipKind::None;
                session.pid = None;
            }
        }
        self.start(safe_mode)
    }

    pub fn confirm_close(&self, stop_owned: bool) -> Result<HostSnapshot, HostError> {
        let ownership = self.session.lock().unwrap_or_else(|p| p.into_inner()).ownership;
        if ownership != OwnershipKind::Owned {
            let mut session = self.session.lock().unwrap_or_else(|p| p.into_inner());
            session.exit_when_stopped = true;
            return Ok(session.to_snapshot(&self.root, &self.version));
        }
        if !stop_owned {
            return Err(HostError::new("Close cancelled. The owned backend is still running."));
        }
        {
            let mut session = self.session.lock().unwrap_or_else(|p| p.into_inner());
            session.exit_when_stopped = true;
        }
        self.stop()
    }

    pub fn open_target(&self, target: &str) -> Result<String, HostError> {
        match target {
            "config" => {
                let path = canonical_env_file(&self.root);
                let allowed = allowlisted_open_path(&self.root, &path).map_err(HostError::new)?;
                open_path(&allowed).map_err(HostError::new)?;
                Ok(allowed.display().to_string())
            }
            "logs" => {
                let path = launcher_log_dir(&self.root);
                fs::create_dir_all(&path).map_err(|err| HostError::new(err.to_string()))?;
                let allowed = allowlisted_open_path(&self.root, &path).map_err(HostError::new)?;
                open_path(&allowed).map_err(HostError::new)?;
                Ok(allowed.display().to_string())
            }
            "frontend" => {
                let session = self.session.lock().unwrap_or_else(|p| p.into_inner());
                let probe = {
                    drop(session);
                    let session = self.session.lock().unwrap_or_else(|p| p.into_inner());
                    let host = session.host.clone();
                    let port = session.port;
                    drop(session);
                    self.port.lock().unwrap_or_else(|p| p.into_inner()).probe_health(&host, port)
                };
                if !(probe.reachable && probe.ok == Some(true)) {
                    return Err(HostError::new(format!(
                        "Frontend URL is not reachable: {}",
                        probe.detail
                    )));
                }
                let session = self.session.lock().unwrap_or_else(|p| p.into_inner());
                let url = format!("http://{}:{}/", session.host, session.port);
                if !paths::is_loopback_host(&session.host) {
                    return Err(HostError::new(
                        "Refusing to open a non-loopback frontend URL from the host shell.",
                    ));
                }
                open_path_or_url(&url).map_err(HostError::new)?;
                Ok(url)
            }
            _ => Err(HostError::new("Unknown open target.")),
        }
    }

    pub fn poll_once(&self) {
        let polled = self.port.lock().unwrap_or_else(|p| p.into_inner()).poll();
        for line in polled.lines {
            let level = if line.stream == "stderr" { "error" } else { "info" };
            self.push_line("process", level, &line.stream, &line.text, line.pid);
        }
        let (phase, host, port, workers_expected, polls) = {
            let session = self.session.lock().unwrap_or_else(|p| p.into_inner());
            (
                session.phase,
                session.host.clone(),
                session.port,
                session.workers_expected,
                session.polls,
            )
        };
        let health = if matches!(phase, Phase::Starting | Phase::Running | Phase::Degraded | Phase::AttachedExternal) {
            Some(self.port.lock().unwrap_or_else(|p| p.into_inner()).probe_health(&host, port))
        } else {
            None
        };
        let supervisor = if matches!(phase, Phase::Running | Phase::Degraded) && workers_expected && polls % 5 == 0 {
            self.port.lock().unwrap_or_else(|p| p.into_inner()).probe_supervisor(&host, port)
        } else {
            None
        };
        let mut session = self.session.lock().unwrap_or_else(|p| p.into_inner());
        session.polls = session.polls.saturating_add(1);
        if let Some(health_name) = supervisor {
            session.supervisor_health = Some(health_name);
        }
        match session.phase {
            Phase::Starting => {
                if !polled.running && session.pid.is_some() {
                    session.exit_code = polled.exit_code;
                    session.phase = Phase::Failed;
                    session.ownership = OwnershipKind::None;
                    session.pid = None;
                    session.clean_shutdown = Some(false);
                    session.message = format!(
                        "Backend process exited before /api/host/liveness became ready (code={}).",
                        polled.exit_code.map(|c| c.to_string()).unwrap_or_else(|| "unknown".into())
                    );
                } else if health.as_ref().and_then(|p| p.ok) == Some(true) {
                    session.phase = Phase::Running;
                    session.message = if session.safe_mode_active {
                        "Backend host active. Safe Mode — API-only recovery posture.".into()
                    } else if session.workers_expected {
                        "Backend host active. System readiness: STARTING WORKERS.".into()
                    } else {
                        "Backend host active. Workers not configured.".into()
                    };
                    session.deadline = None;
                } else if session.deadline.is_some_and(|deadline| Instant::now() > deadline) {
                    session.phase = Phase::Failed;
                    session.message = "Startup timed out waiting for /api/host/liveness.".into();
                    session.clean_shutdown = Some(false);
                    drop(session);
                    let _ = self.port.lock().unwrap_or_else(|p| p.into_inner()).terminate_owned();
                    let mut session = self.session.lock().unwrap_or_else(|p| p.into_inner());
                    session.ownership = OwnershipKind::None;
                    session.pid = None;
                    session.phase = Phase::Failed;
                }
            }
            Phase::Running | Phase::Degraded => {
                if !polled.running && session.pid.is_some() {
                    session.exit_code = polled.exit_code;
                    session.phase = Phase::Failed;
                    session.ownership = OwnershipKind::None;
                    session.pid = None;
                    session.clean_shutdown = Some(false);
                    session.message = "Owned backend exited unexpectedly.".into();
                } else if let Some(probe) = health {
                    if probe.ok == Some(true) {
                        let supervisor_bad = session.workers_expected
                            && session
                                .supervisor_health
                                .as_deref()
                                .is_some_and(|value| !supervisor_is_running(value));
                        if session.safe_mode_active {
                            session.phase = Phase::Running;
                            session.message =
                                "Backend host active. Safe Mode — API-only recovery posture.".into();
                        } else if supervisor_bad {
                            session.phase = Phase::Degraded;
                            session.message = format!(
                                "Backend host active. System degraded — Worker supervisor is {}.",
                                session.supervisor_health.as_deref().unwrap_or("UNMEASURED")
                            );
                        } else if session.workers_expected
                            && session.supervisor_health.as_deref().is_none()
                        {
                            // API alive; supervisor not yet measured — stay RUNNING, readiness STARTING.
                            session.phase = Phase::Running;
                            session.message =
                                "Backend host active. System readiness: STARTING WORKERS.".into();
                        } else {
                            session.phase = Phase::Running;
                            session.message = if session.workers_expected {
                                "Backend host active. SYSTEM READY.".into()
                            } else {
                                "Backend host active. Workers not configured.".into()
                            };
                        }
                    } else if probe.reachable {
                        session.phase = Phase::Degraded;
                        session.message = "API responded but /api/host/liveness did not report ok.".into();
                    } else {
                        session.phase = Phase::Degraded;
                        session.message = format!("Liveness probe failed: {}", probe.detail);
                    }
                }
            }
            Phase::Stopping => {
                if !polled.running {
                    session.phase = Phase::Stopped;
                    session.ownership = OwnershipKind::None;
                    session.pid = None;
                    session.exit_code = polled.exit_code;
                    session.clean_shutdown = Some(true);
                    session.safe_mode_active = false;
                    session.message = "Owned backend stopped cleanly.".into();
                } else if session.deadline.is_some_and(|deadline| Instant::now() > deadline) {
                    drop(session);
                    let _ = self.port.lock().unwrap_or_else(|p| p.into_inner()).terminate_owned();
                    let mut session = self.session.lock().unwrap_or_else(|p| p.into_inner());
                    session.phase = Phase::Stopped;
                    session.ownership = OwnershipKind::None;
                    session.pid = None;
                    session.clean_shutdown = Some(false);
                    session.safe_mode_active = false;
                    session.message = "Graceful shutdown timed out. The owned process tree was force-terminated.".into();
                }
            }
            Phase::AttachedExternal => {
                if let Some(probe) = health {
                    if !(probe.reachable && probe.ok == Some(true)) {
                        session.phase = Phase::Stopped;
                        session.ownership = OwnershipKind::None;
                        session.message = "External instance is no longer reachable. Nothing was terminated.".into();
                    }
                }
            }
            _ => {}
        }
    }

    fn ensure_startable(&self) -> Result<(), HostError> {
        let session = self.session.lock().unwrap_or_else(|p| p.into_inner());
        if session.ownership == OwnershipKind::External || session.phase == Phase::AttachedExternal {
            return Err(HostError::new(
                "An external instance is already attached. Start will not create a second control plane.",
            ));
        }
        if session.phase.busy() || matches!(session.phase, Phase::Running | Phase::Degraded) {
            return Err(HostError::new(format!(
                "Start is already in progress or the host is {}.",
                session.phase.as_str()
            )));
        }
        Ok(())
    }

    fn ensure_startable_or_preflight(&self) -> Result<(), HostError> {
        let session = self.session.lock().unwrap_or_else(|p| p.into_inner());
        if matches!(session.phase, Phase::Running | Phase::Degraded | Phase::Stopping | Phase::AttachedExternal) {
            return Err(HostError::new("duplicate start rejected"));
        }
        if session.ownership == OwnershipKind::Owned && session.pid.is_some() {
            return Err(HostError::new("duplicate start rejected"));
        }
        Ok(())
    }

    fn configured_endpoint(&self) -> (String, u16) {
        let text = fs::read_to_string(self.root.join(".env")).unwrap_or_default();
        if text.is_empty() {
            let example = fs::read_to_string(self.root.join(".env.example")).unwrap_or_default();
            paths::runtime_endpoint(&example)
        } else {
            paths::runtime_endpoint(&text)
        }
    }

    fn push_line(&self, source: &str, level: &str, stream: &str, text: &str, pid: Option<u32>) {
        let line = ConsoleLine {
            seq: 0,
            at: now_iso(),
            source: source.into(),
            level: level.into(),
            stream: stream.into(),
            text: text.into(),
            pid,
        };
        let stored = self.ring.lock().unwrap_or_else(|p| p.into_inner()).push(line);
        if let Some(log) = self.log.lock().unwrap_or_else(|p| p.into_inner()).as_mut() {
            log.write_line(&format!(
                "{} {} {} {}",
                stored.at, stored.level, stored.source, stored.text
            ));
        }
    }
}

impl Session {
    fn to_snapshot(&self, root: &Path, version: &str) -> HostSnapshot {
        let api_base = format!("http://{}:{}", self.host, self.port);
        HostSnapshot {
            state: self.phase.as_str().into(),
            ownership: self.ownership,
            safe_mode_armed: self.safe_mode_armed,
            safe_mode_active: self.safe_mode_active,
            pid: self.pid,
            exit_code: self.exit_code,
            clean_shutdown: self.clean_shutdown,
            message: self.message.clone(),
            api_base: Some(api_base.clone()),
            frontend_url: Some(format!("{api_base}/")),
            version: version.into(),
            install_root: root.display().to_string(),
            preflight: self.preflight.clone(),
            started_at: self.started_at.clone(),
            python_version: self.python_version.clone(),
            supervisor_health: self.supervisor_health.clone(),
            workers_expected: self.workers_expected,
            exit_when_stopped: self.exit_when_stopped,
            system_readiness: derive_system_readiness(self).into(),
        }
    }
}

fn derive_system_readiness(session: &Session) -> &'static str {
    match session.phase {
        Phase::Stopped | Phase::Failed => "UNMEASURED",
        Phase::Preflight | Phase::Starting | Phase::Stopping => "STARTING",
        Phase::AttachedExternal => {
            if session.safe_mode_active {
                "SAFE_MODE"
            } else if !session.workers_expected {
                "NOT_CONFIGURED"
            } else {
                match session.supervisor_health.as_deref() {
                    Some(value) if supervisor_is_running(value) => "READY",
                    Some(_) => "DEGRADED",
                    None => "UNMEASURED",
                }
            }
        }
        Phase::Running | Phase::Degraded => {
            if session.safe_mode_active {
                "SAFE_MODE"
            } else if !session.workers_expected {
                "NOT_CONFIGURED"
            } else if session.phase == Phase::Degraded {
                "DEGRADED"
            } else {
                match session.supervisor_health.as_deref() {
                    Some(value) if supervisor_is_running(value) => "READY",
                    Some(_) => "DEGRADED",
                    None => "STARTING",
                }
            }
        }
    }
}

fn supervisor_is_running(value: &str) -> bool {
    matches!(value.to_ascii_uppercase().as_str(), "RUNNING" | "READY")
}

fn empty_report() -> PreflightReport {
    PreflightReport {
        ok: false,
        checks: Vec::new(),
        host: "127.0.0.1".into(),
        port: 8765,
        python_version: None,
        native_status: None,
        workers_expected: true,
        env_created: false,
    }
}

fn prefs_path(root: &Path) -> PathBuf {
    launcher_log_dir(root).join("preferences.json")
}

fn read_preferences(root: &Path) -> UiPreferences {
    let Ok(text) = fs::read_to_string(prefs_path(root)) else {
        return UiPreferences::default();
    };
    serde_json::from_str(&text).unwrap_or_default()
}

fn write_preferences(root: &Path, prefs: &UiPreferences) {
    let path = prefs_path(root);
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if let Ok(text) = serde_json::to_string_pretty(prefs) {
        let _ = fs::write(path, text);
    }
}

fn now_iso() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64;
    let days = secs.div_euclid(86_400);
    let tod = secs.rem_euclid(86_400);
    let (year, month, day) = civil_from_days(days);
    let hour = tod / 3600;
    let minute = (tod % 3600) / 60;
    let second = tod % 60;
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z")
}

fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let mut year = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    if month <= 2 {
        year += 1;
    }
    (year, month as u32, day as u32)
}

#[cfg(unix)]
fn open_path(path: &Path) -> Result<(), String> {
    open_path_or_url(&path.display().to_string())
}

#[cfg(windows)]
fn open_path(path: &Path) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::UI::Shell::ShellExecuteW;
    use windows_sys::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;
    let wide: Vec<u16> = path.as_os_str().encode_wide().chain(std::iter::once(0)).collect();
    let op: Vec<u16> = "open".encode_utf16().chain(std::iter::once(0)).collect();
    let rc = unsafe {
        ShellExecuteW(
            std::ptr::null_mut(),
            op.as_ptr(),
            wide.as_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            SW_SHOWNORMAL,
        )
    };
    // ShellExecuteW returns an HINSTANCE. Values 32 and below are error codes, not a handle.
    let code = rc as isize;
    if code <= 32 {
        Err(format!("ShellExecute failed ({code})"))
    } else {
        Ok(())
    }
}

fn open_path_or_url(target: &str) -> Result<(), String> {
    if target.starts_with("http://") && !target.starts_with("http://127.0.0.1") && !target.starts_with("http://localhost") && !target.starts_with("http://[::1]") {
        return Err("refusing non-loopback URL".into());
    }
    let program = if cfg!(windows) { "explorer" } else { "xdg-open" };
    if cfg!(windows) && target.starts_with("http") {
        // explorer can open URLs without a shell string.
    }
    let status = std::process::Command::new(program)
        .arg(target)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map_err(|err| err.to_string())?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("{program} exited {status}"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::http_probe::ProbeResult;
    use crate::process_port::{CapturedLine, PollSnapshot, ProcessPort, SpawnSpec};
    use std::sync::{Arc, Mutex as StdMutex};

    struct FakePort {
        spawned: u32,
        running: bool,
        pid: u32,
        lines: Vec<CapturedLine>,
        /// Health observed before any child exists. True means an external instance.
        health_before: bool,
        /// Health observed after this host has spawned a child.
        health_after: bool,
        supervisor: Option<String>,
        graceful: u32,
        killed: u32,
        exit_code: Option<i32>,
    }

    impl FakePort {
        fn down() -> Self {
            Self {
                spawned: 0,
                running: false,
                pid: 0,
                lines: Vec::new(),
                health_before: false,
                health_after: false,
                supervisor: None,
                graceful: 0,
                killed: 0,
                exit_code: None,
            }
        }
    }

    impl ProcessPort for FakePort {
        fn spawn(&mut self, spec: SpawnSpec) -> Result<u32, String> {
            assert_eq!(spec.args, vec!["leviathan.py".to_string()]);
            assert!(spec.env.get("PYTHONUNBUFFERED").is_some());
            assert!(!spec.program.as_os_str().is_empty());
            self.spawned += 1;
            self.running = true;
            self.pid = 4242;
            self.lines.push(CapturedLine {
                stream: "stdout".into(),
                text: "api_key=sekret boot".into(),
                pid: Some(self.pid),
            });
            Ok(self.pid)
        }
        fn poll(&mut self) -> PollSnapshot {
            let lines = std::mem::take(&mut self.lines);
            PollSnapshot {
                running: self.running,
                exit_code: self.exit_code,
                lines,
            }
        }
        fn request_graceful(&mut self) -> Result<(), String> {
            self.graceful += 1;
            self.running = false;
            self.exit_code = Some(0);
            Ok(())
        }
        fn terminate_owned(&mut self) -> Result<(), String> {
            self.killed += 1;
            self.running = false;
            self.exit_code = Some(1);
            Ok(())
        }
        fn probe_health(&mut self, _host: &str, _port: u16) -> ProbeResult {
            let ok = if self.spawned > 0 { self.health_after } else { self.health_before };
            ProbeResult {
                reachable: ok,
                status: if ok { Some(200) } else { None },
                ok: if ok { Some(true) } else { None },
                detail: "fake".into(),
                error_kind: None,
            }
        }
        fn probe_supervisor(&mut self, _host: &str, _port: u16) -> Option<String> {
            self.supervisor.clone()
        }
    }

    fn report(ok: bool) -> PreflightReport {
        PreflightReport {
            ok,
            checks: vec![],
            host: "127.0.0.1".into(),
            port: 9,
            python_version: Some("3.12.3".into()),
            native_status: Some("BUILD_MISSING".into()),
            workers_expected: true,
            env_created: false,
        }
    }

    fn fake(before: bool, after: bool, supervisor: Option<&str>) -> FakePort {
        let mut port = FakePort::down();
        port.health_before = before;
        port.health_after = after;
        port.supervisor = supervisor.map(str::to_string);
        port
    }

    fn controller(port: FakePort) -> HostController {
        use std::sync::atomic::{AtomicU64, Ordering};
        static NEXT: AtomicU64 = AtomicU64::new(1);
        let id = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!("leviathan-ctl-{}-{id}", std::process::id()));
        let _ = fs::create_dir_all(root.join("Data/logs/launcher"));
        let _ = fs::create_dir_all(root.join(".venv/bin"));
        let _ = fs::create_dir_all(root.join(".venv/Scripts"));
        let python = if cfg!(windows) {
            root.join(".venv/Scripts/python.exe")
        } else {
            root.join(".venv/bin/python")
        };
        let _ = fs::write(&python, "");
        HostController::with_port(root, "0.1.0-test", Box::new(port), Duration::from_millis(50), Duration::from_millis(50))
    }

    #[test]
    fn duplicate_start_is_rejected_and_health_gates_running() {
        let ctl = controller(fake(false, false, Some("RUNNING")));
        let snap = ctl.start_from_report(report(true), false).unwrap();
        assert_eq!(snap.state, "STARTING");
        assert_eq!(snap.ownership, OwnershipKind::Owned);
        assert!(ctl.start_from_report(report(true), false).is_err());
        ctl.poll_once();
        let lines = ctl.console_after(0, 20);
        assert!(lines.iter().any(|line| line.text.contains("[REDACTED]")));
        assert!(!lines.iter().any(|line| line.text.contains("sekret")));
        assert_eq!(ctl.snapshot().state, "STARTING");
        // Health still false: remain STARTING until timeout.
        thread::sleep(Duration::from_millis(60));
        ctl.poll_once();
        assert_eq!(ctl.snapshot().state, "FAILED");
    }

    #[test]
    fn external_instance_is_attached_without_spawn() {
        let shared = Arc::new(StdMutex::new(0_u32));
        struct Counting(Arc<StdMutex<u32>>, FakePort);
        impl ProcessPort for Counting {
            fn spawn(&mut self, spec: SpawnSpec) -> Result<u32, String> {
                *self.0.lock().unwrap() += 1;
                self.1.spawn(spec)
            }
            fn poll(&mut self) -> PollSnapshot { self.1.poll() }
            fn request_graceful(&mut self) -> Result<(), String> { self.1.request_graceful() }
            fn terminate_owned(&mut self) -> Result<(), String> { self.1.terminate_owned() }
            fn probe_health(&mut self, h: &str, p: u16) -> ProbeResult { self.1.probe_health(h, p) }
            fn probe_supervisor(&mut self, h: &str, p: u16) -> Option<String> { self.1.probe_supervisor(h, p) }
        }
        let port = Counting(Arc::clone(&shared), fake(true, true, None));
        let ctl = controller(fake(true, true, None));
        // Rebuild with counting port.
        let ctl = HostController::with_port(
            ctl.root.clone(),
            "0.1.0-test",
            Box::new(port),
            Duration::from_millis(50),
            Duration::from_millis(50),
        );
        let snap = ctl.start_from_report(report(true), false).unwrap();
        assert_eq!(snap.state, "ATTACHED_EXTERNAL");
        assert_eq!(snap.ownership, OwnershipKind::External);
        assert_eq!(*shared.lock().unwrap(), 0);
        assert!(ctl.stop().is_err());
        assert!(ctl.emergency().is_err());
    }

    #[test]
    fn graceful_stop_records_clean_and_emergency_does_not() {
        let ctl = controller(fake(false, true, Some("RUNNING")));
        ctl.start_from_report(report(true), false).unwrap();
        ctl.poll_once();
        assert_eq!(ctl.snapshot().state, "RUNNING");
        ctl.stop().unwrap();
        ctl.poll_once();
        let snap = ctl.snapshot();
        assert_eq!(snap.state, "STOPPED");
        assert_eq!(snap.clean_shutdown, Some(true));

        let ctl = controller(fake(false, true, Some("DEGRADED")));
        ctl.start_from_report(report(true), false).unwrap();
        ctl.poll_once();
        let snap = ctl.emergency().unwrap();
        assert_eq!(snap.state, "STOPPED");
        assert_eq!(snap.clean_shutdown, Some(false));
        assert!(snap.message.to_lowercase().contains("not a clean"));
    }

    #[test]
    fn preflight_failure_does_not_spawn() {
        let ctl = controller(fake(false, false, None));
        let snap = ctl.start_from_report(report(false), true).unwrap();
        assert_eq!(snap.state, "FAILED");
        assert_eq!(snap.ownership, OwnershipKind::None);
        assert!(snap.safe_mode_armed);
    }

    #[test]
    fn safe_mode_env_is_not_written_to_dotenv() {
        use std::sync::atomic::{AtomicU64, Ordering};
        static NEXT: AtomicU64 = AtomicU64::new(1);
        let id = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!("leviathan-safe-{}-{id}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        let python = venv_python(&root);
        fs::create_dir_all(python.parent().expect("venv python parent")).unwrap();
        fs::write(&python, "").unwrap();
        fs::write(root.join(".env"), "LEVIATHAN_BOOTSTRAP_MODE=all\n").unwrap();
        let ctl = HostController::with_port(
            root.clone(),
            "0.1.0-test",
            Box::new(fake(false, false, None)),
            Duration::from_secs(2),
            Duration::from_secs(2),
        );
        ctl.start_from_report(report(true), true).unwrap();
        let text = fs::read_to_string(root.join(".env")).unwrap();
        assert!(text.contains("LEVIATHAN_BOOTSTRAP_MODE=all"));
        assert!(!text.contains("LEVIATHAN_NATIVE_COMPUTE_DISABLED"));
        assert!(ctl.snapshot().safe_mode_active);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn open_target_rejects_unknown_and_non_allowlisted() {
        let ctl = controller(fake(false, false, None));
        assert!(ctl.open_target("shell").is_err());
        assert!(ctl.open_target("frontend").is_err());
    }

    #[test]
    fn test_starting_transitions_to_running_on_liveness() {
        let ctl = controller(fake(false, true, None));
        let snap = ctl.start_from_report(report(true), false).unwrap();
        assert_eq!(snap.state, "STARTING");
        assert!(snap.message.contains("/api/host/liveness"));
        assert_eq!(snap.system_readiness, "STARTING");
        ctl.poll_once();
        let snap = ctl.snapshot();
        assert_eq!(snap.state, "RUNNING");
        assert!(!snap.message.contains("Waiting for /api/health"));
        assert!(!snap.message.contains("Waiting for /api/host/liveness"));
        // Workers expected but supervisor not yet measured → readiness STARTING, not READY.
        assert_eq!(snap.system_readiness, "STARTING");
    }

    #[test]
    fn test_worker_failure_does_not_revert_api_to_starting() {
        struct MutablePort {
            inner: FakePort,
            supervisor: Arc<StdMutex<Option<String>>>,
        }
        impl ProcessPort for MutablePort {
            fn spawn(&mut self, spec: SpawnSpec) -> Result<u32, String> {
                self.inner.spawn(spec)
            }
            fn poll(&mut self) -> PollSnapshot {
                self.inner.poll()
            }
            fn request_graceful(&mut self) -> Result<(), String> {
                self.inner.request_graceful()
            }
            fn terminate_owned(&mut self) -> Result<(), String> {
                self.inner.terminate_owned()
            }
            fn probe_health(&mut self, h: &str, p: u16) -> ProbeResult {
                self.inner.probe_health(h, p)
            }
            fn probe_supervisor(&mut self, _h: &str, _p: u16) -> Option<String> {
                self.supervisor.lock().unwrap().clone()
            }
        }

        let supervisor = Arc::new(StdMutex::new(Some("RUNNING".to_string())));
        let mut base = fake(false, true, Some("RUNNING"));
        base.supervisor = Some("RUNNING".into());
        let port = MutablePort {
            inner: base,
            supervisor: Arc::clone(&supervisor),
        };
        let ctl = HostController::with_port(
            {
                let tmp = controller(fake(false, true, None));
                tmp.root.clone()
            },
            "0.1.0-test",
            Box::new(port),
            Duration::from_millis(200),
            Duration::from_millis(50),
        );
        ctl.start_from_report(report(true), false).unwrap();
        // First poll: STARTING → RUNNING via liveness.
        ctl.poll_once();
        assert_eq!(ctl.snapshot().state, "RUNNING");
        // Force supervisor polls (every 5th poll while Running/Degraded).
        for _ in 0..6 {
            ctl.poll_once();
        }
        let snap = ctl.snapshot();
        assert_eq!(snap.state, "RUNNING");
        assert_eq!(snap.system_readiness, "READY");
        assert_eq!(snap.supervisor_health.as_deref(), Some("RUNNING"));

        *supervisor.lock().unwrap() = Some("FAILED".into());
        for _ in 0..6 {
            ctl.poll_once();
        }
        let snap = ctl.snapshot();
        assert_eq!(snap.state, "DEGRADED");
        assert_ne!(snap.state, "STARTING");
        assert_eq!(snap.system_readiness, "DEGRADED");
        assert!(snap.message.to_lowercase().contains("degraded") || snap.message.contains("FAILED"));
    }

    #[test]
    fn test_safe_mode_readiness_is_not_worker_failure() {
        let ctl = controller(fake(false, true, None));
        ctl.start_from_report(report(true), true).unwrap();
        ctl.poll_once();
        let snap = ctl.snapshot();
        assert_eq!(snap.state, "RUNNING");
        assert!(snap.safe_mode_active);
        assert_eq!(snap.system_readiness, "SAFE_MODE");
        assert!(!snap.workers_expected);
    }
}
