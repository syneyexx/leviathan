//! dataset.transform — record-local transforms matching Python.

use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::path::Path;
use std::sync::Arc;

use crate::error::{DataPlaneError, Result, NATIVE_OPTIONS_INVALID};
use crate::io::{iter_jsonl_records, write_canonical_line, CanonicalRecord};
use crate::metrics::Metrics;
use crate::ops::{empty_content_hash, finalize_hash, open_output_writer, OpOutcome};
use crate::protocol::NativeTask;

pub fn run_transform(
    task: &NativeTask,
    input: &Path,
    output: &Path,
    metrics: Arc<Metrics>,
) -> Result<OpOutcome> {
    let transforms = task
        .options
        .get("transforms")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();

    let compiled = compile_pipeline(&transforms)?;
    let mut counters: Vec<(u64, u64, u64)> = compiled.iter().map(|_| (0, 0, 0)).collect();

    let mut writer = open_output_writer(output)?;
    let mut digest = Sha256::new();
    let mut out_count = 0u64;

    let stats = iter_jsonl_records(
        input,
        task.limits.max_record_bytes,
        Some(&metrics),
        |_idx, rec, _| {
            let mut current: Option<CanonicalRecord> = Some(rec);
            for (i, (name, params)) in compiled.iter().enumerate() {
                counters[i].0 += 1;
                match current.take() {
                    None => {
                        counters[i].2 += 1;
                        break;
                    }
                    Some(r) => match apply_transform(name, &r, params)? {
                        None => {
                            counters[i].2 += 1;
                            current = None;
                            break;
                        }
                        Some(next) => {
                            counters[i].1 += 1;
                            current = Some(next);
                        }
                    },
                }
            }
            if let Some(out) = current {
                write_canonical_line(&mut writer, &out, Some(&mut digest), Some(&metrics))?;
                out_count += 1;
            }
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

    let lineage: Vec<Value> = compiled
        .iter()
        .zip(counters.iter())
        .map(|((name, params), (inp, outp, drop))| {
            serde_json::json!({
                "name": name,
                "params": params,
                "inputCount": inp,
                "outputCount": outp,
                "dropCount": drop,
            })
        })
        .collect();

    Ok(OpOutcome {
        records_in: stats.records,
        records_out: out_count,
        bytes_in: stats.bytes,
        bytes_out: std::fs::metadata(output).map(|m| m.len()).unwrap_or(0),
        content_hash: Some(hash),
        spill_bytes: 0,
        result: Some(serde_json::json!({ "transformLineage": lineage })),
    })
}

fn compile_pipeline(transforms: &[Value]) -> Result<Vec<(String, Map<String, Value>)>> {
    let mut out = Vec::new();
    for spec in transforms {
        let name = spec
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        if name.is_empty() {
            return Err(DataPlaneError::coded(
                NATIVE_OPTIONS_INVALID,
                "Transform missing name",
            ));
        }
        if !matches!(
            name.as_str(),
            "strip_whitespace" | "lowercase" | "filter_min_chars" | "add_prefix" | "set_metadata"
        ) {
            return Err(DataPlaneError::coded(
                NATIVE_OPTIONS_INVALID,
                format!("Unknown transform: {name}"),
            ));
        }
        let params = spec
            .get("params")
            .and_then(|v| v.as_object())
            .cloned()
            .unwrap_or_default();
        out.push((name, params));
    }
    Ok(out)
}

fn apply_transform(
    name: &str,
    rec: &CanonicalRecord,
    params: &Map<String, Value>,
) -> Result<Option<CanonicalRecord>> {
    match name {
        "strip_whitespace" => Ok(strip_whitespace(rec, params)),
        "lowercase" => Ok(Some(lowercase(rec))),
        "filter_min_chars" => Ok(filter_min_chars(rec, params)),
        "add_prefix" => Ok(Some(add_prefix(rec, params))),
        "set_metadata" => set_metadata(rec, params).map(Some),
        _ => Err(DataPlaneError::coded(
            NATIVE_OPTIONS_INVALID,
            format!("Unknown transform: {name}"),
        )),
    }
}

fn strip_whitespace(rec: &CanonicalRecord, params: &Map<String, Value>) -> Option<CanonicalRecord> {
    let do_strip = params
        .get("strip")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let mut text = if do_strip {
        rec.text.trim().to_string()
    } else {
        rec.text.clone()
    };
    if params
        .get("collapse_whitespace")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
    {
        text = collapse_whitespace(&text);
    }
    let drop_empty = params
        .get("drop_empty")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let has_messages = rec
        .messages
        .as_ref()
        .map(|m| !m.is_empty())
        .unwrap_or(false);
    if drop_empty && text.trim().is_empty() && !has_messages {
        return None;
    }
    Some(CanonicalRecord {
        id: rec.id.clone(),
        text,
        messages: rec.messages.clone(),
        labels: rec.labels.clone(),
        metadata: rec.metadata.clone(),
        split: rec.split.clone(),
    })
}

fn collapse_whitespace(text: &str) -> String {
    // Match Python: re.sub(r"[ \t]+", " ", text) then re.sub(r"\n{3,}", "\n\n", text)
    let mut out = String::with_capacity(text.len());
    let mut chars = text.chars().peekable();
    while let Some(c) = chars.next() {
        if c == ' ' || c == '\t' {
            out.push(' ');
            while matches!(chars.peek(), Some(' ' | '\t')) {
                chars.next();
            }
        } else {
            out.push(c);
        }
    }
    let mut final_out = String::with_capacity(out.len());
    let mut iter = out.chars().peekable();
    while let Some(c) = iter.next() {
        if c == '\n' {
            let mut n = 1;
            while iter.peek() == Some(&'\n') {
                iter.next();
                n += 1;
            }
            let keep = n.min(2);
            for _ in 0..keep {
                final_out.push('\n');
            }
        } else {
            final_out.push(c);
        }
    }
    final_out
}

fn lowercase(rec: &CanonicalRecord) -> CanonicalRecord {
    let mut metadata = rec.metadata.clone();
    metadata.insert("lowercased".to_string(), Value::Bool(true));
    CanonicalRecord {
        id: rec.id.clone(),
        text: rec.text.to_lowercase(),
        messages: rec.messages.clone(),
        labels: rec.labels.clone(),
        metadata,
        split: rec.split.clone(),
    }
}

fn filter_min_chars(rec: &CanonicalRecord, params: &Map<String, Value>) -> Option<CanonicalRecord> {
    let minimum = params
        .get("min_chars")
        .and_then(|v| v.as_u64())
        .unwrap_or(1) as usize;
    let has_messages = rec
        .messages
        .as_ref()
        .map(|m| !m.is_empty())
        .unwrap_or(false);
    // Python `len(str)` counts Unicode codepoints.
    if rec.text.chars().count() < minimum && !has_messages {
        None
    } else {
        Some(rec.clone())
    }
}

fn add_prefix(rec: &CanonicalRecord, params: &Map<String, Value>) -> CanonicalRecord {
    let prefix = params
        .get("prefix")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    CanonicalRecord {
        id: rec.id.clone(),
        text: format!("{}{}", prefix, rec.text),
        messages: rec.messages.clone(),
        labels: rec.labels.clone(),
        metadata: rec.metadata.clone(),
        split: rec.split.clone(),
    }
}

fn set_metadata(rec: &CanonicalRecord, params: &Map<String, Value>) -> Result<CanonicalRecord> {
    let extra = params
        .get("metadata")
        .cloned()
        .unwrap_or(Value::Object(Map::new()));
    let extra_map = match extra {
        Value::Object(m) => m,
        _ => {
            return Err(DataPlaneError::coded(
                NATIVE_OPTIONS_INVALID,
                "set_metadata.metadata must be an object",
            ));
        }
    };
    let mut metadata = rec.metadata.clone();
    for (k, v) in extra_map {
        metadata.insert(k, v);
    }
    Ok(CanonicalRecord {
        id: rec.id.clone(),
        text: rec.text.clone(),
        messages: rec.messages.clone(),
        labels: rec.labels.clone(),
        metadata,
        split: rec.split.clone(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strip_and_filter() {
        let rec = CanonicalRecord {
            id: "1".into(),
            text: "  Hi  ".into(),
            messages: None,
            labels: None,
            metadata: Map::new(),
            split: None,
        };
        let mut params = Map::new();
        params.insert("strip".into(), Value::Bool(true));
        let out = strip_whitespace(&rec, &params).unwrap();
        assert_eq!(out.text, "Hi");

        let mut min = Map::new();
        min.insert("min_chars".into(), Value::from(10));
        assert!(filter_min_chars(&out, &min).is_none());
    }
}
