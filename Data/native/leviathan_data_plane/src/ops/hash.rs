//! dataset.hash — content hash of canonical JSONL.

use serde_json::json;
use sha2::{Digest, Sha256};
use std::path::Path;
use std::sync::Arc;

use crate::error::Result;
use crate::io::{content_hash_update, iter_jsonl_records};
use crate::metrics::Metrics;
use crate::ops::{empty_content_hash, finalize_hash, OpOutcome};
use crate::protocol::NativeTask;

pub fn run_hash(
    task: &NativeTask,
    input: &Path,
    output: &Path,
    metrics: Arc<Metrics>,
) -> Result<OpOutcome> {
    let mut digest = Sha256::new();
    let mut count = 0u64;
    let stats = iter_jsonl_records(
        input,
        task.limits.max_record_bytes,
        Some(&metrics),
        |_idx, rec, _| {
            content_hash_update(&mut digest, &rec)?;
            count += 1;
            Ok(())
        },
    )?;

    let hash = if count == 0 {
        empty_content_hash()
    } else {
        finalize_hash(digest, false)
    };

    let report = json!({
        "contentHash": hash,
        "rowCount": count,
        "byteSize": stats.bytes,
    });
    std::fs::write(output, serde_json::to_vec_pretty(&report)?)?;

    Ok(OpOutcome {
        records_in: count,
        records_out: count,
        bytes_in: stats.bytes,
        bytes_out: std::fs::metadata(output).map(|m| m.len()).unwrap_or(0),
        content_hash: Some(hash),
        spill_bytes: 0,
        result: Some(report),
    })
}
