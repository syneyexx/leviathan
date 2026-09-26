//! Streaming OHLCV readers for CSV / JSONL / Parquet (market-data pilot).
//!
//! Deterministic validation aligned with Python `Data.modules.market_sim.ohlcv`
//! streaming checks: required columns, OHLC invariants, sorted unique timestamps.

use arrow_array::{
    Array, Float32Array, Float64Array, Int32Array, Int64Array, RecordBatch, StringArray,
    TimestampMicrosecondArray, TimestampMillisecondArray, TimestampNanosecondArray,
    TimestampSecondArray,
};
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
use serde_json::Value;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

use crate::error::{DataPlaneError, Result, NATIVE_INPUT_INVALID};
use crate::metrics::Metrics;

const REQUIRED: &[&str] = &["timestamp", "open", "high", "low", "close", "volume"];
const TS_ALIASES: &[&str] = &["timestamp", "ts", "time", "datetime", "date"];

#[derive(Debug, Clone)]
#[allow(dead_code)] // fields consumed via validation paths / future export
pub struct OhlcvBar {
    pub ts: String,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OhlcvFormat {
    Csv,
    Jsonl,
    Parquet,
}

impl OhlcvFormat {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Csv => "csv",
            Self::Jsonl => "jsonl",
            Self::Parquet => "parquet",
        }
    }

    pub fn detect(path: &Path, hint: &str) -> Result<Self> {
        let hint = hint.trim().to_lowercase();
        if matches!(hint.as_str(), "csv" | "txt") {
            return Ok(Self::Csv);
        }
        if matches!(hint.as_str(), "jsonl" | "ndjson") {
            return Ok(Self::Jsonl);
        }
        if hint == "parquet" {
            return Ok(Self::Parquet);
        }
        match path
            .extension()
            .and_then(|e| e.to_str())
            .unwrap_or("")
            .to_lowercase()
            .as_str()
        {
            "csv" | "txt" => Ok(Self::Csv),
            "jsonl" | "ndjson" => Ok(Self::Jsonl),
            "parquet" => Ok(Self::Parquet),
            other => Err(DataPlaneError::coded(
                NATIVE_INPUT_INVALID,
                format!("unsupported OHLCV format: {other}"),
            )),
        }
    }
}

#[derive(Debug, Default)]
pub struct OhlcvScanStats {
    pub bars: u64,
    pub bytes: u64,
    pub start_ts: Option<String>,
    pub end_ts: Option<String>,
    pub duplicate_count: u64,
}

/// Normalize vendor timestamps toward UTC ISO-8601 seconds (best-effort).
pub fn normalize_ts(raw: &str) -> Result<String> {
    let text = raw.trim();
    if text.is_empty() {
        return Err(DataPlaneError::coded(
            NATIVE_INPUT_INVALID,
            "empty timestamp",
        ));
    }

    // Compact YYYYMMDD / YYYYMMDDHHMMSS
    if text.chars().all(|c| c.is_ascii_digit()) {
        if text.len() == 8 {
            return Ok(format!(
                "{}-{}-{}T00:00:00+00:00",
                &text[0..4],
                &text[4..6],
                &text[6..8]
            ));
        }
        if text.len() == 14 {
            return Ok(format!(
                "{}-{}-{}T{}:{}:{}+00:00",
                &text[0..4],
                &text[4..6],
                &text[6..8],
                &text[8..10],
                &text[10..12],
                &text[12..14]
            ));
        }
    }

    // Numeric epoch (seconds / ms / µs)
    if text
        .chars()
        .all(|c| c.is_ascii_digit() || c == '.')
        && text.parse::<f64>().is_ok()
    {
        let mut value: f64 = text.parse().unwrap();
        if value >= 1e14 {
            value /= 1_000_000.0;
        } else if value >= 1e12 {
            value /= 1000.0;
        }
        if (19_000_000.0..=21_001_231.0).contains(&value) && value == value.trunc() {
            let as_int = value as i64;
            let as_text = format!("{as_int:08}");
            if as_text.len() == 8 {
                return Ok(format!(
                    "{}-{}-{}T00:00:00+00:00",
                    &as_text[0..4],
                    &as_text[4..6],
                    &as_text[6..8]
                ));
            }
        }
        let secs = value.floor() as i64;
        return Ok(format_epoch_secs(secs));
    }

    // ISO-ish: accept Z / +00:00 / space separator; truncate to seconds when present.
    let cleaned = text.replace('Z', "+00:00");
    let cleaned = cleaned.replace(' ', "T");
    if let Some(norm) = normalize_iso_like(&cleaned) {
        return Ok(norm);
    }
    // Date-only YYYY-MM-DD / YYYY/MM/DD
    let date_only = cleaned.replace('/', "-");
    if date_only.len() == 10 && date_only.chars().filter(|c| *c == '-').count() == 2 {
        return Ok(format!("{date_only}T00:00:00+00:00"));
    }

    Err(DataPlaneError::coded(
        NATIVE_INPUT_INVALID,
        format!("Unrecognized timestamp: {text:?}"),
    ))
}

