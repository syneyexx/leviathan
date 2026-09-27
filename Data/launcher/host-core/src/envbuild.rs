use std::collections::HashMap;
use std::path::Path;

/// Process-local Safe Mode overrides.
///
/// These are not written to `.env`. They select the existing API-only bootstrap
/// (`LEVIATHAN_BOOTSTRAP_MODE=api`) and turn off outbound network, chaos,
/// module-manager subprocesses, native-binary spawn, and external domain runners.
/// Worker Fabric leases are not bypassed: Safe Mode simply does not start the
/// supervisor, so no second supervisor is created.
pub const SAFE_MODE_ENV: &[(&str, &str)] = &[
    ("LEVIATHAN_BOOTSTRAP_MODE", "api"),
    ("LEVIATHAN_NETWORK_ALLOW_OUTBOUND", "false"),
    ("LEVIATHAN_CHAOS_ENABLED", "false"),
    ("LEVIATHAN_FEATURE_MODULE_MANAGER_SUBPROCESS", "false"),
    ("LEVIATHAN_NATIVE_COMPUTE_DISABLED", "1"),
    ("LEVIATHAN_SOURCE_INGESTION_RUNNER", "none"),
    ("LEVIATHAN_DATASET_JOBS_RUNNER", "none"),
    ("LEVIATHAN_RESEARCH_RUNNER", "none"),
    ("LEVIATHAN_AGENTS_RUNNER", "none"),
    ("LEVIATHAN_MARKET_SIM_RUNNER", "none"),
    ("LEVIATHAN_WORKERS_AUTOSTART", "0"),
];

pub fn build_child_env(base: &HashMap<String, String>, root: &Path, safe_mode: bool) -> HashMap<String, String> {
    let mut env = base.clone();
    env.insert("PYTHONUNBUFFERED".into(), "1".into());
    let root_s = root.to_string_lossy().to_string();
    let mut parts: Vec<String> = vec![root_s.clone()];
    if let Some(existing) = env.get("PYTHONPATH") {
        for part in existing.split(':').chain(existing.split(';')) {
            if !part.is_empty() && part != root_s && !parts.iter().any(|item| item == part) {
                parts.push(part.to_string());
            }
        }
    }
    let sep = if cfg!(windows) { ";" } else { ":" };
    env.insert("PYTHONPATH".into(), parts.join(sep));
    if safe_mode {
        for (key, value) in SAFE_MODE_ENV {
            env.insert((*key).to_string(), (*value).to_string());
        }
    }
    env
}

#[cfg(test)]
mod tests {
    use super::{build_child_env, SAFE_MODE_ENV};
    use std::collections::HashMap;
    use std::path::Path;

    #[test]
    fn prepends_install_root_and_unbuffered() {
        let mut base = HashMap::new();
        base.insert("PYTHONPATH".into(), "/tmp/other".into());
        base.insert("LEVIATHAN_NETWORK_ALLOW_OUTBOUND".into(), "true".into());
        let env = build_child_env(&base, Path::new("/opt/leviathan"), false);
        assert_eq!(env.get("PYTHONUNBUFFERED").map(String::as_str), Some("1"));
        let pythonpath = env.get("PYTHONPATH").unwrap();
        assert!(pythonpath.starts_with("/opt/leviathan"));
        assert!(pythonpath.contains("/tmp/other"));
        assert_eq!(
            env.get("LEVIATHAN_NETWORK_ALLOW_OUTBOUND").map(String::as_str),
            Some("true")
        );
    }

    #[test]
    fn safe_mode_is_process_local_and_documented() {
        let env = build_child_env(&HashMap::new(), Path::new("/opt/leviathan"), true);
        for (key, value) in SAFE_MODE_ENV {
            assert_eq!(env.get(*key).map(String::as_str), Some(*value), "{key}");
        }
        assert_eq!(env.get("LEVIATHAN_BOOTSTRAP_MODE").map(String::as_str), Some("api"));
        assert!(SAFE_MODE_ENV.len() >= 8);
    }
}
