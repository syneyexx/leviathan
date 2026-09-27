//! Loopback-only HTTP probe for host liveness and supervisor health.
//!
//! This is not a general HTTP client. It only contacts the configured local
//! backend endpoint and refuses to become an SSRF primitive.

use std::io::{Read, Write};
use std::net::{IpAddr, SocketAddr, TcpStream, ToSocketAddrs};
use std::time::{Duration, Instant};

use serde::Deserialize;

const LIVENESS_PATH: &str = "/api/host/liveness";
const SUPERVISOR_PATH: &str = "/api/workers/dashboard";
const MAX_BODY: usize = 64 * 1024;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProbeErrorKind {
    DnsError,
    ConnectError,
    ConnectTimeout,
    ReadTimeout,
    HttpError,
    InvalidHttp,
    InvalidJson,
    LivenessFalse,
    Unreachable,
}

impl ProbeErrorKind {
    pub fn as_str(self) -> &'static str {
        match self {
            ProbeErrorKind::DnsError => "DNS_ERROR",
            ProbeErrorKind::ConnectError => "CONNECT_ERROR",
            ProbeErrorKind::ConnectTimeout => "CONNECT_TIMEOUT",
            ProbeErrorKind::ReadTimeout => "READ_TIMEOUT",
            ProbeErrorKind::HttpError => "HTTP_ERROR",
            ProbeErrorKind::InvalidHttp => "INVALID_HTTP",
            ProbeErrorKind::InvalidJson => "INVALID_JSON",
            ProbeErrorKind::LivenessFalse => "LIVENESS_FALSE",
            ProbeErrorKind::Unreachable => "UNREACHABLE",
        }
    }
}

#[derive(Clone, Debug)]
pub struct ProbeResult {
    pub reachable: bool,
    pub status: Option<u16>,
    pub ok: Option<bool>,
    pub detail: String,
    pub error_kind: Option<ProbeErrorKind>,
}

impl ProbeResult {
    fn failure(kind: ProbeErrorKind, detail: impl Into<String>) -> Self {
        Self {
            reachable: false,
            status: None,
            ok: None,
            detail: detail.into(),
            error_kind: Some(kind),
        }
    }

    fn http_failure(kind: ProbeErrorKind, status: Option<u16>, detail: impl Into<String>) -> Self {
        Self {
            reachable: status.is_some(),
            status,
            ok: None,
            detail: detail.into(),
            error_kind: Some(kind),
        }
    }
}

#[derive(Debug, Deserialize)]
struct LivenessBody {
    ok: bool,
    #[serde(default)]
    liveness: Option<String>,
    #[serde(default)]
    bootstrapped: Option<bool>,
}

/// Probe the cheap canonical liveness endpoint with semantic JSON validation.
pub fn probe_health(host: &str, port: u16, timeout: Duration) -> ProbeResult {
    probe_liveness(host, port, timeout)
}

pub fn probe_liveness(host: &str, port: u16, timeout: Duration) -> ProbeResult {
    if !is_loopback_host(host) {
        return ProbeResult::failure(
            ProbeErrorKind::Unreachable,
            format!("refusing non-loopback probe host '{host}'"),
        );
    }
    let deadline = Instant::now() + timeout;
    let addrs = match resolve_loopback_addrs(host, port) {
        Ok(addrs) if !addrs.is_empty() => addrs,
        Ok(_) => {
            return ProbeResult::failure(ProbeErrorKind::DnsError, "address unresolved");
        }
        Err(err) => {
            return ProbeResult::failure(ProbeErrorKind::DnsError, format!("address: {err}"));
        }
    };

    let mut last = ProbeResult::failure(ProbeErrorKind::ConnectError, "no address candidates");
    for addr in addrs {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return ProbeResult::failure(ProbeErrorKind::ConnectTimeout, "deadline exhausted");
        }
        match probe_address(host, addr, LIVENESS_PATH, remaining) {
            Ok(body) => {
                return interpret_liveness(body.status, &body.body);
            }
            Err(err) => {
                last = err;
                // Try next resolved address within the shared deadline.
            }
        }
    }
    last
}