fn format_epoch_secs(secs: i64) -> String {
    // Minimal UTC formatting without chrono dependency.
    // Algorithm from civil_from_days (Howard Hinnant).
    let z = secs.div_euclid(86_400) + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 }.div_euclid(146_097);
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    let tod = secs.rem_euclid(86_400) as u32;
    let hh = tod / 3600;
    let mm = (tod % 3600) / 60;
    let ss = tod % 60;
    format!("{y:04}-{m:02}-{d:02}T{hh:02}:{mm:02}:{ss:02}+00:00")
}

fn normalize_iso_like(s: &str) -> Option<String> {
    // Expect YYYY-MM-DDTHH:MM:SS[.frac][+tz]
    let (date, rest) = s.split_once('T')?;
    if date.len() != 10 {
        return None;
    }
    let (time_part, tz) = if let Some(idx) = rest.rfind('+').or_else(|| {
        // find timezone minus after time digits
        rest.char_indices()
            .skip(8)
            .find(|(_, c)| *c == '-')
            .map(|(i, _)| i)
    }) {
        (&rest[..idx], &rest[idx..])
    } else {
        (rest, "+00:00")
    };
    let time_part = time_part.split('.').next().unwrap_or(time_part);
    let parts: Vec<&str> = time_part.split(':').collect();
    if parts.len() < 2 {
        return None;
    }
    let hh = parts[0];
    let mm = parts[1];
    let ss = if parts.len() >= 3 { parts[2] } else { "00" };
    let tz = if tz.is_empty() { "+00:00" } else { tz };
    // Collapse Z already handled; ensure +HH:MM form
    let tz_norm = if tz == "Z" {
        "+00:00".to_string()
    } else if tz.len() == 3 {
        format!("{tz}:00")
    } else {
        tz.to_string()
    };
    let ss = ss.trim_end_matches(|c: char| !c.is_ascii_digit());
    Some(format!("{date}T{hh}:{mm}:{ss}{tz_norm}"))
}

pub fn check_ohlc(o: f64, h: f64, l: f64, c: f64) -> bool {
    h >= o.max(c) && l <= o.min(c) && h >= l
}

/// Stream-validate OHLCV from path; on_bar is called for each accepted bar.
pub fn iter_ohlcv_validate<F>(
    path: &Path,
    format: OhlcvFormat,
    batch_rows: u64,
    metrics: Option<&Metrics>,
    mut on_bar: F,
) -> Result<OhlcvScanStats>
where
    F: FnMut(u64, &OhlcvBar) -> Result<()>,
{
    match format {
        OhlcvFormat::Csv => iter_csv(path, metrics, &mut on_bar),
        OhlcvFormat::Jsonl => iter_jsonl(path, metrics, &mut on_bar),
        OhlcvFormat::Parquet => iter_parquet(path, batch_rows, metrics, &mut on_bar),
    }
}

