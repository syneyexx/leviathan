//! dataset.validate — counters + issue sample, streaming.

use serde_json::{json, Value};
use std::path::Path;
use std::sync::Arc;

use crate::error::Result;
use crate::io::{iter_jsonl_records, CanonicalRecord};
use crate::metrics::Metrics;
use crate::ops::OpOutcome;
use crate::protocol::NativeTask;

pub fn run_validate(
    task: &NativeTask,
    input: &Path,
    output: &Path,
    metrics: Arc<Metrics>,
) -> Result<OpOutcome> {
    let max_issues = task
        .options
        .get("maxIssues")
        .or_else(|| task.options.get("max_issues"))
        .and_then(|v| v.as_u64())
        .unwrap_or(200) as usize;

    let mut issues: Vec<Value> = Vec::new();
    let mut error_count: u64 = 0;
    let mut warning_count: u64 = 0;
    let mut empty_content: u64 = 0;
    let mut records_out = 0u64;

    let stats = iter_jsonl_records(
        input,
        task.limits.max_record_bytes,
        Some(&metrics),
        |line_index, rec, _| {
            let idx = (line_index.saturating_sub(1)) as usize;
            let found = validate_record(&rec, idx);
            for issue in found {
                let is_warning = issue
                    .get("severity")
                    .and_then(|v| v.as_str())
                    .unwrap_or("error")
                    == "warning";
                if issue.get("code").and_then(|v| v.as_str()) == Some("empty_content") {
                    empty_content += 1;
                }
                if is_warning {
                    warning_count += 1;
                } else {
                    error_count += 1;
                }
                if issues.len() < max_issues {
                    issues.push(issue);
                }
            }
            records_out += 1;
            Ok(())
        },
    )?;

    let truncated = (error_count + warning_count) > issues.len() as u64;
    let report = json!({
        "valid": error_count == 0,
        "rowCount": stats.records,
        "errorCount": error_count,
        "warningCount": warning_count,
        "emptyContentCount": empty_content,
        "issues": issues,
        "issuesTruncated": truncated,
        "truncated": truncated,
    });

    std::fs::write(output, serde_json::to_vec_pretty(&report)?)?;

    Ok(OpOutcome {
        records_in: stats.records,
        records_out: stats.records,
        bytes_in: stats.bytes,
        bytes_out: std::fs::metadata(output).map(|m| m.len()).unwrap_or(0),
        content_hash: None,
        spill_bytes: 0,
        result: Some(report),
    })
}

fn validate_record(record: &CanonicalRecord, index: usize) -> Vec<Value> {
    let mut issues = Vec::new();
    if record.id.trim().is_empty() {
        issues.push(json!({
            "index": index,
            "field": "id",
            "code": "missing_id",
            "message": "id is required",
        }));
    }
    let has_text = !record.text.trim().is_empty();
    let has_messages = record
        .messages
        .as_ref()
        .map(|m| !m.is_empty())
        .unwrap_or(false);
    if !has_text && !has_messages {
        issues.push(json!({
            "index": index,
            "field": "text",
            "code": "empty_content",
            "message": "record needs text or messages",
        }));
    }
    if let Some(ref messages) = record.messages {
        for (mi, msg) in messages.iter().enumerate() {
            if !msg.is_object() {
                issues.push(json!({
                    "index": index,
                    "field": format!("messages[{mi}]"),
                    "code": "invalid_message",
                    "message": "each message must be an object",
                }));
                continue;
            }
            let obj = msg.as_object().unwrap();
            if !obj.contains_key("content") && !obj.contains_key("text") {
                issues.push(json!({
                    "index": index,
                    "field": format!("messages[{mi}]"),
                    "code": "message_missing_content",
                    "message": "message needs content or text",
                }));
            }
        }
    }
    if let Some(ref split) = record.split {
        match split.as_str() {
            "train" | "validation" | "val" | "test" | "dev" => {}
            other => {
                issues.push(json!({
                    "index": index,
                    "field": "split",
                    "code": "unknown_split",
                    "message": format!("unexpected split label: {other}"),
                    "severity": "warning",
                }));
            }
        }
    }
    issues
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Map;

    #[test]
    fn missing_id_detected() {
        let rec = CanonicalRecord {
            id: "".into(),
            text: "".into(),
            messages: None,
            labels: None,
            metadata: Map::new(),
            split: None,
        };
        let issues = validate_record(&rec, 0);
        assert!(issues.iter().any(|i| i["code"] == "missing_id"));
        assert!(issues.iter().any(|i| i["code"] == "empty_content"));
    }
}
