//! dataset.dedupe — external-memory exact dedupe via spill partition files.

use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::Path;
use std::sync::Arc;

use crate::error::{
    DataPlaneError, Result, NATIVE_MEMORY_BUDGET_EXCEEDED, NATIVE_SPILL_BUDGET_EXCEEDED,
};
use crate::io::{fingerprint_payload, iter_jsonl_records, write_canonical_line, CanonicalRecord};
use crate::metrics::Metrics;
use crate::ops::{empty_content_hash, finalize_hash, open_output_writer, spill_dir_for, OpOutcome};
use crate::protocol::NativeTask;

/// Two-phase external exact dedupe:
/// 1) Stream input → partition files keyed by fingerprint prefix (spill).
/// 2) Per-partition: keep first seq per fingerprint; emit winners sorted by seq.
///
/// Honors memoryBytes (in-memory map size soft limit) and spillBytes budget.
pub fn run_dedupe(
    task: &NativeTask,
    input: &Path,
    output: &Path,
    metrics: Arc<Metrics>,
) -> Result<OpOutcome> {
    let spill_root = spill_dir_for(task, output)?;
    let memory_budget = task.limits.memory_bytes.max(64 * 1024);
    let spill_budget = task.limits.spill_bytes.max(1024 * 1024);

    // Phase 1: partition by fp[:2]
    let mut seq: u64 = 0;
    let mut partition_handles: HashMap<String, BufWriter<File>> = HashMap::new();
    let mut spill_bytes: u64 = 0;
    // Soft in-memory estimate: open writers + small map of keys.
    let approx_writer_overhead = 64 * 1024u64;

    let stats = iter_jsonl_records(
        input,
        task.limits.max_record_bytes,
        Some(&metrics),
        |_idx, rec, _| {
            let fp = fingerprint_payload(&rec)?;
            let key = fp.chars().take(2).collect::<String>();
            let line = format!(
                "{seq}\t{fp}\t{}",
                serde_json::to_string(&rec.to_canonical_value())?
            );
            let part_path = spill_root.join(format!("part-{key}.tsv"));
            if !partition_handles.contains_key(&key) {
                // Memory soft check for number of open partitions
                let estimate = (partition_handles.len() as u64 + 1) * approx_writer_overhead;
                if estimate > memory_budget {
                    // Flush all writers to reduce resident buffers, then continue with fewer open.
                    flush_all(&mut partition_handles)?;
                    if (partition_handles.len() as u64 + 1) * approx_writer_overhead > memory_budget
                        && partition_handles.len() > 8
                    {
                        // Close half the writers to free memory.
                        close_half(&mut partition_handles)?;
                    }
                    if approx_writer_overhead > memory_budget {
                        return Err(DataPlaneError::coded(
                            NATIVE_MEMORY_BUDGET_EXCEEDED,
                            format!("memory budget {memory_budget} too small for spill writers"),
                        ));
                    }
                }
                let file = OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(&part_path)?;
                partition_handles.insert(key.clone(), BufWriter::new(file));
            }
            let writer = partition_handles.get_mut(&key).unwrap();
            writeln!(writer, "{line}")?;
            spill_bytes = spill_bytes.saturating_add(line.len() as u64 + 1);
            if spill_bytes > spill_budget {
                return Err(DataPlaneError::coded(
                    NATIVE_SPILL_BUDGET_EXCEEDED,
                    format!("spill budget {spill_budget} exceeded ({spill_bytes} bytes)"),
                ));
            }
            seq += 1;
            Ok(())
        },
    )?;
    flush_all(&mut partition_handles)?;
    partition_handles.clear();
    metrics.set_spill(dir_size(&spill_root)?);

    // Phase 2: for each partition, keep min seq per fp
    let mut winners: Vec<(u64, CanonicalRecord)> = Vec::new();
    let mut duplicate_ids: Vec<String> = Vec::new();

    for entry in fs::read_dir(&spill_root)? {
        let entry = entry?;
        let path = entry.path();
        if !path
            .file_name()
            .and_then(|n| n.to_str())
            .map(|n| n.starts_with("part-") && n.ends_with(".tsv"))
            .unwrap_or(false)
        {
            continue;
        }
        let (part_winners, part_dups) = reduce_partition(&path, memory_budget)?;
        for (s, rec) in part_winners {
            winners.push((s, rec));
        }
        for id in part_dups {
            if duplicate_ids.len() < 100 {
                duplicate_ids.push(id);
            }
        }
    }

    // Sort winners by original sequence to preserve first-occurrence order.
    winners.sort_by_key(|(s, _)| *s);

    let mut writer = open_output_writer(output)?;
    let mut digest = Sha256::new();
    let mut out_count = 0u64;
    for (_, rec) in winners {
        write_canonical_line(&mut writer, &rec, Some(&mut digest), Some(&metrics))?;
        out_count += 1;
    }
    writer.get_mut().sync_all().ok();
    drop(writer);

    let spill_final = dir_size(&spill_root).unwrap_or(spill_bytes);
    metrics.set_spill(spill_final);
    // Cleanup spill (best-effort)
    let _ = fs::remove_dir_all(&spill_root);

    let hash = if out_count == 0 {
        empty_content_hash()
    } else {
        finalize_hash(digest, false)
    };

    let removed_count = stats.records.saturating_sub(out_count);
    let result = serde_json::json!({
        "inputCount": stats.records,
        "outputCount": out_count,
        "removedCount": removed_count,
        "duplicateIds": duplicate_ids,
        "duplicateIdsTruncated": removed_count > duplicate_ids.len() as u64,
        "method": "exact_sha256",
        "memoryMode": "external_partition_spill",
        "spillBytes": spill_final,
    });

    Ok(OpOutcome {
        records_in: stats.records,
        records_out: out_count,
        bytes_in: stats.bytes,
        bytes_out: std::fs::metadata(output).map(|m| m.len()).unwrap_or(0),
        content_hash: Some(hash),
        spill_bytes: spill_final,
        result: Some(result),
    })
}

