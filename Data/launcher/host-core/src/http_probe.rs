use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::time::Duration;

#[derive(Clone, Debug)]
pub struct ProbeResult {
    pub reachable: bool,
    pub status: Option<u16>,
    pub ok: Option<bool>,
    pub detail: String,
}

pub fn probe_health(host: &str, port: u16, timeout: Duration) -> ProbeResult {
    let address = format!("{host}:{port}");
    let mut iter = match address.to_socket_addrs() {
        Ok(iter) => iter,
        Err(err) => {
            return ProbeResult {
                reachable: false,
                status: None,
                ok: None,
                detail: format!("address: {err}"),
            };
        }
    };
    let Some(sockaddr) = iter.next() else {
        return ProbeResult {
            reachable: false,
            status: None,
            ok: None,
            detail: "address unresolved".into(),
        };
    };
    let mut stream = match TcpStream::connect_timeout(&sockaddr, timeout) {
        Ok(stream) => stream,
        Err(err) => {
            return ProbeResult {
                reachable: false,
                status: None,
                ok: None,
                detail: err.to_string(),
            };
        }
    };
    let _ = stream.set_read_timeout(Some(timeout));
    let _ = stream.set_write_timeout(Some(timeout));
    let request = format!(
        "GET /api/health HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\nAccept: application/json\r\n\r\n"
    );
    if let Err(err) = stream.write_all(request.as_bytes()) {
        return ProbeResult {
            reachable: false,
            status: None,
            ok: None,
            detail: err.to_string(),
        };
    }
    let mut buf = Vec::new();
    let mut chunk = [0_u8; 4096];
    loop {
        if buf.len() > 256 * 1024 {
            break;
        }
        match stream.read(&mut chunk) {
            Ok(0) => break,
            Ok(n) => buf.extend_from_slice(&chunk[..n]),
            Err(_) => break,
        }
    }
    let text = String::from_utf8_lossy(&buf);
    let status = text
        .split_whitespace()
        .nth(1)
        .and_then(|code| code.parse::<u16>().ok());
    let ok = if text.contains("\"ok\": true") || text.contains("\"ok\":true") {
        Some(true)
    } else if text.contains("\"ok\": false") || text.contains("\"ok\":false") {
        Some(false)
    } else {
        None
    };
    ProbeResult {
        reachable: status.is_some(),
        status,
        ok,
        detail: format!("status={status:?} ok={ok:?}"),
    }
}

pub fn probe_supervisor_health(host: &str, port: u16, timeout: Duration) -> Option<String> {
    let address = format!("{host}:{port}");
    let sockaddr = address.to_socket_addrs().ok()?.next()?;
    let mut stream = TcpStream::connect_timeout(&sockaddr, timeout).ok()?;
    let _ = stream.set_read_timeout(Some(timeout));
    let request = format!(
        "GET /api/workers/dashboard HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\nAccept: application/json\r\n\r\n"
    );
    stream.write_all(request.as_bytes()).ok()?;
    let mut buf = Vec::new();
    let mut chunk = [0_u8; 8192];
    loop {
        if buf.len() > 512 * 1024 {
            break;
        }
        match stream.read(&mut chunk) {
            Ok(0) => break,
            Ok(n) => buf.extend_from_slice(&chunk[..n]),
            Err(_) => break,
        }
    }
    let text = String::from_utf8_lossy(&buf);
    let marker = "\"health\":";
    let idx = text.find(marker)?;
    let rest = text[idx + marker.len()..].trim_start();
    let rest = rest.trim_start_matches('"');
    let end = rest.find('"')?;
    Some(rest[..end].trim().to_string())
}