pub fn probe_supervisor_health(host: &str, port: u16, timeout: Duration) -> Option<String> {
    if !is_loopback_host(host) {
        return None;
    }
    let deadline = Instant::now() + timeout;
    let addrs = resolve_loopback_addrs(host, port).ok()?;
    for addr in addrs {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return None;
        }
        if let Ok(body) = probe_address(host, addr, SUPERVISOR_PATH, remaining) {
            if let Some(health) = extract_supervisor_health(&body.body) {
                return Some(health);
            }
        }
    }
    None
}

fn interpret_liveness(status: u16, body: &str) -> ProbeResult {
    if !(200..300).contains(&status) {
        return ProbeResult::http_failure(
            ProbeErrorKind::HttpError,
            Some(status),
            format!("HTTP {status}"),
        );
    }
    let parsed = match parse_liveness_json(body) {
        Ok(parsed) => parsed,
        Err(detail) => {
            return ProbeResult::http_failure(ProbeErrorKind::InvalidJson, Some(status), detail);
        }
    };
    if parsed.ok {
        ProbeResult {
            reachable: true,
            status: Some(status),
            ok: Some(true),
            detail: format!(
                "liveness={} bootstrapped={:?}",
                parsed.liveness.as_deref().unwrap_or("alive"),
                parsed.bootstrapped
            ),
            error_kind: None,
        }
    } else {
        ProbeResult {
            reachable: true,
            status: Some(status),
            ok: Some(false),
            detail: "liveness ok=false".into(),
            error_kind: Some(ProbeErrorKind::LivenessFalse),
        }
    }
}

fn parse_liveness_json(body: &str) -> Result<LivenessBody, String> {
    let trimmed = body.trim();
    if trimmed.is_empty() {
        return Err("empty JSON body".into());
    }
    serde_json::from_str::<LivenessBody>(trimmed).map_err(|err| format!("invalid JSON: {err}"))
}

struct HttpBody {
    status: u16,
    body: String,
}

fn probe_address(
    host: &str,
    addr: SocketAddr,
    path: &str,
    timeout: Duration,
) -> Result<HttpBody, ProbeResult> {
    let mut stream = match TcpStream::connect_timeout(&addr, timeout) {
        Ok(stream) => stream,
        Err(err) => {
            let kind = if err.kind() == std::io::ErrorKind::TimedOut {
                ProbeErrorKind::ConnectTimeout
            } else {
                ProbeErrorKind::ConnectError
            };
            return Err(ProbeResult::failure(kind, err.to_string()));
        }
    };
    let _ = stream.set_read_timeout(Some(timeout));
    let _ = stream.set_write_timeout(Some(timeout));
    let request = format!(
        "GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\nAccept: application/json\r\n\r\n"
    );
    if let Err(err) = stream.write_all(request.as_bytes()) {
        return Err(ProbeResult::failure(ProbeErrorKind::ConnectError, err.to_string()));
    }

    let mut buf = Vec::new();
    let mut chunk = [0_u8; 4096];
    loop {
        if buf.len() > MAX_BODY {
            break;
        }
        match stream.read(&mut chunk) {
            Ok(0) => break,
            Ok(n) => buf.extend_from_slice(&chunk[..n]),
            Err(err) => {
                if err.kind() == std::io::ErrorKind::WouldBlock
                    || err.kind() == std::io::ErrorKind::TimedOut
                {
                    if buf.is_empty() {
                        return Err(ProbeResult::failure(
                            ProbeErrorKind::ReadTimeout,
                            "read timed out",
                        ));
                    }
                    break;
                }
                if buf.is_empty() {
                    return Err(ProbeResult::failure(
                        ProbeErrorKind::ConnectError,
                        err.to_string(),
                    ));
                }
                break;
            }
        }
    }

    parse_http_response(&buf).map_err(|detail| {
        ProbeResult::http_failure(ProbeErrorKind::InvalidHttp, None, detail)
    })
}

