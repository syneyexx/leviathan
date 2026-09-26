//! Bounded Parquet → canonical record reading (Arrow record batches).
//!
//! Supports schemas with id/text-like columns or market OHLCV columns.
//! Never materializes the full table — iterates Arrow batches with a row budget.

use arrow_array::{
    Array, BooleanArray, Float32Array, Float64Array, Int16Array, Int32Array, Int64Array,
    Int8Array, LargeStringArray, RecordBatch, StringArray, UInt16Array, UInt32Array, UInt64Array,
    UInt8Array,
};
use arrow_schema::{DataType, Schema};
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
use serde_json::{Map, Number, Value};
use sha2::{Digest, Sha256};
use std::fs::File;
use std::path::Path;
use std::sync::Arc;

use crate::error::{DataPlaneError, Result, NATIVE_INPUT_INVALID, NATIVE_RECORD_TOO_LARGE};
use crate::io::jsonl::CanonicalRecord;
use crate::metrics::Metrics;

const ID_KEYS: &[&str] = &["id", "uid", "uuid", "example_id", "row_id"];
const TEXT_KEYS: &[&str] = &[
    "text",
    "content",
    "body",
    "prompt",
    "input",
    "question",
    "document",
    "passage",
    "review",
    "comment",
    "sentence",
    "utterance",
    "response",
    "completion",
    "instruction",
    "article",
];
const LABEL_KEYS: &[&str] = &["label", "labels", "target", "output", "answer", "category"];
const MESSAGES_KEYS: &[&str] = &["messages", "conversations", "dialogue"];
const MARKET_TS_KEYS: &[&str] = &["timestamp", "ts", "time", "datetime", "date"];
const MARKET_OHLCV: &[&str] = &["open", "high", "low", "close", "volume"];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ParquetRowKind {
    Text,
    Market,
    Unknown,
}

#[derive(Debug, Clone)]
pub struct ParquetSchemaReport {
    pub fields: Vec<ParquetFieldInfo>,
    pub row_kind: ParquetRowKind,
    pub num_row_groups: usize,
    pub metadata_num_rows: Option<i64>,
}

#[derive(Debug, Clone)]
pub struct ParquetFieldInfo {
    pub name: String,
    pub data_type: String,
    pub nullable: bool,
}

#[derive(Debug, Default)]
pub struct ParquetReaderStats {
    pub records: u64,
    pub bytes: u64,
    pub batches: u64,
    pub skipped_empty: u64,
}

/// Classify Arrow schema as text-like, market OHLCV, or unknown.
pub fn classify_schema(schema: &Schema) -> ParquetRowKind {
    let names: Vec<String> = schema.fields().iter().map(|f| f.name().to_lowercase()).collect();
    let has_text = names.iter().any(|n| TEXT_KEYS.iter().any(|k| k == n));
    let has_id = names.iter().any(|n| ID_KEYS.iter().any(|k| k == n));
    if has_text || has_id {
        return ParquetRowKind::Text;
    }
    let has_ts = names.iter().any(|n| MARKET_TS_KEYS.iter().any(|k| k == n));
    let ohlcv_hits = MARKET_OHLCV
        .iter()
        .filter(|k| names.iter().any(|n| n == *k))
        .count();
    if has_ts && ohlcv_hits >= 4 {
        return ParquetRowKind::Market;
    }
    ParquetRowKind::Unknown
}

pub fn schema_report(schema: &Schema, num_row_groups: usize, metadata_num_rows: Option<i64>) -> ParquetSchemaReport {
    let fields = schema
        .fields()
        .iter()
        .map(|f| ParquetFieldInfo {
            name: f.name().clone(),
            data_type: format!("{:?}", f.data_type()),
            nullable: f.is_nullable(),
        })
        .collect();
    ParquetSchemaReport {
        fields,
        row_kind: classify_schema(schema),
        num_row_groups,
        metadata_num_rows,
    }
}

fn pick_ci<'a>(map: &'a Map<String, Value>, keys: &[&str]) -> Option<&'a Value> {
    for key in keys {
        if let Some(v) = map.get(*key) {
            if !v.is_null() {
                return Some(v);
            }
        }
        let lower = key.to_lowercase();
        for (k, v) in map {
            if k.to_lowercase() == lower && !v.is_null() {
                return Some(v);
            }
        }
    }
    None
}