fn map_header(fields: &[String]) -> Result<Vec<usize>> {
    let lower: Vec<String> = fields.iter().map(|f| f.trim().to_lowercase()).collect();
    let mut idxs = Vec::with_capacity(6);
    let mut ts_idx = None;
    for alt in TS_ALIASES {
        if let Some(i) = lower.iter().position(|n| n == alt) {
            ts_idx = Some(i);
            break;
        }
    }
    let ts_idx = ts_idx.ok_or_else(|| {
        DataPlaneError::coded(NATIVE_INPUT_INVALID, "Missing columns: [\"timestamp\"]")
    })?;
    idxs.push(ts_idx);
    for col in &["open", "high", "low", "close", "volume"] {
        let found = if *col == "volume" {
            lower
                .iter()
                .position(|n| n == "volume" || n == "vol")
        } else {
            lower.iter().position(|n| n == col)
        };
        let i = found.ok_or_else(|| {
            DataPlaneError::coded(
                NATIVE_INPUT_INVALID,
                format!("Missing columns: [{col:?}]; found={lower:?}"),
            )
        })?;
        idxs.push(i);
    }
    let _ = REQUIRED;
    Ok(idxs)
}

fn validate_order(
    prev: &mut Option<String>,
    ts: &str,
    row_num: u64,
    stats: &mut OhlcvScanStats,
) -> Result<()> {
    if let Some(p) = prev.as_ref() {
        if ts < p.as_str() {
            return Err(DataPlaneError::coded(
                NATIVE_INPUT_INVALID,
                format!("Row {row_num}: timestamps not sorted ({p} -> {ts})"),
            ));
        }
        if ts == p.as_str() {
            stats.duplicate_count += 1;
            return Err(DataPlaneError::coded(
                NATIVE_INPUT_INVALID,
                format!("Row {row_num}: duplicate timestamp {ts}"),
            ));
        }
    }
    *prev = Some(ts.to_string());
    Ok(())
}

fn iter_csv<F>(path: &Path, metrics: Option<&Metrics>, on_bar: &mut F) -> Result<OhlcvScanStats>
where
    F: FnMut(u64, &OhlcvBar) -> Result<()>,
{
    let file = File::open(path)?;
    let meta_len = file.metadata().map(|m| m.len()).unwrap_or(0);
    let reader = BufReader::new(file);
    let mut lines = reader.lines();
    let header_line = lines.next().transpose()?.ok_or_else(|| {
        DataPlaneError::coded(NATIVE_INPUT_INVALID, "CSV has no header row")
    })?;
    let fields: Vec<String> = split_csv_line(&header_line);
    let map = map_header(&fields)?;
    let mut stats = OhlcvScanStats {
        bytes: meta_len,
        ..Default::default()
    };
    let mut prev: Option<String> = None;
    let mut row_num: u64 = 1;
    for line in lines {
        let line = line?;
        row_num += 1;
        if line.trim().is_empty() {
            continue;
        }
        let cols = split_csv_line(&line);
        let get = |i: usize| -> Result<&str> {
            cols.get(i)
                .map(|s| s.as_str())
                .ok_or_else(|| {
                    DataPlaneError::coded(
                        NATIVE_INPUT_INVALID,
                        format!("Row {row_num}: missing column"),
                    )
                })
        };
        let ts = normalize_ts(get(map[0])?)?;
        let o: f64 = parse_f64(get(map[1])?, row_num)?;
        let h: f64 = parse_f64(get(map[2])?, row_num)?;
        let l: f64 = parse_f64(get(map[3])?, row_num)?;
        let c: f64 = parse_f64(get(map[4])?, row_num)?;
        let v: f64 = parse_f64(get(map[5])?, row_num)?;
        if !check_ohlc(o, h, l, c) {
            return Err(DataPlaneError::coded(
                NATIVE_INPUT_INVALID,
                format!("Row {row_num}: OHLC inconsistency o={o} h={h} l={l} c={c}"),
            ));
        }
        validate_order(&mut prev, &ts, row_num, &mut stats)?;
        let bar = OhlcvBar {
            ts: ts.clone(),
            open: o,
            high: h,
            low: l,
            close: c,
            volume: v,
        };
        if stats.start_ts.is_none() {
            stats.start_ts = Some(ts.clone());
        }
        stats.end_ts = Some(ts);
        stats.bars += 1;
        if let Some(m) = metrics {
            m.bump_in(1, 64);
        }
        on_bar(stats.bars, &bar)?;
    }
    Ok(stats)
}

