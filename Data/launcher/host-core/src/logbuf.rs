use std::collections::VecDeque;
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::Path;

use serde::Serialize;

use crate::redaction::redact_line;

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ConsoleLine {
    pub seq: u64,
    pub at: String,
    pub source: String,
    pub level: String,
    pub stream: String,
    pub text: String,
    pub pid: Option<u32>,
}

pub struct LogRing {
    lines: VecDeque<ConsoleLine>,
    next_seq: u64,
    capacity: usize,
}

impl LogRing {
    pub fn new(capacity: usize) -> Self {
        Self {
            lines: VecDeque::new(),
            next_seq: 1,
            capacity: capacity.max(1),
        }
    }

    pub fn push(&mut self, mut line: ConsoleLine) -> ConsoleLine {
        line.text = redact_line(&line.text);
        line.seq = self.next_seq;
        self.next_seq = self.next_seq.saturating_add(1);
        if self.lines.len() >= self.capacity {
            self.lines.pop_front();
        }
        self.lines.push_back(line.clone());
        line
    }

    pub fn after(&self, seq: u64, limit: usize) -> Vec<ConsoleLine> {
        self.lines
            .iter()
            .filter(|line| line.seq > seq)
            .take(limit.max(1))
            .cloned()
            .collect()
    }

    pub fn len(&self) -> usize {
        self.lines.len()
    }
}

pub struct RotatingLog {
    path: std::path::PathBuf,
    max_bytes: u64,
    file: File,
}

impl RotatingLog {
    pub fn open(path: &Path, max_bytes: u64) -> std::io::Result<Self> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let file = OpenOptions::new().create(true).append(true).open(path)?;
        Ok(Self {
            path: path.to_path_buf(),
            max_bytes: max_bytes.max(64 * 1024),
            file,
        })
    }

    pub fn write_line(&mut self, line: &str) {
        let redacted = redact_line(line);
        if self.file.metadata().map(|m| m.len()).unwrap_or(0) > self.max_bytes {
            let rotated = self.path.with_extension("log.1");
            let _ = fs::rename(&self.path, rotated);
            if let Ok(file) = OpenOptions::new().create(true).append(true).open(&self.path) {
                self.file = file;
            }
        }
        let _ = writeln!(self.file, "{redacted}");
    }
}

#[cfg(test)]
mod tests {
    use super::{ConsoleLine, LogRing};

    fn line(text: &str) -> ConsoleLine {
        ConsoleLine {
            seq: 0,
            at: "t".into(),
            source: "host".into(),
            level: "info".into(),
            stream: "stdout".into(),
            text: text.into(),
            pid: None,
        }
    }

    #[test]
    fn ring_is_bounded_and_redacts() {
        let mut ring = LogRing::new(3);
        ring.push(line("one"));
        ring.push(line("api_key=sekret"));
        ring.push(line("three"));
        ring.push(line("four"));
        assert_eq!(ring.len(), 3);
        let rows = ring.after(0, 10);
        assert_eq!(rows[0].text, "api_key=[REDACTED]");
        assert_eq!(rows[2].text, "four");
        assert!(rows.iter().all(|row| row.seq > 1));
    }
}
