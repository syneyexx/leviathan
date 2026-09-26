//! Parquet-native dataset operations.

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::io::Write;
use std::path::Path;
use std::sync::Arc;

use crate::error::Result;
use crate::io::{
    content_hash_update, iter_parquet_records, open_parquet_schema, write_canonical_line,
    ParquetFieldInfo, ParquetRowKind,
};
use crate::metrics::Metrics;
use crate::ops::{empty_content_hash, finalize_hash, open_output_writer, OpOutcome};
use crate::protocol::NativeTask;

fn schema_fields_json(fields: &[ParquetFieldInfo]) -> Value {
    Value::Array(
        fields
            .iter()
            .map(|f| {
                json!({
                    "name": f.name,
                    "dataType": f.data_type,
                    "nullable": f.nullable,
                })
            })
            .collect(),
    )
}

fn row_kind_str(kind: ParquetRowKind) -> &'static str {
    match kind {
        ParquetRowKind::Text => "text",
        ParquetRowKind::Market => "market",
        ParquetRowKind::Unknown => "unknown",
    }
}

/// `dataset.parquet_validate` — scan parquet, count rows, enforce limits, report schema.
pub fn run_parquet_validate(
    task: &NativeTask,
    input: &Path,
    output: &Path,
    metrics: Arc<Metrics>,
) -> Result<OpOutcome> {
    let (stats, report) = iter_parquet_records(
        input,
        task.limits.batch_rows,
        task.limits.max_record_bytes,
        Some(&metrics),
        |_idx, _rec, _| Ok(()),
    )?;

    let report_json = json!({
        "valid": true,
        "rowCount": stats.records,
        "batchCount": stats.batches,
        "skippedEmpty": stats.skipped_empty,
        "byteSizeEstimate": stats.bytes,
        "rowKind": row_kind_str(report.row_kind),
        "numRowGroups": report.num_row_groups,
        "metadataNumRows": report.metadata_num_rows,
        "schema": {
            "fields": schema_fields_json(&report.fields),
        },
        "limits": {
            "batchRows": task.limits.batch_rows,
            "maxRecordBytes": task.limits.max_record_bytes,
        },
    });

    std::fs::write(output, serde_json::to_vec_pretty(&report_json)?)?;

    Ok(OpOutcome {
        records_in: stats.records,
        records_out: stats.records,
        bytes_in: stats.bytes,
        bytes_out: std::fs::metadata(output).map(|m| m.len()).unwrap_or(0),
        content_hash: None,
        spill_bytes: 0,
        result: Some(report_json),
    })
}

