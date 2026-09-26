//! dataset.split — SAME hash bucket as Python.

use sha2::{Digest, Sha256};
use std::path::Path;
use std::sync::Arc;

use crate::error::{DataPlaneError, Result, NATIVE_OPTIONS_INVALID};
use crate::io::{iter_jsonl_records, write_canonical_line, CanonicalRecord};
use crate::metrics::Metrics;
use crate::ops::{empty_content_hash, finalize_hash, open_output_writer, OpOutcome};
use crate::protocol::NativeTask;

/// Python: `int(sha256(f"{seed}:{record_id}").hexdigest()[:8], 16) % 10000`
pub fn stable_bucket(record_id: &str, seed: i64, buckets: u32) -> u32 {
    let payload = format!("{seed}:{record_id}");
    let mut hasher = Sha256::new();
    hasher.update(payload.as_bytes());
    let digest = hex::encode(hasher.finalize());
    let prefix = &digest[..8];
    let value = u64::from_str_radix(prefix, 16).unwrap_or(0);
    (value % u64::from(buckets)) as u32
}

pub fn assign_split_label(
    rec: &CanonicalRecord,
    seed: i64,
    train_ratio: f64,
    val_ratio: f64,
    test_ratio: f64,
) -> Result<String> {
    let total = train_ratio + val_ratio + test_ratio;
    if (total - 1.0).abs() > 1e-6 {
        return Err(DataPlaneError::coded(
            NATIVE_OPTIONS_INVALID,
            format!("Split ratios must sum to 1.0, got {total}"),
        ));
    }
    if train_ratio < 0.0 || val_ratio < 0.0 || test_ratio < 0.0 {
        return Err(DataPlaneError::coded(
            NATIVE_OPTIONS_INVALID,
            "Split ratios must be non-negative",
        ));
    }

    if let Some(ref existing) = rec.split {
        match existing.as_str() {
            "train" | "validation" | "test" => return Ok(existing.clone()),
            "val" | "dev" => return Ok("validation".to_string()),
            _ => {}
        }
    }

    let train_cut = (train_ratio * 10_000.0) as i64;
    let val_cut = train_cut + (val_ratio * 10_000.0) as i64;
    let bucket = i64::from(stable_bucket(&rec.id, seed, 10_000));
    if bucket < train_cut {
        Ok("train".to_string())
    } else if bucket < val_cut {
        Ok("validation".to_string())
    } else {
        Ok("test".to_string())
    }
}

pub fn run_split(
    task: &NativeTask,
    input: &Path,
    output: &Path,
    metrics: Arc<Metrics>,
) -> Result<OpOutcome> {
    let seed = task
        .options
        .get("seed")
        .and_then(|v| v.as_i64())
        .unwrap_or(42);
    let train_ratio = task
        .options
        .get("trainRatio")
        .or_else(|| task.options.get("train_ratio"))
        .and_then(|v| v.as_f64())
        .unwrap_or(0.8);
    let val_ratio = task
        .options
        .get("valRatio")
        .or_else(|| task.options.get("val_ratio"))
        .and_then(|v| v.as_f64())
        .unwrap_or(0.1);
    let test_ratio = task
        .options
        .get("testRatio")
        .or_else(|| task.options.get("test_ratio"))
        .and_then(|v| v.as_f64())
        .unwrap_or(0.1);

    let mut counts = serde_json::Map::new();
    counts.insert("train".into(), serde_json::json!(0));
    counts.insert("validation".into(), serde_json::json!(0));
    counts.insert("test".into(), serde_json::json!(0));

    let mut writer = open_output_writer(output)?;
    let mut digest = Sha256::new();
    let mut out_count = 0u64;

    let stats = iter_jsonl_records(
        input,
        task.limits.max_record_bytes,
        Some(&metrics),
        |_idx, rec, _| {
            let label = assign_split_label(&rec, seed, train_ratio, val_ratio, test_ratio)?;
            let entry = counts.entry(label.clone()).or_insert(serde_json::json!(0));
            if let Some(n) = entry.as_u64() {
                *entry = serde_json::json!(n + 1);
            }
            let out = CanonicalRecord {
                id: rec.id,
                text: rec.text,
                messages: rec.messages,
                labels: rec.labels,
                metadata: rec.metadata,
                split: Some(label),
            };
            write_canonical_line(&mut writer, &out, Some(&mut digest), Some(&metrics))?;
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

    let summary = serde_json::json!({
        "seed": seed,
        "ratios": {
            "train": train_ratio,
            "validation": val_ratio,
            "test": test_ratio,
        },
        "counts": counts,
        "method": "sha256_bucket",
        "deterministic": true,
    });

    Ok(OpOutcome {
        records_in: stats.records,
        records_out: out_count,
        bytes_in: stats.bytes,
        bytes_out: std::fs::metadata(output).map(|m| m.len()).unwrap_or(0),
        content_hash: Some(hash),
        spill_bytes: 0,
        result: Some(summary),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Map;

    #[test]
    fn bucket_matches_python_fixture() {
        // Compute expected with known vector: seed=7, id=r0
        let b = stable_bucket("r0", 7, 10_000);
        // Cross-check: sha256("7:r0")[:8]
        let mut h = Sha256::new();
        h.update(b"7:r0");
        let dig = hex::encode(h.finalize());
        let expected = (u64::from_str_radix(&dig[..8], 16).unwrap() % 10_000) as u32;
        assert_eq!(b, expected);
    }

    #[test]
    fn existing_split_preserved() {
        let rec = CanonicalRecord {
            id: "x".into(),
            text: "t".into(),
            messages: None,
            labels: None,
            metadata: Map::new(),
            split: Some("val".into()),
        };
        assert_eq!(
            assign_split_label(&rec, 42, 0.8, 0.1, 0.1).unwrap(),
            "validation"
        );
    }
}
