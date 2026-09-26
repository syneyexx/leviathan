//! Versioned task / receipt / capabilities protocol (JSON file in/out).

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::{Component, Path, PathBuf};

use crate::error::{DataPlaneError, Result, NATIVE_PATH_REJECTED, NATIVE_PROTOCOL_MISMATCH};

pub const PROTOCOL_VERSION: u32 = 1;
pub const BACKEND_NAME: &str = "rust_native";
pub const BACKEND_VERSION: &str = env!("CARGO_PKG_VERSION");

pub const SUPPORTED_OPERATIONS: &[&str] = &[
    "dataset.validate",
    "dataset.hash",
    "dataset.transform",
    "dataset.split",
    "dataset.export",
    "dataset.dedupe",
    "dataset.parquet_validate",
    "dataset.parquet_hash",
    "dataset.parquet_to_jsonl",
    "market.ohlcv_validate",
];

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TaskInput {
    pub path: String,
    #[serde(default = "default_format")]
    pub format: String,
    #[serde(default)]
    pub content_hash: Option<String>,
}

fn default_format() -> String {
    "jsonl".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TaskOutput {
    pub temporary_path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TaskLimits {
    #[serde(default = "default_memory_bytes")]
    pub memory_bytes: u64,
    #[serde(default = "default_batch_rows")]
    pub batch_rows: u64,
    #[serde(default = "default_max_record_bytes")]
    pub max_record_bytes: u64,
    #[serde(default = "default_threads")]
    pub threads: u32,
    #[serde(default = "default_spill_bytes")]
    pub spill_bytes: u64,
}

fn default_memory_bytes() -> u64 {
    512 * 1024 * 1024
}
fn default_batch_rows() -> u64 {
    16_384
}
fn default_max_record_bytes() -> u64 {
    16 * 1024 * 1024
}
fn default_threads() -> u32 {
    4
}
fn default_spill_bytes() -> u64 {
    20 * 1024 * 1024 * 1024
}

impl Default for TaskLimits {
    fn default() -> Self {
        Self {
            memory_bytes: default_memory_bytes(),
            batch_rows: default_batch_rows(),
            max_record_bytes: default_max_record_bytes(),
            threads: default_threads(),
            spill_bytes: default_spill_bytes(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeTask {
    pub protocol_version: u32,
    pub task_id: String,
    pub operation: String,
    pub input: TaskInput,
    pub output: TaskOutput,
    #[serde(default)]
    pub limits: TaskLimits,
    #[serde(default)]
    pub options: Value,
    /// Optional allowlist of absolute roots; paths outside are rejected.
    #[serde(default)]
    pub allowed_roots: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BackendInfo {
    pub name: String,
    pub version: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub protocol_version: Option<u32>,
}

impl BackendInfo {
    pub fn current() -> Self {
        Self {
            name: BACKEND_NAME.to_string(),
            version: BACKEND_VERSION.to_string(),
            protocol_version: Some(PROTOCOL_VERSION),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ReceiptError {
    pub code: String,
    pub message: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TaskReceipt {
    pub protocol_version: u32,
    pub task_id: String,
    pub operation: String,
    pub status: String,
    pub records_in: u64,
    pub records_out: u64,
    pub bytes_in: u64,
    pub bytes_out: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub content_hash: Option<String>,
    pub duration_ms: u64,
    pub peak_rss_bytes: u64,
    pub spill_bytes: u64,
    pub backend: BackendInfo,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<ReceiptError>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub result: Option<Value>,
}

impl TaskReceipt {
    #[allow(clippy::too_many_arguments)]
    pub fn ok(
        task: &NativeTask,
        records_in: u64,
        records_out: u64,
        bytes_in: u64,
        bytes_out: u64,
        content_hash: Option<String>,
        duration_ms: u64,
        peak_rss_bytes: u64,
        spill_bytes: u64,
        result: Option<Value>,
    ) -> Self {
        Self {
            protocol_version: PROTOCOL_VERSION,
            task_id: task.task_id.clone(),
            operation: task.operation.clone(),
            status: "ok".to_string(),
            records_in,
            records_out,
            bytes_in,
            bytes_out,
            content_hash,
            duration_ms,
            peak_rss_bytes,
            spill_bytes,
            backend: BackendInfo::current(),
            error: None,
            result,
        }
    }

    pub fn fail(
        task_id: &str,
        operation: &str,
        code: &str,
        message: &str,
        duration_ms: u64,
        peak_rss_bytes: u64,
    ) -> Self {
        Self {
            protocol_version: PROTOCOL_VERSION,
            task_id: task_id.to_string(),
            operation: operation.to_string(),
            status: "error".to_string(),
            records_in: 0,
            records_out: 0,
            bytes_in: 0,
            bytes_out: 0,
            content_hash: None,
            duration_ms,
            peak_rss_bytes,
            spill_bytes: 0,
            backend: BackendInfo::current(),
            error: Some(ReceiptError {
                code: code.to_string(),
                message: message.to_string(),
            }),
            result: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CapabilitiesDocument {
    pub protocol_version: u32,
    pub backend: BackendInfo,
    pub operations: Vec<String>,
    pub features: CapabilitiesFeatures,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CapabilitiesFeatures {
    pub streaming: bool,
    pub external_memory_dedupe: bool,
    pub progress_stderr: bool,
    pub canonical_jsonl: bool,
    pub path_allowlist: bool,
    pub parquet: bool,
}

pub fn capabilities_document() -> CapabilitiesDocument {
    CapabilitiesDocument {
        protocol_version: PROTOCOL_VERSION,
        backend: BackendInfo::current(),
        operations: SUPPORTED_OPERATIONS
            .iter()
            .map(|s| (*s).to_string())
            .collect(),
        features: CapabilitiesFeatures {
            streaming: true,
            external_memory_dedupe: true,
            progress_stderr: true,
            canonical_jsonl: true,
            path_allowlist: true,
            parquet: true,
        },
    }
}

pub fn validate_protocol_version(version: u32) -> Result<()> {
    if version != PROTOCOL_VERSION {
        return Err(DataPlaneError::coded(
            NATIVE_PROTOCOL_MISMATCH,
            format!("expected protocolVersion={PROTOCOL_VERSION}, got {version}"),
        ));
    }
    Ok(())
}

/// Reject `..` components and paths outside optional allowed roots.
pub fn assert_path_allowed(path: &Path, allowed_roots: &[String]) -> Result<PathBuf> {
    for component in path.components() {
        if matches!(component, Component::ParentDir) {
            return Err(DataPlaneError::coded(
                NATIVE_PATH_REJECTED,
                format!("path contains '..': {}", path.display()),
            ));
        }
    }

    let resolved = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .map_err(DataPlaneError::from)?
            .join(path)
    };

    // Soft normalize without requiring the path to exist yet (output paths).
    let normalized = normalize_path(&resolved);

    if allowed_roots.is_empty() {
        return Ok(normalized);
    }

    let roots: Vec<PathBuf> = allowed_roots
        .iter()
        .map(|r| normalize_path(Path::new(r)))
        .collect();

    let ok = roots.iter().any(|root| path_under_root(&normalized, root));
    if !ok {
        return Err(DataPlaneError::coded(
            NATIVE_PATH_REJECTED,
            format!("path {} is outside allowed roots", normalized.display()),
        ));
    }
    Ok(normalized)
}

fn normalize_path(path: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for component in path.components() {
        match component {
            Component::ParentDir => {
                let _ = out.pop();
            }
            Component::CurDir => {}
            other => out.push(other.as_os_str()),
        }
    }
    out
}

fn path_under_root(path: &Path, root: &Path) -> bool {
    let path_comps: Vec<_> = path.components().collect();
    let root_comps: Vec<_> = root.components().collect();
    if path_comps.len() < root_comps.len() {
        return false;
    }
    path_comps
        .iter()
        .zip(root_comps.iter())
        .all(|(a, b)| a == b)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_parent_dir() {
        let err = assert_path_allowed(Path::new("/tmp/foo/../etc/passwd"), &[]).unwrap_err();
        assert_eq!(err.code(), NATIVE_PATH_REJECTED);
    }

    #[test]
    fn allowlist_enforced() {
        let roots = vec!["/workspace/data".to_string()];
        assert!(assert_path_allowed(Path::new("/workspace/data/a.jsonl"), &roots).is_ok());
        let err = assert_path_allowed(Path::new("/etc/passwd"), &roots).unwrap_err();
        assert_eq!(err.code(), NATIVE_PATH_REJECTED);
    }

    #[test]
    fn protocol_version_gate() {
        assert!(validate_protocol_version(PROTOCOL_VERSION).is_ok());
        assert_eq!(
            validate_protocol_version(99).unwrap_err().code(),
            NATIVE_PROTOCOL_MISMATCH
        );
    }
}