fn split_csv_line(line: &str) -> Vec<String> {
    // Simple split — OHLCV fixtures do not embed commas in fields.
    line.split(',')
        .map(|s| s.trim().trim_matches('"').to_string())
        .collect()
}

fn parse_f64(raw: &str, row_num: u64) -> Result<f64> {
    raw.trim().parse::<f64>().map_err(|e| {
        DataPlaneError::coded(
            NATIVE_INPUT_INVALID,
            format!("Row {row_num}: {e}"),
        )
    })
}

fn iter_jsonl<F>(path: &Path, metrics: Option<&Metrics>, on_bar: &mut F) -> Result<OhlcvScanStats>
where
    F: FnMut(u64, &OhlcvBar) -> Result<()>,
{
    let file = File::open(path)?;
    let meta_len = file.metadata().map(|m| m.len()).unwrap_or(0);
    let reader = BufReader::new(file);
    let mut stats = OhlcvScanStats {
        bytes: meta_len,
        ..Default::default()
    };
    let mut prev: Option<String> = None;
    let mut row_num: u64 = 0;
    for line in reader.lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        row_num += 1;
        let v: Value = serde_json::from_str(&line).map_err(|e| {
            DataPlaneError::coded(
                NATIVE_INPUT_INVALID,
                format!("Row {row_num}: invalid JSONL: {e}"),
            )
        })?;
        let obj = v.as_object().ok_or_else(|| {
            DataPlaneError::coded(
                NATIVE_INPUT_INVALID,
                format!("Row {row_num}: JSONL row must be an object"),
            )
        })?;
        let ts_raw = pick_field(obj, TS_ALIASES).ok_or_else(|| {
            DataPlaneError::coded(
                NATIVE_INPUT_INVALID,
                format!("Row {row_num}: Missing columns: [\"timestamp\"]"),
            )
        })?;
        let ts = normalize_ts(&value_to_string(ts_raw))?;
        let o = pick_f64(obj, &["open"], row_num)?;
        let h = pick_f64(obj, &["high"], row_num)?;
        let l = pick_f64(obj, &["low"], row_num)?;
        let c = pick_f64(obj, &["close"], row_num)?;
        let vol = pick_f64(obj, &["volume", "vol"], row_num)?;
        if !check_ohlc(o, h, l, c) {
            return Err(DataPlaneError::coded(
                NATIVE_INPUT_INVALID,
                format!("Row {row_num}: OHLC inconsistency o={o} h={h} l={l} c={c}"),
            ));
        }
        validate_order(&mut prev, &ts, row_num, &mut stats)?;
        let bar = OhlcvBar {
            ts: ts.clone(),
            open: o,
            high: h,
            low: l,
            close: c,
            volume: vol,
        };
        if stats.start_ts.is_none() {
            stats.start_ts = Some(ts.clone());
        }
        stats.end_ts = Some(ts);
        stats.bars += 1;
        if let Some(m) = metrics {
            m.bump_in(1, line.len() as u64);
        }
        on_bar(stats.bars, &bar)?;
    }
    Ok(stats)
}

fn pick_field<'a>(obj: &'a serde_json::Map<String, Value>, keys: &[&str]) -> Option<&'a Value> {
    for key in keys {
        if let Some(v) = obj.get(*key) {
            if !v.is_null() {
                return Some(v);
            }
        }
        for (k, v) in obj {
            if k.eq_ignore_ascii_case(key) && !v.is_null() {
                return Some(v);
            }
        }
    }
    None
}

fn value_to_string(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Null => String::new(),
        other => other.to_string(),
    }
}

