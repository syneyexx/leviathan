//! Canonical JSONL I/O matching Python `CanonicalRecord`.

mod jsonl;

pub use jsonl::{
    content_hash_update, fingerprint_payload, iter_jsonl_records, write_canonical_line,
    CanonicalRecord,
};
