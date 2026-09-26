//! Dataset operations — streaming, memory-bounded.

mod dedupe;
mod export;
mod hash;
mod parquet;
mod split;
mod transform;
mod validate;

use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs::File;
use std::io::BufWriter;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use crate::error::{DataPlaneError, Result, NATIVE_INPUT_MISSING, NATIVE_UNSUPPORTED_OPERATION};
use crate::metrics::Metrics;
use crate::protocol::{assert_path_allowed, NativeTask, TaskReceipt};

pub use dedupe::run_dedupe;
pub use export::run_export;
pub use hash::run_hash;
pub use parquet::{run_parquet_hash, run_parquet_to_jsonl, run_parquet_validate};
pub use split::run_split;
pub use transform::run_transform;
pub use validate::run_validate;

pub struct OpOutcome {
    pub records_in: u64,
    pub records_out: u64,
    pub bytes_in: u64,
    pub bytes_out: u64,
    pub content_hash: Option<String>,
    pub spill_bytes: u64,
    pub result: Option<Value>,
}

pub fn dispatch(task: &NativeTask, metrics: Arc<Metrics>) -> Result<TaskReceipt> {
    let input_path = assert_path_allowed(Path::new(&task.input.path), &task.allowed_roots)?;
    if !input_path.exists() {
        return Err(DataPlaneError::coded(
            NATIVE_INPUT_MISSING,
            format!("input path missing: {}", input_path.display()),
        ));
    }
    let output_path =
        assert_path_allowed(Path::new(&task.output.temporary_path), &task.allowed_roots)?;
    if let Some(parent) = output_path.parent() {
        std::fs::create_dir_all(parent)?;
    }

    let outcome = match task.operation.as_str() {
        "dataset.validate" => run_validate(task, &input_path, &output_path, metrics.clone())?,
        "dataset.hash" => run_hash(task, &input_path, &output_path, metrics.clone())?,
        "dataset.transform" => run_transform(task, &input_path, &output_path, metrics.clone())?,
        "dataset.split" => run_split(task, &input_path, &output_path, metrics.clone())?,
        "dataset.export" => run_export(task, &input_path, &output_path, metrics.clone())?,
        "dataset.dedupe" => run_dedupe(task, &input_path, &output_path, metrics.clone())?,
        "dataset.parquet_validate" => {
            run_parquet_validate(task, &input_path, &output_path, metrics.clone())?
        }
        "dataset.parquet_hash" => {
            run_parquet_hash(task, &input_path, &output_path, metrics.clone())?
        }
        "dataset.parquet_to_jsonl" => {
            run_parquet_to_jsonl(task, &input_path, &output_path, metrics.clone())?
        }
        other => {
            return Err(DataPlaneError::coded(
                NATIVE_UNSUPPORTED_OPERATION,
                format!("unsupported operation: {other}"),
            ));
        }
    };

    let (ri, ro, bi, bo, peak, spill) = metrics.snapshot_counts();
    let records_in = if outcome.records_in > 0 {
        outcome.records_in
    } else {
        ri
    };
    let records_out = if outcome.records_out > 0
        || matches!(
            task.operation.as_str(),
            "dataset.validate"
                | "dataset.hash"
                | "dataset.parquet_validate"
                | "dataset.parquet_hash"
        )
    {
        outcome.records_out
    } else {
        ro
    };
    let bytes_in = if outcome.bytes_in > 0 {
        outcome.bytes_in
    } else {
        bi
    };
    let bytes_out = if outcome.bytes_out > 0 {
        outcome.bytes_out
    } else {
        bo
    };
    let spill_bytes = outcome.spill_bytes.max(spill);

    Ok(TaskReceipt::ok(
        task,
        records_in,
        records_out,
        bytes_in,
        bytes_out,
        outcome.content_hash,
        metrics.duration_ms(),
        peak,
        spill_bytes,
        outcome.result,
    ))
}

pub(crate) fn open_output_writer(path: &Path) -> Result<BufWriter<File>> {
    let file = File::create(path)?;
    Ok(BufWriter::new(file))
}

pub(crate) fn finalize_hash(digest: Sha256, empty: bool) -> String {
    if empty {
        let mut h = Sha256::new();
        h.update([]);
        return hex::encode(h.finalize());
    }
    hex::encode(digest.finalize())
}

pub(crate) fn empty_content_hash() -> String {
    // Match Python sha256_text("") for empty corpus.
    let mut h = Sha256::new();
    h.update([]);
    hex::encode(h.finalize())
}

pub(crate) fn spill_dir_for(task: &NativeTask, output_path: &Path) -> Result<PathBuf> {
    let base = output_path
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."));
    let dir = base.join(format!(".leviathan-spill-{}", task.task_id));
    std::fs::create_dir_all(&dir)?;
    Ok(dir)
}
