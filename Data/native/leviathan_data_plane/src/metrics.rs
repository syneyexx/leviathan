//! Lightweight progress + RSS metrics for the native data-plane.

use serde::Serialize;
use std::io::{self, Write};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Instant;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProgressEvent {
    #[serde(rename = "type")]
    pub event_type: &'static str,
    pub task_id: String,
    pub operation: String,
    pub records_in: u64,
    pub records_out: u64,
    pub bytes_in: u64,
    pub phase: String,
}

#[derive(Debug)]
pub struct Metrics {
    pub task_id: String,
    pub operation: String,
    pub started: Instant,
    pub records_in: AtomicU64,
    pub records_out: AtomicU64,
    pub bytes_in: AtomicU64,
    pub bytes_out: AtomicU64,
    pub spill_bytes: AtomicU64,
    pub peak_rss_bytes: AtomicU64,
    last_progress_at: AtomicU64,
    progress_every_rows: u64,
}

impl Metrics {
    pub fn new(task_id: impl Into<String>, operation: impl Into<String>) -> Arc<Self> {
        Arc::new(Self {
            task_id: task_id.into(),
            operation: operation.into(),
            started: Instant::now(),
            records_in: AtomicU64::new(0),
            records_out: AtomicU64::new(0),
            bytes_in: AtomicU64::new(0),
            bytes_out: AtomicU64::new(0),
            spill_bytes: AtomicU64::new(0),
            peak_rss_bytes: AtomicU64::new(current_rss_bytes()),
            last_progress_at: AtomicU64::new(0),
            progress_every_rows: 10_000,
        })
    }

    pub fn duration_ms(&self) -> u64 {
        self.started.elapsed().as_millis() as u64
    }

    pub fn bump_in(&self, records: u64, bytes: u64) {
        self.records_in.fetch_add(records, Ordering::Relaxed);
        self.bytes_in.fetch_add(bytes, Ordering::Relaxed);
        self.sample_rss();
        self.maybe_progress("read");
    }

    pub fn bump_out(&self, records: u64, bytes: u64) {
        self.records_out.fetch_add(records, Ordering::Relaxed);
        self.bytes_out.fetch_add(bytes, Ordering::Relaxed);
        self.sample_rss();
        self.maybe_progress("write");
    }

    pub fn set_spill(&self, bytes: u64) {
        self.spill_bytes.store(bytes, Ordering::Relaxed);
        self.sample_rss();
    }

    pub fn sample_rss(&self) {
        let rss = current_rss_bytes();
        let mut cur = self.peak_rss_bytes.load(Ordering::Relaxed);
        while rss > cur {
            match self.peak_rss_bytes.compare_exchange_weak(
                cur,
                rss,
                Ordering::Relaxed,
                Ordering::Relaxed,
            ) {
                Ok(_) => break,
                Err(v) => cur = v,
            }
        }
    }

    fn maybe_progress(&self, phase: &str) {
        let in_count = self.records_in.load(Ordering::Relaxed);
        let last = self.last_progress_at.load(Ordering::Relaxed);
        if in_count.saturating_sub(last) < self.progress_every_rows && in_count != last {
            return;
        }
        if self
            .last_progress_at
            .compare_exchange(last, in_count, Ordering::Relaxed, Ordering::Relaxed)
            .is_err()
        {
            return;
        }
        emit_progress(ProgressEvent {
            event_type: "progress",
            task_id: self.task_id.clone(),
            operation: self.operation.clone(),
            records_in: in_count,
            records_out: self.records_out.load(Ordering::Relaxed),
            bytes_in: self.bytes_in.load(Ordering::Relaxed),
            phase: phase.to_string(),
        });
    }

    pub fn snapshot_counts(&self) -> (u64, u64, u64, u64, u64, u64) {
        (
            self.records_in.load(Ordering::Relaxed),
            self.records_out.load(Ordering::Relaxed),
            self.bytes_in.load(Ordering::Relaxed),
            self.bytes_out.load(Ordering::Relaxed),
            self.peak_rss_bytes.load(Ordering::Relaxed),
            self.spill_bytes.load(Ordering::Relaxed),
        )
    }
}

pub fn emit_progress(event: ProgressEvent) {
    if let Ok(line) = serde_json::to_string(&event) {
        let mut err = io::stderr().lock();
        let _ = writeln!(err, "{line}");
        let _ = err.flush();
    }
}

/// Best-effort RSS in bytes (Linux VmRSS; 0 elsewhere).
pub fn current_rss_bytes() -> u64 {
    #[cfg(target_os = "linux")]
    {
        if let Ok(status) = std::fs::read_to_string("/proc/self/status") {
            for line in status.lines() {
                if let Some(rest) = line.strip_prefix("VmRSS:") {
                    let kb: u64 = rest
                        .split_whitespace()
                        .next()
                        .and_then(|s| s.parse().ok())
                        .unwrap_or(0);
                    return kb.saturating_mul(1024);
                }
            }
        }
    }
    0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn metrics_counts() {
        let m = Metrics::new("t1", "dataset.hash");
        m.bump_in(2, 10);
        m.bump_out(1, 5);
        let (ri, ro, bi, bo, _, _) = m.snapshot_counts();
        assert_eq!((ri, ro, bi, bo), (2, 1, 10, 5));
    }
}