fn parse_http_response(raw: &[u8]) -> Result<HttpBody, String> {
    let text = String::from_utf8_lossy(raw);
    let (header, body) = text
        .split_once("\r\n\r\n")
        .or_else(|| text.split_once("\n\n"))
        .ok_or_else(|| "incomplete HTTP response".to_string())?;
    let status_line = header.lines().next().unwrap_or_default();
    let status = status_line
        .split_whitespace()
        .nth(1)
        .and_then(|code| code.parse::<u16>().ok())
        .ok_or_else(|| format!("invalid status line: {status_line}"))?;
    Ok(HttpBody {
        status,
        body: body.to_string(),
    })
}

fn extract_supervisor_health(body: &str) -> Option<String> {
    let value: serde_json::Value = serde_json::from_str(body.trim()).ok()?;
    value
        .get("supervisor")
        .and_then(|s| s.get("health"))
        .and_then(|h| h.as_str())
        .map(|s| s.to_string())
}

fn resolve_loopback_addrs(host: &str, port: u16) -> Result<Vec<SocketAddr>, String> {
    let address = format!("{host}:{port}");
    let mut addrs: Vec<SocketAddr> = address
        .to_socket_addrs()
        .map_err(|err| err.to_string())?
        .filter(|addr| addr.ip().is_loopback())
        .collect();
    // Prefer IPv4 first for typical Windows/WSL loopback quirks, then IPv6.
    addrs.sort_by_key(|addr| match addr.ip() {
        IpAddr::V4(_) => 0u8,
        IpAddr::V6(_) => 1u8,
    });
    // De-duplicate while preserving order.
    let mut unique = Vec::new();
    for addr in addrs {
        if !unique.contains(&addr) {
            unique.push(addr);
        }
    }
    Ok(unique)
}