fn stable_id(seed: &str) -> String {
    let mut h = Sha256::new();
    h.update(seed.as_bytes());
    let hex = hex::encode(h.finalize());
    hex[..16.min(hex.len())].to_string()
}

fn value_as_string(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Null => String::new(),
        other => other.to_string(),
    }
}

/// Convert a row dict into a canonical record (text or market).
pub fn row_to_canonical(
    data: &Map<String, Value>,
    index: u64,
    source: &str,
    row_kind: ParquetRowKind,
) -> CanonicalRecord {
    match row_kind {
        ParquetRowKind::Market => market_row_to_canonical(data, index, source),
        ParquetRowKind::Text | ParquetRowKind::Unknown => text_row_to_canonical(data, index, source),
    }
}

fn text_row_to_canonical(data: &Map<String, Value>, index: u64, source: &str) -> CanonicalRecord {
    let raw_id = pick_ci(data, ID_KEYS).map(value_as_string);
    let text_val = pick_ci(data, TEXT_KEYS);
    let messages = pick_ci(data, MESSAGES_KEYS).and_then(|v| v.as_array().cloned());
    let labels_raw = pick_ci(data, LABEL_KEYS);

    let mut text = match text_val {
        Some(Value::String(s)) => s.clone(),
        Some(other) if messages.is_none() => value_as_string(other),
        _ => String::new(),
    };

    if text.is_empty() {
        if let Some(ref msgs) = messages {
            let mut parts = Vec::new();
            for msg in msgs {
                if let Some(obj) = msg.as_object() {
                    let role = obj
                        .get("role")
                        .and_then(|v| v.as_str())
                        .unwrap_or("");
                    let content = obj
                        .get("content")
                        .or_else(|| obj.get("text"))
                        .map(value_as_string)
                        .unwrap_or_default();
                    if !content.trim().is_empty() {
                        if role.is_empty() {
                            parts.push(content);
                        } else {
                            parts.push(format!("{role}: {content}"));
                        }
                    }
                }
            }
            text = parts.join("\n");
        }
    }

    if text.is_empty() && messages.is_none() {
        let mut synthesized = Vec::new();
        for (k, v) in data {
            let kl = k.to_lowercase();
            if ID_KEYS.iter().any(|x| *x == kl) || kl == "split" || kl == "metadata" {
                continue;
            }
            if let Value::String(s) = v {
                if !s.trim().is_empty() {
                    synthesized.push(s.trim().to_string());
                }
            }
        }
        if !synthesized.is_empty() {
            text = synthesized.join("\n");
        }
    }

    let labels = match labels_raw {
        Some(Value::Object(m)) => Some(m.clone()),
        Some(other) => {
            let mut m = Map::new();
            m.insert("value".into(), other.clone());
            Some(m)
        }
        None => None,
    };

    let mut metadata = Map::new();
    for (k, v) in data {
        let kl = k.to_lowercase();
        let reserved = ID_KEYS.iter().any(|x| *x == kl)
            || TEXT_KEYS.iter().any(|x| *x == kl)
            || LABEL_KEYS.iter().any(|x| *x == kl)
            || MESSAGES_KEYS.iter().any(|x| *x == kl)
            || kl == "split"
            || kl == "metadata";
        if !reserved {
            metadata.insert(k.clone(), v.clone());
        }
    }
    if let Some(Value::Object(m)) = data.get("metadata") {
        for (k, v) in m {
            metadata.insert(k.clone(), v.clone());
        }
    }

    let row_id = raw_id.unwrap_or_else(|| {
        let seed = format!("{source}:{index}:{}", &text[..text.len().min(200)]);
        stable_id(&seed)
    });
    let split = data
        .get("split")
        .and_then(|v| {
            if v.is_null() {
                None
            } else {
                Some(value_as_string(v))
            }
        });

    CanonicalRecord {
        id: row_id,
        text,
        messages,
        labels,
        metadata,
        split,
    }
}

