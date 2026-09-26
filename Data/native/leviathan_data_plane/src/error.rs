//! Shared error codes for the Leviathan native data-plane.

use thiserror::Error;

pub const NATIVE_PROTOCOL_MISMATCH: &str = "NATIVE_PROTOCOL_MISMATCH";
pub const NATIVE_UNSUPPORTED_OPERATION: &str = "NATIVE_UNSUPPORTED_OPERATION";
pub const NATIVE_INPUT_MISSING: &str = "NATIVE_INPUT_MISSING";
pub const NATIVE_INPUT_INVALID: &str = "NATIVE_INPUT_INVALID";
pub const NATIVE_RECORD_TOO_LARGE: &str = "NATIVE_RECORD_TOO_LARGE";
pub const NATIVE_MEMORY_BUDGET_EXCEEDED: &str = "NATIVE_MEMORY_BUDGET_EXCEEDED";
pub const NATIVE_SPILL_BUDGET_EXCEEDED: &str = "NATIVE_SPILL_BUDGET_EXCEEDED";
pub const NATIVE_PATH_REJECTED: &str = "NATIVE_PATH_REJECTED";
/// Raised when the Python runner kills/cancels the child process mid-task.
#[allow(dead_code)]
pub const NATIVE_CANCELLED: &str = "NATIVE_CANCELLED";
pub const NATIVE_IO_ERROR: &str = "NATIVE_IO_ERROR";
pub const NATIVE_JSON_ERROR: &str = "NATIVE_JSON_ERROR";
pub const NATIVE_INTERNAL: &str = "NATIVE_INTERNAL";
pub const NATIVE_OPTIONS_INVALID: &str = "NATIVE_OPTIONS_INVALID";
/// Reserved for output-path / receipt publish failures.
#[allow(dead_code)]
pub const NATIVE_OUTPUT_INVALID: &str = "NATIVE_OUTPUT_INVALID";

#[derive(Debug, Error)]
pub enum DataPlaneError {
    #[error("{code}: {message}")]
    Coded { code: &'static str, message: String },

    #[error(transparent)]
    Io(#[from] std::io::Error),

    #[error(transparent)]
    Json(#[from] serde_json::Error),
}

impl DataPlaneError {
    pub fn coded(code: &'static str, message: impl Into<String>) -> Self {
        Self::Coded {
            code,
            message: message.into(),
        }
    }

    pub fn code(&self) -> &'static str {
        match self {
            Self::Coded { code, .. } => code,
            Self::Io(_) => NATIVE_IO_ERROR,
            Self::Json(_) => NATIVE_JSON_ERROR,
        }
    }

    pub fn message(&self) -> String {
        match self {
            Self::Coded { message, .. } => message.clone(),
            Self::Io(e) => e.to_string(),
            Self::Json(e) => e.to_string(),
        }
    }
}

pub type Result<T> = std::result::Result<T, DataPlaneError>;
