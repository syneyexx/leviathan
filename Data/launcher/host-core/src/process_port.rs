use std::collections::{HashMap, VecDeque};
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use crate::http_probe::{self, ProbeResult};

#[derive(Clone, Debug)]
pub struct SpawnSpec {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub cwd: PathBuf,
    pub env: HashMap<String, String>,
}

#[derive(Clone, Debug)]
pub struct CapturedLine {
    pub stream: String,
    pub text: String,
    pub pid: Option<u32>,
}

#[derive(Clone, Debug)]
pub struct PollSnapshot {
    pub running: bool,
    pub exit_code: Option<i32>,
    pub lines: Vec<CapturedLine>,
}

pub trait ProcessPort: Send {
    fn spawn(&mut self, spec: SpawnSpec) -> Result<u32, String>;
    fn poll(&mut self) -> PollSnapshot;
    fn request_graceful(&mut self) -> Result<(), String>;
    fn terminate_owned(&mut self) -> Result<(), String>;
    fn probe_health(&mut self, host: &str, port: u16) -> ProbeResult;
    fn probe_supervisor(&mut self, host: &str, port: u16) -> Option<String>;
}

struct OwnedChild {
    child: Child,
    pid: u32,
    lines: Arc<Mutex<VecDeque<CapturedLine>>>,
    graceful_sent: bool,
    #[cfg(windows)]
    job: Option<isize>,
}

pub struct SystemProcessPort {
    child: Option<OwnedChild>,
    last_exit: Option<i32>,
}

impl SystemProcessPort {
    pub fn new() -> Self {
        Self {
            child: None,
            last_exit: None,
        }
    }
}

impl Default for SystemProcessPort {
    fn default() -> Self {
        Self::new()
    }
}

impl ProcessPort for SystemProcessPort {
    fn spawn(&mut self, spec: SpawnSpec) -> Result<u32, String> {
        if self.child.is_some() {
            return Err("a child is already owned".into());
        }
        let mut command = Command::new(&spec.program);
        command
            .args(&spec.args)
            .current_dir(&spec.cwd)
            .env_clear()
            .envs(&spec.env)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            command.process_group(0);
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            // Hidden process, new group. Job-object ownership is applied after spawn.
            // CREATE_NO_WINDOW avoids a loose console. Graceful console-control may be
            // unavailable; the stop path then records an unclean job termination.
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
            command.creation_flags(CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW);
        }
        let mut child = command.spawn().map_err(|err| format!("spawn failed: {err}"))?;
        let pid = child.id();
        let lines = Arc::new(Mutex::new(VecDeque::new()));
        if let Some(stdout) = child.stdout.take() {
            let queue = Arc::clone(&lines);
            thread::spawn(move || {
                let reader = BufReader::new(stdout);
                for line in reader.lines() {
                    match line {
                        Ok(text) => push_line(&queue, "stdout", text, Some(pid)),
                        Err(_) => break,
                    }
                }
            });
        }
        if let Some(stderr) = child.stderr.take() {
            let queue = Arc::clone(&lines);
            thread::spawn(move || {
                let reader = BufReader::new(stderr);
                for line in reader.lines() {
                    match line {
                        Ok(text) => push_line(&queue, "stderr", text, Some(pid)),
                        Err(_) => break,
                    }
                }
            });
        }
        #[cfg(windows)]
        let job = assign_job(pid);
        self.child = Some(OwnedChild {
            child,
            pid,
            lines,
            graceful_sent: false,
            #[cfg(windows)]
            job,
        });
        self.last_exit = None;
        Ok(pid)
    }

    fn poll(&mut self) -> PollSnapshot {
        let Some(owned) = self.child.as_mut() else {
            return PollSnapshot {
                running: false,
                exit_code: self.last_exit,
                lines: Vec::new(),
            };
        };
        let lines = drain_lines(&owned.lines);
        match owned.child.try_wait() {
            Ok(Some(status)) => {
                let code = status.code();
                self.last_exit = code;
                self.child = None;
                PollSnapshot {
                    running: false,
                    exit_code: code,
                    lines,
                }
            }
            Ok(None) => PollSnapshot {
                running: true,
                exit_code: None,
                lines,
            },
            Err(err) => {
                push_line(&owned.lines, "stderr", format!("wait failed: {err}"), Some(owned.pid));
                PollSnapshot {
                    running: true,
                    exit_code: None,
                    lines,
                }
            }
        }
    }

    fn request_graceful(&mut self) -> Result<(), String> {
        let Some(owned) = self.child.as_mut() else {
            return Err("no owned process".into());
        };
        if owned.graceful_sent {
            return Ok(());
        }
        owned.graceful_sent = true;
        graceful_stop(owned.pid)
    }

    fn terminate_owned(&mut self) -> Result<(), String> {
        let Some(mut owned) = self.child.take() else {
            return Ok(());
        };
        force_stop(&mut owned)?;
        match owned.child.wait() {
            Ok(status) => {
                self.last_exit = status.code();
            }
            Err(err) => return Err(err.to_string()),
        }
        Ok(())
    }

    fn probe_health(&mut self, host: &str, port: u16) -> ProbeResult {
        http_probe::probe_health(host, port, Duration::from_millis(1200))
    }

    fn probe_supervisor(&mut self, host: &str, port: u16) -> Option<String> {
        http_probe::probe_supervisor_health(host, port, Duration::from_millis(1200))
    }
}