fn market_row_to_canonical(data: &Map<String, Value>, index: u64, source: &str) -> CanonicalRecord {
    let ts = pick_ci(data, MARKET_TS_KEYS)
        .map(value_as_string)
        .unwrap_or_else(|| format!("row-{index}"));
    let mut labels = Map::new();
    for key in MARKET_OHLCV {
        if let Some(v) = pick_ci(data, &[key]) {
            labels.insert((*key).to_string(), v.clone());
        }
    }
    let text = format!(
        "ohlcv ts={ts} open={} high={} low={} close={} volume={}",
        labels
            .get("open")
            .map(value_as_string)
            .unwrap_or_default(),
        labels
            .get("high")
            .map(value_as_string)
            .unwrap_or_default(),
        labels
            .get("low")
            .map(value_as_string)
            .unwrap_or_default(),
        labels
            .get("close")
            .map(value_as_string)
            .unwrap_or_default(),
        labels
            .get("volume")
            .map(value_as_string)
            .unwrap_or_default(),
    );
    let mut metadata = Map::new();
    metadata.insert("kind".into(), Value::String("market_ohlcv".into()));
    metadata.insert("source".into(), Value::String(source.to_string()));
    for (k, v) in data {
        let kl = k.to_lowercase();
        if MARKET_TS_KEYS.iter().any(|x| *x == kl) || MARKET_OHLCV.iter().any(|x| *x == kl) {
            continue;
        }
        metadata.insert(k.clone(), v.clone());
    }
    CanonicalRecord {
        id: ts,
        text,
        messages: None,
        labels: Some(labels),
        metadata,
        split: None,
    }
}

fn arrow_value_at(array: &dyn Array, row: usize) -> Value {
    if array.is_null(row) {
        return Value::Null;
    }
    match array.data_type() {
        DataType::Utf8 => {
            let a = array.as_any().downcast_ref::<StringArray>().unwrap();
            Value::String(a.value(row).to_string())
        }
        DataType::LargeUtf8 => {
            let a = array.as_any().downcast_ref::<LargeStringArray>().unwrap();
            Value::String(a.value(row).to_string())
        }
        DataType::Boolean => {
            let a = array.as_any().downcast_ref::<BooleanArray>().unwrap();
            Value::Bool(a.value(row))
        }
        DataType::Int8 => {
            let a = array.as_any().downcast_ref::<Int8Array>().unwrap();
            Value::Number(Number::from(a.value(row) as i64))
        }
        DataType::Int16 => {
            let a = array.as_any().downcast_ref::<Int16Array>().unwrap();
            Value::Number(Number::from(a.value(row) as i64))
        }
        DataType::Int32 => {
            let a = array.as_any().downcast_ref::<Int32Array>().unwrap();
            Value::Number(Number::from(i64::from(a.value(row))))
        }
        DataType::Int64 => {
            let a = array.as_any().downcast_ref::<Int64Array>().unwrap();
            Value::Number(Number::from(a.value(row)))
        }
        DataType::UInt8 => {
            let a = array.as_any().downcast_ref::<UInt8Array>().unwrap();
            Value::Number(Number::from(u64::from(a.value(row))))
        }
        DataType::UInt16 => {
            let a = array.as_any().downcast_ref::<UInt16Array>().unwrap();
            Value::Number(Number::from(u64::from(a.value(row))))
        }
        DataType::UInt32 => {
            let a = array.as_any().downcast_ref::<UInt32Array>().unwrap();
            Value::Number(Number::from(u64::from(a.value(row))))
        }
        DataType::UInt64 => {
            let a = array.as_any().downcast_ref::<UInt64Array>().unwrap();
            Value::Number(Number::from(a.value(row)))
        }
        DataType::Float32 => {
            let a = array.as_any().downcast_ref::<Float32Array>().unwrap();
            Number::from_f64(f64::from(a.value(row)))
                .map(Value::Number)
                .unwrap_or(Value::Null)
        }
        DataType::Float64 => {
            let a = array.as_any().downcast_ref::<Float64Array>().unwrap();
            Number::from_f64(a.value(row))
                .map(Value::Number)
                .unwrap_or(Value::Null)
        }
        // Nested / binary / temporal: keep plane minimal — emit typed placeholder.
        // Text/id and market OHLCV schemas use Utf8 + numeric types above.
        other => Value::String(format!("<__unsupported:{other:?}>")),
    }
}