fn pick_f64(obj: &serde_json::Map<String, Value>, keys: &[&str], row_num: u64) -> Result<f64> {
    let v = pick_field(obj, keys).ok_or_else(|| {
        DataPlaneError::coded(
            NATIVE_INPUT_INVALID,
            format!("Row {row_num}: Missing columns: {:?}", keys[0]),
        )
    })?;
    match v {
        Value::Number(n) => n.as_f64().ok_or_else(|| {
            DataPlaneError::coded(NATIVE_INPUT_INVALID, format!("Row {row_num}: bad number"))
        }),
        Value::String(s) => parse_f64(s, row_num),
        _ => Err(DataPlaneError::coded(
            NATIVE_INPUT_INVALID,
            format!("Row {row_num}: expected number"),
        )),
    }
}

fn iter_parquet<F>(
    path: &Path,
    batch_rows: u64,
    metrics: Option<&Metrics>,
    on_bar: &mut F,
) -> Result<OhlcvScanStats>
where
    F: FnMut(u64, &OhlcvBar) -> Result<()>,
{
    let file = File::open(path)?;
    let meta_len = file.metadata().map(|m| m.len()).unwrap_or(0);
    let builder = ParquetRecordBatchReaderBuilder::try_new(file).map_err(|e| {
        DataPlaneError::coded(NATIVE_INPUT_INVALID, format!("parquet open failed: {e}"))
    })?;
    let schema = builder.schema().clone();
    let names: Vec<String> = schema.fields().iter().map(|f| f.name().clone()).collect();
    let lower: Vec<String> = names.iter().map(|n| n.to_lowercase()).collect();
    let map = map_header(&lower)?;
    let batch_size = batch_rows.max(1) as usize;
    let reader = builder
        .with_batch_size(batch_size)
        .build()
        .map_err(|e| DataPlaneError::coded(NATIVE_INPUT_INVALID, format!("parquet reader: {e}")))?;

    let mut stats = OhlcvScanStats {
        bytes: meta_len,
        ..Default::default()
    };
    let mut prev: Option<String> = None;
    let mut row_num: u64 = 0;

    for batch in reader {
        let batch = batch.map_err(|e| {
            DataPlaneError::coded(NATIVE_INPUT_INVALID, format!("parquet batch: {e}"))
        })?;
        scan_batch(&batch, &map, &mut prev, &mut row_num, &mut stats, metrics, on_bar)?;
    }
    Ok(stats)
}

fn scan_batch<F>(
    batch: &RecordBatch,
    map: &[usize],
    prev: &mut Option<String>,
    row_num: &mut u64,
    stats: &mut OhlcvScanStats,
    metrics: Option<&Metrics>,
    on_bar: &mut F,
) -> Result<()>
where
    F: FnMut(u64, &OhlcvBar) -> Result<()>,
{
    let n = batch.num_rows();
    let ts_col = batch.column(map[0]);
    let o_col = batch.column(map[1]);
    let h_col = batch.column(map[2]);
    let l_col = batch.column(map[3]);
    let c_col = batch.column(map[4]);
    let v_col = batch.column(map[5]);
    for i in 0..n {
        *row_num += 1;
        let ts = normalize_ts(&array_to_string(ts_col.as_ref(), i)?)?;
        let o = array_to_f64(o_col.as_ref(), i, *row_num)?;
        let h = array_to_f64(h_col.as_ref(), i, *row_num)?;
        let l = array_to_f64(l_col.as_ref(), i, *row_num)?;
        let c = array_to_f64(c_col.as_ref(), i, *row_num)?;
        let v = array_to_f64(v_col.as_ref(), i, *row_num)?;
        if !check_ohlc(o, h, l, c) {
            return Err(DataPlaneError::coded(
                NATIVE_INPUT_INVALID,
                format!("Row {}: OHLC inconsistency o={o} h={h} l={l} c={c}", *row_num),
            ));
        }
        validate_order(prev, &ts, *row_num, stats)?;
        let bar = OhlcvBar {
            ts: ts.clone(),
            open: o,
            high: h,
            low: l,
            close: c,
            volume: v,
        };
        if stats.start_ts.is_none() {
            stats.start_ts = Some(ts.clone());
        }
        stats.end_ts = Some(ts);
        stats.bars += 1;
        if let Some(m) = metrics {
            m.bump_in(1, 64);
        }
        on_bar(stats.bars, &bar)?;
    }
    Ok(())
}