/// `dataset.parquet_hash` — deterministic content hash of canonical row payloads in file order.
pub fn run_parquet_hash(
    task: &NativeTask,
    input: &Path,
    output: &Path,
    metrics: Arc<Metrics>,
) -> Result<OpOutcome> {
    let mut digest = Sha256::new();
    let mut count = 0u64;
    let (stats, report) = iter_parquet_records(
        input,
        task.limits.batch_rows,
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

    let report_json = json!({
        "contentHash": hash,
        "rowCount": count,
        "byteSizeEstimate": stats.bytes,
        "rowKind": row_kind_str(report.row_kind),
        "schema": {
            "fields": schema_fields_json(&report.fields),
        },
    });
    std::fs::write(output, serde_json::to_vec_pretty(&report_json)?)?;

    Ok(OpOutcome {
        records_in: count,
        records_out: count,
        bytes_in: stats.bytes,
        bytes_out: std::fs::metadata(output).map(|m| m.len()).unwrap_or(0),
        content_hash: Some(hash),
        spill_bytes: 0,
        result: Some(report_json),
    })
}

/// `dataset.parquet_to_jsonl` — stream convert parquet rows to canonical JSONL.
pub fn run_parquet_to_jsonl(
    task: &NativeTask,
    input: &Path,
    output: &Path,
    metrics: Arc<Metrics>,
) -> Result<OpOutcome> {
    // Schema probe early for clearer errors on empty/corrupt files.
    let _ = open_parquet_schema(input)?;

    let mut writer = open_output_writer(output)?;
    let mut digest = Sha256::new();
    let mut count = 0u64;
    let mut bytes_out = 0u64;

    let (stats, report) = iter_parquet_records(
        input,
        task.limits.batch_rows,
        task.limits.max_record_bytes,
        Some(&metrics),
        |_idx, rec, _| {
            let n = write_canonical_line(&mut writer, &rec, Some(&mut digest), Some(&metrics))?;
            bytes_out += n as u64;
            count += 1;
            Ok(())
        },
    )?;

    writer.flush()?;
    drop(writer);

    let hash = if count == 0 {
        empty_content_hash()
    } else {
        finalize_hash(digest, false)
    };

    let summary = json!({
        "contentHash": hash,
        "rowCount": count,
        "outputPath": output.display().to_string(),
        "rowKind": row_kind_str(report.row_kind),
        "schema": {
            "fields": schema_fields_json(&report.fields),
        },
    });
    // Sidecar summary next to JSONL for receipt.result (output itself is JSONL).
    let summary_path = format!("{}.summary.json", output.display());
    std::fs::write(&summary_path, serde_json::to_vec_pretty(&summary)?)?;

    Ok(OpOutcome {
        records_in: stats.records,
        records_out: count,
        bytes_in: stats.bytes,
        bytes_out,
        content_hash: Some(hash),
        spill_bytes: 0,
        result: Some(summary),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::{NativeTask, PROTOCOL_VERSION, TaskInput, TaskLimits, TaskOutput};
    use arrow_array::{RecordBatch, StringArray};
    use arrow_schema::{DataType, Field, Schema};
    use parquet::arrow::ArrowWriter;
    use std::sync::Arc;
    use tempfile::tempdir;

    fn tiny_task(op: &str, input: &Path, output: &Path, root: &Path) -> NativeTask {
        NativeTask {
            protocol_version: PROTOCOL_VERSION,
            task_id: "parquet-test".into(),
            operation: op.into(),
            input: TaskInput {
                path: input.display().to_string(),
                format: "parquet".into(),
                content_hash: None,
            },
            output: TaskOutput {
                temporary_path: output.display().to_string(),
            },
            limits: TaskLimits {
                batch_rows: 64,
                max_record_bytes: 1_000_000,
                ..Default::default()
            },
            options: json!({}),
            allowed_roots: vec![root.display().to_string()],
        }
    }

    fn write_fixture(path: &Path) {
        let schema = Arc::new(Schema::new(vec![
            Field::new("id", DataType::Utf8, false),
            Field::new("text", DataType::Utf8, false),
        ]));
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(StringArray::from(vec!["a", "b"])),
                Arc::new(StringArray::from(vec!["one", "two"])),
            ],
        )
        .unwrap();
        let file = std::fs::File::create(path).unwrap();
        let mut writer = ArrowWriter::try_new(file, schema, None).unwrap();
        writer.write(&batch).unwrap();
        writer.close().unwrap();
    }

    #[test]
    fn validate_and_hash_and_jsonl() {
        let dir = tempdir().unwrap();
        let input = dir.path().join("t.parquet");
        write_fixture(&input);

        let out_v = dir.path().join("validate.json");
        let task_v = tiny_task("dataset.parquet_validate", &input, &out_v, dir.path());
        let metrics = Metrics::new("t", "dataset.parquet_validate");
        let outcome = run_parquet_validate(&task_v, &input, &out_v, metrics).unwrap();
        assert_eq!(outcome.records_in, 2);
        let report: Value = serde_json::from_slice(&std::fs::read(&out_v).unwrap()).unwrap();
        assert_eq!(report["rowCount"], 2);
        assert_eq!(report["rowKind"], "text");

        let out_h = dir.path().join("hash.json");
        let task_h = tiny_task("dataset.parquet_hash", &input, &out_h, dir.path());
        let metrics = Metrics::new("t", "dataset.parquet_hash");
        let outcome = run_parquet_hash(&task_h, &input, &out_h, metrics).unwrap();
        assert!(outcome.content_hash.is_some());
        let hash1 = outcome.content_hash.clone().unwrap();

        // Deterministic
        let metrics = Metrics::new("t", "dataset.parquet_hash");
        let outcome2 = run_parquet_hash(&task_h, &input, &out_h, metrics).unwrap();
        assert_eq!(outcome2.content_hash.as_ref().unwrap(), &hash1);

        let out_j = dir.path().join("out.jsonl");
        let task_j = tiny_task("dataset.parquet_to_jsonl", &input, &out_j, dir.path());
        let metrics = Metrics::new("t", "dataset.parquet_to_jsonl");
        let outcome = run_parquet_to_jsonl(&task_j, &input, &out_j, metrics).unwrap();
        assert_eq!(outcome.records_out, 2);
        let text = std::fs::read_to_string(&out_j).unwrap();
        assert_eq!(text.lines().count(), 2);
        assert!(text.contains("\"id\":\"a\""));
    }
}