fn batch_row_map(batch: &RecordBatch, row: usize) -> Map<String, Value> {
    let mut map = Map::new();
    for (i, field) in batch.schema().fields().iter().enumerate() {
        let col = batch.column(i);
        map.insert(field.name().clone(), arrow_value_at(col.as_ref(), row));
    }
    map
}

fn estimate_row_bytes(map: &Map<String, Value>) -> usize {
    serde_json::to_vec(map).map(|v| v.len()).unwrap_or(0)
}

/// Open parquet metadata + schema without reading row data.
pub fn open_parquet_schema(path: &Path) -> Result<(Arc<Schema>, ParquetSchemaReport)> {
    let file = File::open(path)?;
    let builder = ParquetRecordBatchReaderBuilder::try_new(file).map_err(|e| {
        DataPlaneError::coded(NATIVE_INPUT_INVALID, format!("parquet open failed: {e}"))
    })?;
    let schema = builder.schema().clone();
    let meta = builder.metadata();
    let num_row_groups = meta.num_row_groups();
    let metadata_num_rows = Some(meta.file_metadata().num_rows());
    let report = schema_report(schema.as_ref(), num_row_groups, metadata_num_rows);
    Ok((schema, report))
}

/// Callback-driven bounded batch reader — never collects the full corpus.
pub fn iter_parquet_records<F>(
    path: &Path,
    batch_rows: u64,
    max_record_bytes: u64,
    metrics: Option<&Metrics>,
    mut on_record: F,
) -> Result<(ParquetReaderStats, ParquetSchemaReport)>
where
    F: FnMut(u64, CanonicalRecord, usize) -> Result<()>,
{
    let file = File::open(path)?;
    let builder = ParquetRecordBatchReaderBuilder::try_new(file).map_err(|e| {
        DataPlaneError::coded(NATIVE_INPUT_INVALID, format!("parquet open failed: {e}"))
    })?;
    let schema = builder.schema().clone();
    let meta = builder.metadata();
    let report = schema_report(
        schema.as_ref(),
        meta.num_row_groups(),
        Some(meta.file_metadata().num_rows()),
    );
    let row_kind = report.row_kind;
    if row_kind == ParquetRowKind::Unknown {
        // Still attempt text-like synthesis from string columns; only reject totally empty schemas.
        if schema.fields().is_empty() {
            return Err(DataPlaneError::coded(
                NATIVE_INPUT_INVALID,
                "parquet schema has no fields",
            ));
        }
    }

    let batch_size = batch_rows.max(1) as usize;
    let limit = max_record_bytes.max(1) as usize;
    let source = path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("parquet");

    let reader = builder.with_batch_size(batch_size).build().map_err(|e| {
        DataPlaneError::coded(NATIVE_INPUT_INVALID, format!("parquet reader build failed: {e}"))
    })?;

    let mut stats = ParquetReaderStats::default();
    let mut index: u64 = 0;

    for batch_result in reader {
        let batch = batch_result.map_err(|e| {
            DataPlaneError::coded(NATIVE_INPUT_INVALID, format!("parquet batch read failed: {e}"))
        })?;
        stats.batches += 1;
        let n = batch.num_rows();
        // Enforce batch row budget (builder already sizes; still guard oversized batches).
        if n as u64 > batch_rows.max(1) * 4 {
            return Err(DataPlaneError::coded(
                NATIVE_INPUT_INVALID,
                format!(
                    "parquet batch rows={n} exceeds safety multiple of batch_rows={batch_rows}"
                ),
            ));
        }
        for row in 0..n {
            let map = batch_row_map(&batch, row);
            let est = estimate_row_bytes(&map);
            if est > limit {
                return Err(DataPlaneError::coded(
                    NATIVE_RECORD_TOO_LARGE,
                    format!(
                        "Parquet record exceeds max_record_bytes={limit} at row {index} (est={est})"
                    ),
                ));
            }
            // Skip pure-null rows.
            let any_value = map.values().any(|v| !v.is_null());
            if !any_value {
                stats.skipped_empty += 1;
                index += 1;
                continue;
            }
            let rec = row_to_canonical(&map, index, source, row_kind);
            // Also bound canonical payload size.
            let line_est = serde_json::to_vec(&rec.to_canonical_value())
                .map(|v| v.len())
                .unwrap_or(est);
            if line_est > limit {
                return Err(DataPlaneError::coded(
                    NATIVE_RECORD_TOO_LARGE,
                    format!(
                        "Parquet canonical record exceeds max_record_bytes={limit} at row {index}"
                    ),
                ));
            }
            stats.records += 1;
            stats.bytes += est as u64;
            if let Some(m) = metrics {
                m.bump_in(1, est as u64);
            }
            on_record(index, rec, est)?;
            index += 1;
        }
    }

    Ok((stats, report))
}

