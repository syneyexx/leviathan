//! `market.ohlcv_validate` — deterministic high-volume OHLCV streaming validate.

use serde_json::json;
use std::path::Path;
use std::sync::Arc;

use crate::error::{DataPlaneError, Result, NATIVE_INPUT_INVALID};
use crate::io::{iter_ohlcv_validate, OhlcvFormat};
use crate::metrics::Metrics;
use crate::ops::OpOutcome;
use crate::protocol::NativeTask;

/// Validate CSV / JSONL / Parquet OHLCV without materializing the full series.
pub fn run_ohlcv_validate(
    task: &NativeTask,
    input: &Path,
    output: &Path,
    metrics: Arc<Metrics>,
) -> Result<OpOutcome> {
    let format = OhlcvFormat::detect(input, &task.input.format)?;
    let scan = match iter_ohlcv_validate(
        input,
        format,
        task.limits.batch_rows,
        Some(&metrics),
        |_idx, _bar| Ok(()),
    ) {
        Ok(s) => s,
        Err(e) => {
            // Structured failure report (parity with Python OhlcvValidation.ok=False).
            let report = json!({
                "ok": false,
                "valid": false,
                "barCount": 0,
                "startTs": null,
                "endTs": null,
                "error": e.message(),
                "errorCode": e.code(),
                "columns": ["timestamp", "open", "high", "low", "close", "volume"],
                "duplicateCount": 0,
                "format": format.as_str(),
                "byteSize": std::fs::metadata(input).map(|m| m.len()).unwrap_or(0),
            });
            std::fs::write(output, serde_json::to_vec_pretty(&report)?)?;
            // Still return Ok with result so Python parity can read the report;
            // receipt status remains ok with valid=false for soft validation failures.
            if e.code() == NATIVE_INPUT_INVALID {
                return Ok(OpOutcome {
                    records_in: 0,
                    records_out: 0,
                    bytes_in: std::fs::metadata(input).map(|m| m.len()).unwrap_or(0),
                    bytes_out: std::fs::metadata(output).map(|m| m.len()).unwrap_or(0),
                    content_hash: None,
                    spill_bytes: 0,
                    result: Some(report),
                });
            }
            return Err(e);
        }
    };

    if scan.bars == 0 {
        let report = json!({
            "ok": false,
            "valid": false,
            "barCount": 0,
            "startTs": null,
            "endTs": null,
            "error": "empty bar series",
            "errorCode": NATIVE_INPUT_INVALID,
            "columns": ["timestamp", "open", "high", "low", "close", "volume"],
            "duplicateCount": 0,
            "format": format.as_str(),
            "byteSize": scan.bytes,
        });
        std::fs::write(output, serde_json::to_vec_pretty(&report)?)?;
        return Ok(OpOutcome {
            records_in: 0,
            records_out: 0,
            bytes_in: scan.bytes,
            bytes_out: std::fs::metadata(output).map(|m| m.len()).unwrap_or(0),
            content_hash: None,
            spill_bytes: 0,
            result: Some(report),
        });
    }

    let report = json!({
        "ok": true,
        "valid": true,
        "barCount": scan.bars,
        "startTs": scan.start_ts,
        "endTs": scan.end_ts,
        "error": null,
        "columns": ["timestamp", "open", "high", "low", "close", "volume"],
        "duplicateCount": scan.duplicate_count,
        "format": format.as_str(),
        "byteSize": scan.bytes,
        "limits": {
            "batchRows": task.limits.batch_rows,
            "maxRecordBytes": task.limits.max_record_bytes,
        },
    });
    std::fs::write(output, serde_json::to_vec_pretty(&report)?)?;

    Ok(OpOutcome {
        records_in: scan.bars,
        records_out: scan.bars,
        bytes_in: scan.bytes,
        bytes_out: std::fs::metadata(output).map(|m| m.len()).unwrap_or(0),
        content_hash: None,
        spill_bytes: 0,
        result: Some(report),
    })
}

#[allow(dead_code)]
fn _ensure_error_type(_: DataPlaneError) {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::metrics::Metrics;
    use crate::protocol::{NativeTask, PROTOCOL_VERSION, TaskInput, TaskLimits, TaskOutput};
    use serde_json::json;
    use std::io::Write;
    use tempfile::tempdir;

    fn tiny_task(op: &str, input: &Path, output: &Path, root: &Path) -> NativeTask {
        NativeTask {
            protocol_version: PROTOCOL_VERSION,
            task_id: "t".into(),
            operation: op.into(),
            input: TaskInput {
                path: input.display().to_string(),
                format: "csv".into(),
                content_hash: None,
            },
            output: TaskOutput {
                temporary_path: output.display().to_string(),
            },
            limits: TaskLimits::default(),
            options: json!({}),
            allowed_roots: vec![root.display().to_string()],
        }
    }

    #[test]
    fn validates_fixture_shape() {
        let dir = tempdir().unwrap();
        let input = dir.path().join("bars.csv");
        let mut f = std::fs::File::create(&input).unwrap();
        writeln!(
            f,
            "timestamp,open,high,low,close,volume\n2024-01-01T00:00:00+00:00,1,2,0.5,1.5,10\n2024-01-01T01:00:00+00:00,1.5,2.5,1,2,11"
        )
        .unwrap();
        let out = dir.path().join("out.json");
        let task = tiny_task("market.ohlcv_validate", &input, &out, dir.path());
        let metrics = Metrics::new("t", "market.ohlcv_validate");
        let outcome = run_ohlcv_validate(&task, &input, &out, metrics).unwrap();
        assert_eq!(outcome.records_in, 2);
        let report = outcome.result.unwrap();
        assert_eq!(report["ok"], true);
        assert_eq!(report["barCount"], 2);
    }
}