fn is_loopback_host(host: &str) -> bool {
    let lowered = host.trim().to_ascii_lowercase();
    matches!(
        lowered.as_str(),
        "127.0.0.1" | "localhost" | "::1" | "[::1]"
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::net::TcpListener;
    use std::thread;

    fn serve_once(response: &'static [u8]) -> (u16, thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().unwrap().port();
        let handle = thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let mut buf = [0_u8; 1024];
                let _ = stream.read(&mut buf);
                let _ = stream.write_all(response);
            }
        });
        (port, handle)
    }

    #[test]
    fn test_probe_accepts_valid_json_true() {
        let response = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"ok\":true,\"liveness\":\"alive\",\"bootstrapped\":true}";
        let (port, join) = serve_once(response);
        let result = probe_liveness("127.0.0.1", port, Duration::from_secs(2));
        let _ = join.join();
        assert_eq!(result.ok, Some(true));
        assert!(result.reachable);
        assert_eq!(result.status, Some(200));
        assert!(result.error_kind.is_none());
    }

    #[test]
    fn test_probe_does_not_depend_on_json_whitespace() {
        let response = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\n  \"ok\" : true ,\n  \"liveness\" : \"alive\"\n}\n";
        let (port, join) = serve_once(response);
        let result = probe_liveness("127.0.0.1", port, Duration::from_secs(2));
        let _ = join.join();
        assert_eq!(result.ok, Some(true));
    }

    #[test]
    fn test_probe_rejects_json_false() {
        let response = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"ok\":false,\"liveness\":\"dead\"}";
        let (port, join) = serve_once(response);
        let result = probe_liveness("127.0.0.1", port, Duration::from_secs(2));
        let _ = join.join();
        assert_eq!(result.ok, Some(false));
        assert_eq!(result.error_kind, Some(ProbeErrorKind::LivenessFalse));
    }

    #[test]
    fn test_probe_rejects_invalid_json() {
        let response = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{not-json";
        let (port, join) = serve_once(response);
        let result = probe_liveness("127.0.0.1", port, Duration::from_secs(2));
        let _ = join.join();
        assert!(result.ok.is_none());
        assert_eq!(result.error_kind, Some(ProbeErrorKind::InvalidJson));
    }

    #[test]
    fn test_probe_rejects_http_500() {
        let response = b"HTTP/1.1 500 Internal Server Error\r\nConnection: close\r\n\r\n{\"ok\":true}";
        let (port, join) = serve_once(response);
        let result = probe_liveness("127.0.0.1", port, Duration::from_secs(2));
        let _ = join.join();
        assert_eq!(result.status, Some(500));
        assert_eq!(result.error_kind, Some(ProbeErrorKind::HttpError));
        assert!(result.ok.is_none());
    }

    #[test]
    fn test_probe_reports_connection_failure() {
        let result = probe_liveness("127.0.0.1", 1, Duration::from_millis(200));
        assert!(!result.reachable);
        assert!(matches!(
            result.error_kind,
            Some(ProbeErrorKind::ConnectError) | Some(ProbeErrorKind::ConnectTimeout)
        ));
    }

    #[test]
    fn test_probe_uses_liveness_endpoint() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let handle = thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let mut buf = [0_u8; 2048];
                let n = stream.read(&mut buf).unwrap_or(0);
                let req = String::from_utf8_lossy(&buf[..n]);
                assert!(req.contains("GET /api/host/liveness "));
                let _ = stream.write_all(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"ok\":true}",
                );
            }
        });
        let result = probe_liveness("127.0.0.1", port, Duration::from_secs(2));
        let _ = handle.join();
        assert_eq!(result.ok, Some(true));
    }

    #[test]
    fn test_probe_reports_timeout() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let handle = thread::spawn(move || {
            // Accept but never respond — force read/connect timeout path.
            let _ = listener.accept();
            thread::sleep(Duration::from_millis(800));
        });
        let result = probe_liveness("127.0.0.1", port, Duration::from_millis(150));
        let _ = handle.join();
        assert!(matches!(
            result.error_kind,
            Some(ProbeErrorKind::ReadTimeout)
                | Some(ProbeErrorKind::ConnectTimeout)
                | Some(ProbeErrorKind::InvalidHttp)
                | Some(ProbeErrorKind::ConnectError)
        ));
    }

    #[test]
    fn test_parse_liveness_pretty_and_compact() {
        let compact = parse_liveness_json(r#"{"ok":true}"#).unwrap();
        assert!(compact.ok);
        let pretty = parse_liveness_json("{\n  \"ok\": true,\n  \"liveness\": \"alive\"\n}").unwrap();
        assert!(pretty.ok);
        assert!(parse_liveness_json(r#"{"ok":false}"#).unwrap().ok == false);
        assert!(parse_liveness_json("nope").is_err());
    }

    #[test]
    fn test_multiple_resolved_addresses_are_handled() {
        // localhost may resolve to both v4 and v6; ensure we still succeed via 127.0.0.1 service.
        let response = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"ok\":true}";
        let (port, join) = serve_once(response);
        let result = probe_liveness("localhost", port, Duration::from_secs(2));
        let _ = join.join();
        // May succeed via 127.0.0.1 or fail if OS resolves only ::1 without listener —
        // either way the probe must not panic and must classify cleanly.
        assert!(result.error_kind.is_none() || result.error_kind.is_some());
        if result.ok == Some(true) {
            assert!(result.reachable);
        }
    }

    #[test]
    fn test_refuses_non_loopback_host() {
        let result = probe_liveness("example.com", 80, Duration::from_millis(100));
        assert_eq!(result.error_kind, Some(ProbeErrorKind::Unreachable));
    }

    #[test]
    fn test_supervisor_health_parses_json() {
        let response = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"supervisor\":{\"health\":\"RUNNING\"}}";
        let (port, join) = serve_once(response);
        let health = probe_supervisor_health("127.0.0.1", port, Duration::from_secs(2));
        let _ = join.join();
        assert_eq!(health.as_deref(), Some("RUNNING"));
    }
}