#[cfg(test)]
mod tests {
    use super::*;
    use arrow_array::{Float64Array, StringArray};
    use arrow_schema::Field;
    use parquet::arrow::ArrowWriter;
    use tempfile::NamedTempFile;

    fn write_text_parquet(path: &Path) {
        let schema = Arc::new(Schema::new(vec![
            Field::new("id", DataType::Utf8, false),
            Field::new("text", DataType::Utf8, false),
        ]));
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(StringArray::from(vec!["r1", "r2"])),
                Arc::new(StringArray::from(vec!["hello", "world"])),
            ],
        )
        .unwrap();
        let file = File::create(path).unwrap();
        let mut writer = ArrowWriter::try_new(file, schema, None).unwrap();
        writer.write(&batch).unwrap();
        writer.close().unwrap();
    }

    fn write_market_parquet(path: &Path) {
        let schema = Arc::new(Schema::new(vec![
            Field::new("timestamp", DataType::Utf8, false),
            Field::new("open", DataType::Float64, false),
            Field::new("high", DataType::Float64, false),
            Field::new("low", DataType::Float64, false),
            Field::new("close", DataType::Float64, false),
            Field::new("volume", DataType::Float64, false),
        ]));
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(StringArray::from(vec!["2024-01-01T00:00:00Z"])),
                Arc::new(Float64Array::from(vec![1.0])),
                Arc::new(Float64Array::from(vec![2.0])),
                Arc::new(Float64Array::from(vec![0.5])),
                Arc::new(Float64Array::from(vec![1.5])),
                Arc::new(Float64Array::from(vec![100.0])),
            ],
        )
        .unwrap();
        let file = File::create(path).unwrap();
        let mut writer = ArrowWriter::try_new(file, schema, None).unwrap();
        writer.write(&batch).unwrap();
        writer.close().unwrap();
    }

    #[test]
    fn reads_text_rows() {
        let tmp = NamedTempFile::new().unwrap();
        write_text_parquet(tmp.path());
        let mut ids = Vec::new();
        let (stats, report) = iter_parquet_records(tmp.path(), 64, 1_000_000, None, |_i, rec, _| {
            ids.push(rec.id.clone());
            Ok(())
        })
        .unwrap();
        assert_eq!(stats.records, 2);
        assert_eq!(report.row_kind, ParquetRowKind::Text);
        assert_eq!(ids, vec!["r1".to_string(), "r2".to_string()]);
    }

    #[test]
    fn reads_market_rows() {
        let tmp = NamedTempFile::new().unwrap();
        write_market_parquet(tmp.path());
        let mut texts = Vec::new();
        let (stats, report) = iter_parquet_records(tmp.path(), 64, 1_000_000, None, |_i, rec, _| {
            texts.push(rec.text.clone());
            assert_eq!(rec.id, "2024-01-01T00:00:00Z");
            Ok(())
        })
        .unwrap();
        assert_eq!(stats.records, 1);
        assert_eq!(report.row_kind, ParquetRowKind::Market);
        assert!(texts[0].contains("ohlcv"));
    }

    #[test]
    fn enforces_max_record_bytes() {
        let tmp = NamedTempFile::new().unwrap();
        write_text_parquet(tmp.path());
        let err = iter_parquet_records(tmp.path(), 64, 8, None, |_, _, _| Ok(())).unwrap_err();
        assert_eq!(err.code(), NATIVE_RECORD_TOO_LARGE);
    }
}