fn push_line(queue: &Mutex<VecDeque<CapturedLine>>, stream: &str, text: String, pid: Option<u32>) {
    let mut guard = match queue.lock() {
        Ok(guard) => guard,
        Err(poison) => poison.into_inner(),
    };
    if guard.len() > 5_000 {
        guard.pop_front();
    }
    guard.push_back(CapturedLine {
        stream: stream.into(),
        text,
        pid,
    });
}

fn drain_lines(queue: &Mutex<VecDeque<CapturedLine>>) -> Vec<CapturedLine> {
    let mut guard = match queue.lock() {
        Ok(guard) => guard,
        Err(poison) => poison.into_inner(),
    };
    guard.drain(..).collect()
}

#[cfg(unix)]
fn graceful_stop(pid: u32) -> Result<(), String> {
    let rc = unsafe { libc::kill(-(pid as i32), libc::SIGTERM) };
    if rc == 0 {
        Ok(())
    } else {
        let rc = unsafe { libc::kill(pid as i32, libc::SIGTERM) };
        if rc == 0 {
            Ok(())
        } else {
            Err(format!("SIGTERM failed: {}", std::io::Error::last_os_error()))
        }
    }
}

#[cfg(unix)]
fn force_stop(owned: &mut OwnedChild) -> Result<(), String> {
    let _ = unsafe { libc::kill(-(owned.pid as i32), libc::SIGKILL) };
    let _ = unsafe { libc::kill(owned.pid as i32, libc::SIGKILL) };
    let _ = owned.child.kill();
    Ok(())
}

#[cfg(windows)]
fn graceful_stop(pid: u32) -> Result<(), String> {
    // Attempt console-control break. CREATE_NO_WINDOW children often have no
    // console, in which case this returns an error and the controller waits
    // out the grace period before terminating the owned job only.
    use windows_sys::Win32::System::Console::{
        AttachConsole, FreeConsole, GenerateConsoleCtrlEvent, SetConsoleCtrlHandler, CTRL_BREAK_EVENT,
    };
    unsafe {
        if AttachConsole(pid) == 0 {
            return Err(format!(
                "graceful console control unavailable: {}",
                std::io::Error::last_os_error()
            ));
        }
        SetConsoleCtrlHandler(None, 1);
        let ok = GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, pid);
        let _ = FreeConsole();
        if ok == 0 {
            Err(format!(
                "CTRL_BREAK failed: {}",
                std::io::Error::last_os_error()
            ))
        } else {
            Ok(())
        }
    }
}

#[cfg(windows)]
fn assign_job(pid: u32) -> Option<isize> {
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };
    use windows_sys::Win32::System::Threading::{OpenProcess, PROCESS_ALL_ACCESS};
    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            return None;
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let set = SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const _,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        if set == 0 {
            CloseHandle(job);
            return None;
        }
        let process = OpenProcess(PROCESS_ALL_ACCESS, 0, pid);
        if process.is_null() {
            CloseHandle(job);
            return None;
        }
        let assigned = AssignProcessToJobObject(job, process);
        CloseHandle(process);
        if assigned == 0 {
            CloseHandle(job);
            return None;
        }
        Some(job as isize)
    }
}

