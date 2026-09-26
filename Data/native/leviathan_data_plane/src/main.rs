//! Leviathan native data-plane binary (`leviathan-data-plane`).
//!
//! Task protocol: JSON file in / receipt file out (not full datasets on stdin).
//! Progress: bounded JSON lines on stderr (`type=progress`).

mod error;
mod io;
mod metrics;
mod ops;
mod protocol;

use clap::Parser;
use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::process::ExitCode;
use std::sync::Arc;

use crate::error::{DataPlaneError, NATIVE_INPUT_MISSING, NATIVE_INTERNAL};
use crate::metrics::{current_rss_bytes, Metrics};
use crate::protocol::{capabilities_document, validate_protocol_version, NativeTask, TaskReceipt};

#[derive(Debug, Parser)]
#[command(
    name = "leviathan-data-plane",
    about = "Leviathan Rust native dataset data-plane",
    version
)]
struct Cli {
    /// Print capability handshake document and exit.
    #[arg(long)]
    capabilities: bool,

    /// Emit JSON (required with --capabilities for machine handshake).
    #[arg(long)]
    json: bool,

    /// Path to task JSON file.
    #[arg(long)]
    task: Option<PathBuf>,

    /// Path to write receipt JSON (defaults to task.output.temporaryPath + ".receipt.json").
    #[arg(long)]
    receipt: Option<PathBuf>,
}

fn main() -> ExitCode {
    let cli = Cli::parse();

    if cli.capabilities {
        let doc = capabilities_document();
        if cli.json {
            match serde_json::to_string_pretty(&doc) {
                Ok(s) => {
                    println!("{s}");
                    return ExitCode::SUCCESS;
                }
                Err(e) => {
                    eprintln!("failed to serialize capabilities: {e}");
                    return ExitCode::from(2);
                }
            }
        }
        println!(
            "leviathan-data-plane protocolVersion={} operations={}",
            doc.protocol_version,
            doc.operations.join(",")
        );
        return ExitCode::SUCCESS;
    }

    let Some(task_path) = cli.task.as_ref() else {
        eprintln!("error: --task <path> is required (or pass --capabilities --json)");
        return ExitCode::from(2);
    };

    match run_task(task_path, cli.receipt.as_ref()) {
        Ok(code) => code,
        Err(e) => {
            eprintln!("{}: {}", e.code(), e.message());
            ExitCode::from(1)
        }
    }
}

fn run_task(
    task_path: &PathBuf,
    receipt_override: Option<&PathBuf>,
) -> Result<ExitCode, DataPlaneError> {
    if !task_path.exists() {
        return Err(DataPlaneError::coded(
            NATIVE_INPUT_MISSING,
            format!("task file missing: {}", task_path.display()),
        ));
    }
    let raw = fs::read_to_string(task_path)?;
    let task: NativeTask = serde_json::from_str(&raw)?;
    validate_protocol_version(task.protocol_version)?;

    let metrics = Metrics::new(&task.task_id, &task.operation);
    let receipt_path = receipt_override
        .cloned()
        .unwrap_or_else(|| PathBuf::from(format!("{}.receipt.json", task.output.temporary_path)));

    let receipt = match ops::dispatch(&task, Arc::clone(&metrics)) {
        Ok(r) => r,
        Err(e) => {
            metrics.sample_rss();
            TaskReceipt::fail(
                &task.task_id,
                &task.operation,
                e.code(),
                &e.message(),
                metrics.duration_ms(),
                metrics.snapshot_counts().4.max(current_rss_bytes()),
            )
        }
    };

    write_receipt(&receipt_path, &receipt)?;
    // Also emit receipt JSON on stdout (bounded — receipt only, not dataset).
    let stdout_payload = serde_json::to_string(&receipt)
        .map_err(|e| DataPlaneError::coded(NATIVE_INTERNAL, format!("receipt serialize: {e}")))?;
    let mut out = std::io::stdout().lock();
    writeln!(out, "{stdout_payload}")?;
    out.flush()?;

    if receipt.status == "ok" {
        Ok(ExitCode::SUCCESS)
    } else {
        Ok(ExitCode::from(1))
    }
}

fn write_receipt(path: &PathBuf, receipt: &TaskReceipt) -> Result<(), DataPlaneError> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let pretty = serde_json::to_vec_pretty(receipt)?;
    fs::write(path, pretty)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::PROTOCOL_VERSION;
    use serde_json::json;
    use std::io::Write;
    use tempfile::tempdir;

    #[test]
    fn end_to_end_hash_task() {
        let dir = tempdir().unwrap();
        let input = dir.path().join("in.jsonl");
        let output = dir.path().join("out.json");
        let mut f = fs::File::create(&input).unwrap();
        writeln!(
            f,
            "{}",
            serde_json::to_string(&json!({"id":"r1","text":"hello","metadata":{}})).unwrap()
        )
        .unwrap();

        let task = NativeTask {
            protocol_version: PROTOCOL_VERSION,
            task_id: "t-hash".into(),
            operation: "dataset.hash".into(),
            input: crate::protocol::TaskInput {
                path: input.display().to_string(),
                format: "jsonl".into(),
                content_hash: None,
            },
            output: crate::protocol::TaskOutput {
                temporary_path: output.display().to_string(),
            },
            limits: Default::default(),
            options: json!({}),
            allowed_roots: vec![dir.path().display().to_string()],
        };
        let task_path = dir.path().join("task.json");
        fs::write(&task_path, serde_json::to_string(&task).unwrap()).unwrap();
        let receipt_path = dir.path().join("receipt.json");
        let code = run_task(&task_path, Some(&receipt_path)).unwrap();
        assert_eq!(code, ExitCode::SUCCESS);
        let receipt: TaskReceipt =
            serde_json::from_str(&fs::read_to_string(receipt_path).unwrap()).unwrap();
        assert_eq!(receipt.status, "ok");
        assert!(receipt.content_hash.is_some());
        assert_eq!(receipt.records_in, 1);
    }
}
