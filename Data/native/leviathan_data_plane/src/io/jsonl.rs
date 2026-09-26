//! Streaming JSONL reader/writer with bounded line size and canonical hashing.

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::fs::File;
use std::io::{BufWriter, Read, Write};
use std::path::Path;

use crate::error::{DataPlaneError, Result, NATIVE_INPUT_INVALID, NATIVE_RECORD_TOO_LARGE};
use crate::metrics::Metrics;

/// Matches Python `CanonicalRecord.to_dict()` field set.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CanonicalRecord {
    pub id: String,
    #[serde(default)]
    pub text: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub messages: Option<Vec<Value>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub labels: Option<Map<String, Value>>,
    #[serde(default)]
    pub metadata: Map<String, Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub split: Option<String>,
}

impl CanonicalRecord {
    pub fn from_value(v: Value) -> Result<Self> {
        serde_json::from_value(v).map_err(|e| {
            DataPlaneError::coded(
                NATIVE_INPUT_INVALID,
                format!("invalid canonical record: {e}"),
            )
        })
    }

    /// Serialize like Python `json.dumps(rec.to_dict(), ensure_ascii=False, sort_keys=True)`.
    pub fn to_canonical_value(&self) -> Value {
        let mut map = Map::new();
        map.insert("id".to_string(), Value::String(self.id.clone()));
        map.insert("text".to_string(), Value::String(self.text.clone()));
        map.insert("metadata".to_string(), Value::Object(self.metadata.clone()));
        if let Some(ref messages) = self.messages {
            map.insert("messages".to_string(), Value::Array(messages.clone()));
        }
        if let Some(ref labels) = self.labels {
            map.insert("labels".to_string(), Value::Object(labels.clone()));
        }
        if let Some(ref split) = self.split {
            map.insert("split".to_string(), Value::String(split.clone()));
        }
        sort_value_keys(Value::Object(map))
    }
}

/// Recursively sort object keys for stable hashing (Python sort_keys=True).
pub fn sort_value_keys(value: Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut keys: Vec<String> = map.keys().cloned().collect();
            keys.sort();
            let mut out = Map::new();
            for k in keys {
                if let Some(v) = map.get(&k) {
                    out.insert(k, sort_value_keys(v.clone()));
                }
            }
            Value::Object(out)
        }
        Value::Array(arr) => Value::Array(arr.into_iter().map(sort_value_keys).collect()),
        other => other,
    }
}

pub fn canonical_json_line(rec: &CanonicalRecord) -> Result<String> {
    let value = rec.to_canonical_value();
    // serde_json preserves Map insertion order; we already sorted keys.
    let s = serde_json::to_string(&value)?;
    Ok(format!("{s}\n"))
}

pub fn content_hash_update(digest: &mut Sha256, rec: &CanonicalRecord) -> Result<usize> {
    let line = canonical_json_line(rec)?;
    let raw = line.as_bytes();
    digest.update(raw);
    Ok(raw.len())
}

/// Exact dedupe fingerprint — matches Python `record_fingerprint` (id excluded).
pub fn fingerprint_payload(rec: &CanonicalRecord) -> Result<String> {
    let mut map = Map::new();
    map.insert("text".to_string(), Value::String(rec.text.clone()));
    map.insert(
        "messages".to_string(),
        match &rec.messages {
            Some(m) => Value::Array(m.clone()),
            None => Value::Null,
        },
    );
    map.insert(
        "labels".to_string(),
        match &rec.labels {
            Some(l) => Value::Object(l.clone()),
            None => Value::Null,
        },
    );
    let sorted = sort_value_keys(Value::Object(map));
    let payload = serde_json::to_string(&sorted)?;
    let mut hasher = Sha256::new();
    hasher.update(payload.as_bytes());
    Ok(hex::encode(hasher.finalize()))
}

#[derive(Debug, Default)]
pub struct JsonlReaderStats {
    pub records: u64,
    pub bytes: u64,
    pub empty_lines: u64,
}