#[cfg(windows)]
fn force_stop(owned: &mut OwnedChild) -> Result<(), String> {
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::JobObjects::TerminateJobObject;
    unsafe {
        if let Some(job) = owned.job.take() {
            let handle = job as *mut _;
            let _ = TerminateJobObject(handle, 1);
            CloseHandle(handle);
        }
    }
    let _ = owned.child.kill();
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{PollSnapshot, ProcessPort, SpawnSpec, SystemProcessPort};
    use std::collections::HashMap;
    use std::io::Write;
    use std::thread;
    use std::time::{Duration, Instant};

    const CHILD_TEST: &str = "process_port::tests::process_port_child_helper";

    /// Test-only child. Ordinary `cargo test` runs leave immediately.
    /// The ownership test spawns this same executable with the marker set.
    #[test]
    fn process_port_child_helper() {
        if std::env::var_os("LEVIATHAN_PROCESS_PORT_TEST_CHILD").is_none() {
            return;
        }
        println!("hello-host");
        let _ = std::io::stdout().flush();
        thread::sleep(Duration::from_secs(30));
    }

    #[test]
    fn spawns_owned_process_captures_output_and_stops_group() {
        let mut port = SystemProcessPort::new();
        let exe = std::env::current_exe().expect("current test executable");
        let pid = port
            .spawn(SpawnSpec {
                program: exe,
                args: vec![CHILD_TEST.into(), "--exact".into(), "--nocapture".into()],
                cwd: std::env::temp_dir(),
                env: child_env(),
            })
            .expect("spawn");
        assert!(pid > 0);

        let started = Instant::now();
        let mut saw = false;
        while started.elapsed() < Duration::from_secs(5) {
            let snap = port.poll();
            if snap.lines.iter().any(|line| line.text.contains("hello-host")) {
                saw = true;
                break;
            }
            thread::sleep(Duration::from_millis(50));
        }
        assert!(saw, "stdout was not captured");

        let mut exited = false;
        match port.request_graceful() {
            Ok(()) => {
                let started = Instant::now();
                while started.elapsed() < Duration::from_secs(5) {
                    let snap: PollSnapshot = port.poll();
                    if !snap.running {
                        exited = true;
                        break;
                    }
                    thread::sleep(Duration::from_millis(50));
                }
            }
            Err(err) if cfg!(windows) && graceful_console_unavailable(&err) => {
                // CREATE_NO_WINDOW children often have no console, so CTRL_BREAK
                // is not a process-ownership failure. The owned-job fallback is next.
            }
            Err(err) => panic!("graceful stop failed: {err}"),
        }
        if !exited {
            port.terminate_owned().expect("owned termination");
        }
        let snap = port.poll();
        assert!(!snap.running, "owned process is still running");
        assert_pid_dead(pid);
    }

    fn graceful_console_unavailable(err: &str) -> bool {
        err.contains("graceful console control unavailable") || err.contains("CTRL_BREAK failed")
    }

    fn child_env() -> HashMap<String, String> {
        let mut env = HashMap::new();
        env.insert("LEVIATHAN_PROCESS_PORT_TEST_CHILD".into(), "1".into());
        // A cleared environment can stop a Windows process from initializing.
        // These are inherited only by the test child, not by production spawns.
        for key in ["SYSTEMROOT", "SystemRoot", "WINDIR", "PATHEXT", "TMP", "TEMP"] {
            if let Ok(value) = std::env::var(key) {
                env.insert(key.to_string(), value);
            }
        }
        env
    }

    fn assert_pid_dead(pid: u32) {
        #[cfg(unix)]
        {
            let alive = unsafe { libc::kill(pid as i32, 0) } == 0;
            assert!(!alive, "owned pid {pid} is still alive");
        }
        #[cfg(windows)]
        {
            use windows_sys::Win32::Foundation::CloseHandle;
            use windows_sys::Win32::System::Threading::{
                GetExitCodeProcess, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION,
            };
            const STILL_ACTIVE: u32 = 259;
            unsafe {
                let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
                if handle.is_null() {
                    return;
                }
                let mut code = STILL_ACTIVE;
                let ok = GetExitCodeProcess(handle, &mut code);
                CloseHandle(handle);
                assert!(ok != 0, "GetExitCodeProcess failed for owned pid {pid}");
                assert_ne!(code, STILL_ACTIVE, "owned pid {pid} is still alive");
            }
        }
    }
}