fn flush_all(handles: &mut HashMap<String, BufWriter<File>>) -> Result<()> {
    for w in handles.values_mut() {
        w.flush()?;
    }
    Ok(())
}

fn close_half(handles: &mut HashMap<String, BufWriter<File>>) -> Result<()> {
    let keys: Vec<String> = handles.keys().cloned().collect();
    let half = keys.len() / 2;
    for key in keys.into_iter().take(half) {
        if let Some(mut w) = handles.remove(&key) {
            w.flush()?;
        }
    }
    Ok(())
}

type PartitionWinners = Vec<(u64, CanonicalRecord)>;

/// Returns (winners as seq+record, duplicate victim ids).
fn reduce_partition(path: &Path, memory_budget: u64) -> Result<(PartitionWinners, Vec<String>)> {
    let mut best: HashMap<String, (u64, CanonicalRecord)> = HashMap::new();
    let mut dup_ids: Vec<String> = Vec::new();
    let file = File::open(path)?;
    let reader = BufReader::new(file);
    for line in reader.lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let mut parts = line.splitn(3, '\t');
        let seq: u64 = parts.next().and_then(|s| s.parse().ok()).ok_or_else(|| {
            DataPlaneError::coded(
                crate::error::NATIVE_INTERNAL,
                "corrupt spill partition line",
            )
        })?;
        let fp = parts.next().unwrap_or("").to_string();
        let json = parts.next().unwrap_or("");
        let rec: CanonicalRecord = serde_json::from_str(json)?;
        match best.get(&fp) {
            Some((existing_seq, _)) if *existing_seq <= seq => {
                dup_ids.push(rec.id);
            }
            Some(_) => {
                let prev = best.insert(fp, (seq, rec)).unwrap();
                dup_ids.push(prev.1.id);
            }
            None => {
                best.insert(fp, (seq, rec));
            }
        }
        let estimate = best.len() as u64 * 512;
        if estimate > memory_budget {
            return Err(DataPlaneError::coded(
                NATIVE_MEMORY_BUDGET_EXCEEDED,
                format!(
                    "partition {:?} exceeds memory budget while reducing ({estimate} est.)",
                    path.file_name()
                ),
            ));
        }
    }
    let winners: Vec<(u64, CanonicalRecord)> = best.into_values().collect();
    Ok((winners, dup_ids))
}

fn dir_size(path: &Path) -> Result<u64> {
    let mut total = 0u64;
    if !path.exists() {
        return Ok(0);
    }
    for entry in fs::read_dir(path)? {
        let entry = entry?;
        let meta = entry.metadata()?;
        if meta.is_file() {
            total = total.saturating_add(meta.len());
        } else if meta.is_dir() {
            total = total.saturating_add(dir_size(&entry.path())?);
        }
    }
    Ok(total)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::io::fingerprint_payload;
    use serde_json::Map;
    use tempfile::tempdir;

    #[test]
    fn fingerprints_match_for_dup_payload() {
        let a = CanonicalRecord {
            id: "1".into(),
            text: "alpha".into(),
            messages: None,
            labels: None,
            metadata: Map::new(),
            split: None,
        };
        let b = CanonicalRecord {
            id: "3".into(),
            text: "alpha".into(),
            messages: None,
            labels: None,
            metadata: Map::new(),
            split: None,
        };
        assert_eq!(
            fingerprint_payload(&a).unwrap(),
            fingerprint_payload(&b).unwrap()
        );
    }

    #[test]
    fn reduce_keeps_first_seq() {
        let dir = tempdir().unwrap();
        let part = dir.path().join("part-ab.tsv");
        let mut f = File::create(&part).unwrap();
        let r0 = CanonicalRecord {
            id: "a".into(),
            text: "x".into(),
            messages: None,
            labels: None,
            metadata: Map::new(),
            split: None,
        };
        let r1 = CanonicalRecord {
            id: "b".into(),
            text: "x".into(),
            messages: None,
            labels: None,
            metadata: Map::new(),
            split: None,
        };
        let fp = fingerprint_payload(&r0).unwrap();
        writeln!(
            f,
            "0\t{fp}\t{}",
            serde_json::to_string(&r0.to_canonical_value()).unwrap()
        )
        .unwrap();
        writeln!(
            f,
            "1\t{fp}\t{}",
            serde_json::to_string(&r1.to_canonical_value()).unwrap()
        )
        .unwrap();
        let (winners, dups) = reduce_partition(&part, 64 * 1024 * 1024).unwrap();
        assert_eq!(winners.len(), 1);
        assert_eq!(winners[0].1.id, "a");
        assert_eq!(dups, vec!["b".to_string()]);
    }
}