/// Callback-driven streaming reader — never collects the full corpus.
pub fn iter_jsonl_records<F>(
    path: &Path,
    max_record_bytes: u64,
    metrics: Option<&Metrics>,
    mut on_record: F,
) -> Result<JsonlReaderStats>
where
    F: FnMut(u64, CanonicalRecord, usize) -> Result<()>,
{
    let mut file = File::open(path)?;
    let mut stats = JsonlReaderStats::default();
    let mut line_index: u64 = 0;
    let limit = max_record_bytes.max(1) as usize;

    loop {
        line_index += 1;
        let (raw, eof) = read_bounded_line(&mut file, limit, line_index)?;
        if raw.is_empty() && eof {
            break;
        }
        if eof && raw.is_empty() {
            break;
        }
        let byte_len = raw.len();
        // Strip CR
        let text = if raw.ends_with(b"\r") {
            String::from_utf8_lossy(&raw[..raw.len().saturating_sub(1)]).into_owned()
        } else {
            String::from_utf8_lossy(&raw).into_owned()
        };
        let trimmed = text.trim();
        if trimmed.is_empty() {
            stats.empty_lines += 1;
            if eof {
                break;
            }
            continue;
        }
        let value: Value = serde_json::from_str(trimmed).map_err(|e| {
            DataPlaneError::coded(
                NATIVE_INPUT_INVALID,
                format!("invalid JSON at line {line_index}: {e}"),
            )
        })?;
        let rec = CanonicalRecord::from_value(value)?;
        stats.records += 1;
        stats.bytes += byte_len as u64;
        if let Some(m) = metrics {
            m.bump_in(1, byte_len as u64);
        }
        on_record(line_index, rec, byte_len)?;
        if eof {
            break;
        }
    }
    Ok(stats)
}

fn read_bounded_line(file: &mut File, limit: usize, line_index: u64) -> Result<(Vec<u8>, bool)> {
    let mut buf = Vec::with_capacity(256);
    let mut exceeded = false;
    let mut byte = [0u8; 1];
    loop {
        let n = file.read(&mut byte)?;
        if n == 0 {
            return Ok((buf, true));
        }
        if byte[0] == b'\n' {
            if exceeded {
                return Err(DataPlaneError::coded(
                    NATIVE_RECORD_TOO_LARGE,
                    format!("Record exceeds max_record_bytes={limit} at line {line_index}"),
                ));
            }
            return Ok((buf, false));
        }
        if !exceeded {
            if buf.len() >= limit {
                exceeded = true;
                buf.clear();
            } else {
                buf.push(byte[0]);
            }
        }
    }
}

pub fn write_canonical_line(
    writer: &mut BufWriter<File>,
    rec: &CanonicalRecord,
    digest: Option<&mut Sha256>,
    metrics: Option<&Metrics>,
) -> Result<usize> {
    let line = canonical_json_line(rec)?;
    let raw = line.as_bytes();
    writer.write_all(raw)?;
    if let Some(d) = digest {
        d.update(raw);
    }
    if let Some(m) = metrics {
        m.bump_out(1, raw.len() as u64);
    }
    Ok(raw.len())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn canonical_hash_stable() {
        let rec = CanonicalRecord {
            id: "r1".into(),
            text: "hello".into(),
            messages: None,
            labels: None,
            metadata: Map::new(),
            split: None,
        };
        let a = canonical_json_line(&rec).unwrap();
        let b = canonical_json_line(&rec).unwrap();
        assert_eq!(a, b);
        assert!(a.contains("\"id\":\"r1\""));
        // sort_keys → id, metadata, text
        assert!(a.starts_with("{\"id\":"));
    }

    #[test]
    fn bounded_line_rejects_huge() {
        let mut tmp = NamedTempFile::new().unwrap();
        let huge = "x".repeat(100);
        writeln!(tmp, "{huge}").unwrap();
        let path = tmp.path().to_path_buf();
        let err = iter_jsonl_records(&path, 50, None, |_, _, _| Ok(())).unwrap_err();
        assert_eq!(err.code(), NATIVE_RECORD_TOO_LARGE);
    }

    #[test]
    fn fingerprint_excludes_id() {
        let a = CanonicalRecord {
            id: "1".into(),
            text: "same".into(),
            messages: None,
            labels: None,
            metadata: Map::new(),
            split: None,
        };
        let b = CanonicalRecord {
            id: "2".into(),
            text: "same".into(),
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
}