fn array_to_string(arr: &dyn Array, i: usize) -> Result<String> {
    if arr.is_null(i) {
        return Err(DataPlaneError::coded(
            NATIVE_INPUT_INVALID,
            "null timestamp",
        ));
    }
    if let Some(a) = arr.as_any().downcast_ref::<StringArray>() {
        return Ok(a.value(i).to_string());
    }
    if let Some(a) = arr.as_any().downcast_ref::<TimestampSecondArray>() {
        return Ok(format_epoch_secs(a.value(i)));
    }
    if let Some(a) = arr.as_any().downcast_ref::<TimestampMillisecondArray>() {
        return Ok(format_epoch_secs(a.value(i) / 1000));
    }
    if let Some(a) = arr.as_any().downcast_ref::<TimestampMicrosecondArray>() {
        return Ok(format_epoch_secs(a.value(i) / 1_000_000));
    }
    if let Some(a) = arr.as_any().downcast_ref::<TimestampNanosecondArray>() {
        return Ok(format_epoch_secs(a.value(i) / 1_000_000_000));
    }
    if let Some(a) = arr.as_any().downcast_ref::<Int64Array>() {
        return Ok(a.value(i).to_string());
    }
    Err(DataPlaneError::coded(
        NATIVE_INPUT_INVALID,
        format!("unsupported timestamp column type: {:?}", arr.data_type()),
    ))
}

fn array_to_f64(arr: &dyn Array, i: usize, row_num: u64) -> Result<f64> {
    if arr.is_null(i) {
        return Err(DataPlaneError::coded(
            NATIVE_INPUT_INVALID,
            format!("Row {row_num}: null numeric"),
        ));
    }
    if let Some(a) = arr.as_any().downcast_ref::<Float64Array>() {
        return Ok(a.value(i));
    }
    if let Some(a) = arr.as_any().downcast_ref::<Float32Array>() {
        return Ok(a.value(i) as f64);
    }
    if let Some(a) = arr.as_any().downcast_ref::<Int64Array>() {
        return Ok(a.value(i) as f64);
    }
    if let Some(a) = arr.as_any().downcast_ref::<Int32Array>() {
        return Ok(a.value(i) as f64);
    }
    if let Some(a) = arr.as_any().downcast_ref::<StringArray>() {
        return parse_f64(a.value(i), row_num);
    }
    Err(DataPlaneError::coded(
        NATIVE_INPUT_INVALID,
        format!("Row {row_num}: unsupported numeric type {:?}", arr.data_type()),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn csv_validate_ok() {
        let mut tmp = NamedTempFile::new().unwrap();
        writeln!(
            tmp,
            "timestamp,open,high,low,close,volume\n2024-01-01T00:00:00+00:00,1,2,0.5,1.5,10\n2024-01-01T01:00:00+00:00,1.5,2.5,1,2,11"
        )
        .unwrap();
        let stats = iter_ohlcv_validate(tmp.path(), OhlcvFormat::Csv, 64, None, |_, _| Ok(())).unwrap();
        assert_eq!(stats.bars, 2);
        assert_eq!(stats.start_ts.as_deref(), Some("2024-01-01T00:00:00+00:00"));
    }

    #[test]
    fn rejects_ohlc_break() {
        let mut tmp = NamedTempFile::new().unwrap();
        writeln!(
            tmp,
            "timestamp,open,high,low,close,volume\n2024-01-01T00:00:00+00:00,1,0.5,0.4,1.5,10"
        )
        .unwrap();
        let err = iter_ohlcv_validate(tmp.path(), OhlcvFormat::Csv, 64, None, |_, _| Ok(())).unwrap_err();
        assert!(err.message().contains("OHLC"));
    }
}
