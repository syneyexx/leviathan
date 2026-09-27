use std::sync::LazyLock;

use regex::Regex;

static SECRET: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"(?i)(authorization\s*:\s*bearer\s+)\S+|((?:api[_-]?key|secret|password|passwd|token)\s*[=:]\s*)\S+|\bsk-[A-Za-z0-9]{8,}\b|\bbearer\s+[A-Za-z0-9\-._~+/]{8,}={0,2}",
    )
    .expect("redaction regex")
});

pub fn redact_line(input: &str) -> String {
    let capped = if input.len() > 8_000 {
        format!("{}…[truncated]", &input[..8_000])
    } else {
        input.to_string()
    };
    SECRET
        .replace_all(&capped, |caps: &regex::Captures| {
            if let Some(prefix) = caps.get(1).or_else(|| caps.get(2)) {
                format!("{}[REDACTED]", prefix.as_str())
            } else {
                "[REDACTED]".to_string()
            }
        })
        .into_owned()
}

#[cfg(test)]
mod tests {
    use super::redact_line;

    #[test]
    fn redacts_keys_tokens_and_sk() {
        let line = redact_line("Authorization: Bearer abcdefghijklmnop api_key=supersecret sk-abcdefghij123");
        assert!(!line.contains("abcdefghijklmnop"));
        assert!(!line.contains("supersecret"));
        assert!(!line.contains("sk-abcdefghij123"));
        assert!(line.contains("[REDACTED]"));
    }

    #[test]
    fn leaves_ordinary_startup_lines() {
        let line = "Starting LEVIATHAN backend host v0.1.0";
        assert_eq!(redact_line(line), line);
    }
}
