use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::Path;

use fs2::FileExt;

#[derive(Debug)]
pub struct InstanceLock {
    _file: File,
}

#[derive(Debug)]
pub enum InstanceLockError {
    AlreadyRunning { pid: Option<u32> },
    Io(String),
}

impl InstanceLock {
    pub fn acquire(path: &Path) -> Result<Self, InstanceLockError> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|err| InstanceLockError::Io(err.to_string()))?;
        }
        let mut file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(path)
            .map_err(|err| InstanceLockError::Io(err.to_string()))?;
        match file.try_lock_exclusive() {
            Ok(()) => {
                file.set_len(0).ok();
                let _ = write!(file, "{}", std::process::id());
                let _ = file.flush();
                Ok(Self { _file: file })
            }
            Err(_) => {
                let mut buf = String::new();
                let _ = file.read_to_string(&mut buf);
                let pid = buf.trim().parse::<u32>().ok();
                Err(InstanceLockError::AlreadyRunning { pid })
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{InstanceLock, InstanceLockError};
    use std::fs;

    #[test]
    fn second_acquire_fails_without_starting_another_owner() {
        let path = std::env::temp_dir().join(format!("leviathan-lock-{}-{}.lock", std::process::id(), line!()));
        let _ = fs::remove_file(&path);
        let first = InstanceLock::acquire(&path).expect("first lock");
        match InstanceLock::acquire(&path) {
            Err(InstanceLockError::AlreadyRunning { pid }) => {
                assert_eq!(pid, Some(std::process::id()));
            }
            other => panic!("expected already running, got {other:?}"),
        }
        drop(first);
        let _ = fs::remove_file(path);
    }
}
