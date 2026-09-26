//! dataset.export — optional split filter, write JSONL, hash.

use sha2::{Digest, Sha256};
use std::path::Path;
use std::sync::Arc;

use crate::error::Result;
use crate::io::{iter_jsonl_records, write_canonical_line};
use crate::metrics::Metrics;
use crate::ops::{empty_content_hash, finalize_hash, open_output_writer, OpOutcome};
use crate::protocol::NativeTask;

pub fn run_export(
    task: &NativeTask,
    input: &Path,
    output: &Path,
    metrics: Arc<Metrics>,
) -> Result<OpOutcome> {
    let split_filter = task
        .options
        .get("split")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    let mut writer = open_output_writer(output)?;
    let mut digest = Sha256::new();
    let mut out_count = 0u64;

    let stats = iter_jsonl_records(
        input,
        task.limits.max_record_bytes,
        Some(&metrics),
        |_idx, rec, _| {
            if let Some(ref want) = split_filter {
                match rec.split.as_deref() {
                    Some(s) if s == want => {}
                    _ => return Ok(()),
                }
            }
            write_canonical_line(&mut writer, &rec, Some(&mut digest), Some(&metrics))?;
            out_count += 1;
            Ok(())
        },
    )?;

    writer.get_mut().sync_all().ok();
    drop(writer);

    let hash = if out_count == 0 {
        empty_content_hash()
    } else {
        finalize_hash(digest, false)
    };

    let bytes_out = std::fs::metadata(output).map(|m| m.len()).unwrap_or(0);
    Ok(OpOutcome {
        records_in: stats.records,
        records_out: out_count,
        bytes_in: stats.bytes,
        bytes_out,
        content_hash: Some(hash.clone()),
        spill_bytes: 0,
        result: Some(serde_json::json!({
            "path": output.display().to_string(),
            "contentHash": hash,
            "byteSize": bytes_out,
            "rowCount": out_count,
            "split": split_filter,
            "format": "jsonl",
        })),
    })
}
