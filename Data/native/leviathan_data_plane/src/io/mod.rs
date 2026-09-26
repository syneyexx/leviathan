//! Canonical JSONL + Parquet I/O matching Python `CanonicalRecord`.
//! Market OHLCV streaming readers for `market.ohlcv_validate`.

mod jsonl;
mod ohlcv;
mod parquet;

pub use jsonl::{
    content_hash_update, fingerprint_payload, iter_jsonl_records, write_canonical_line,
    CanonicalRecord,
};
pub use ohlcv::{iter_ohlcv_validate, OhlcvFormat};
pub use parquet::{
    iter_parquet_records, open_parquet_schema, ParquetFieldInfo, ParquetRowKind,
};
