use std::io::Read;
use std::net::TcpListener;
use std::time::Duration;

use reqwest::blocking::Client;
use serde::Serialize;
use serde_json::Value;

#[derive(Clone, Serialize)]
pub struct StartupStatus {
    pub phase: &'static str,
    pub code: Option<&'static str>,
    pub message: &'static str,
}

impl StartupStatus {
    pub fn starting() -> Self {
        Self { phase: "starting", code: None, message: "Opening your local workspace…" }
    }

    pub fn ready() -> Self {
        Self { phase: "ready", code: None, message: "Your workspace is ready." }
    }

    pub fn failed(code: &'static str, message: &'static str) -> Self {
        Self { phase: "failed", code: Some(code), message }
    }
}

pub fn port_available(port: u16) -> bool {
    TcpListener::bind(("127.0.0.1", port)).is_ok()
}

pub fn probe_client(timeout: Duration) -> reqwest::Result<Client> {
    Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(timeout)
        .build()
}

fn get_json(client: &Client, url: &str) -> Option<Value> {
    let response = client.get(url).send().ok()?;
    if !response.status().is_success() {
        return None;
    }
    // A service on the reserved port must not stream an unbounded response.
    let mut bytes = Vec::new();
    response.take(4097).read_to_end(&mut bytes).ok()?;
    if bytes.len() > 4096 {
        return None;
    }
    serde_json::from_slice(&bytes).ok()
}

pub fn api_ready(client: &Client, base_url: &str, version: &str, instance_id: &str) -> bool {
    let Some(runtime) = get_json(client, &format!("{base_url}/runtime")) else {
        return false;
    };
    if runtime["mode"] != "desktop"
        || runtime["app_version"] != version
        || runtime["desktop_instance_id"] != instance_id
    {
        return false;
    }
    get_json(client, &format!("{base_url}/health/ready"))
        .is_some_and(|health| health["status"] == "ready")
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};

    fn server(replies: Vec<(u16, String)>) -> (String, std::thread::JoinHandle<()>) {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        listener.set_nonblocking(true).unwrap();
        let thread = std::thread::spawn(move || {
            for (status, body) in replies {
                let deadline = std::time::Instant::now() + Duration::from_secs(3);
                let mut stream = loop {
                    match listener.accept() {
                        Ok((stream, _)) => break stream,
                        Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                            assert!(std::time::Instant::now() < deadline, "Probe did not connect");
                            std::thread::sleep(Duration::from_millis(10));
                        }
                        Err(error) => panic!("{error}"),
                    }
                };
                stream.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
                let mut request = [0; 2048];
                stream.read(&mut request).unwrap();
                write!(stream, "HTTP/1.1 {status} Test\r\nContent-Length: {}\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{body}", body.len()).unwrap();
            }
        });
        (url, thread)
    }

    fn runtime(version: &str, mode: &str, instance: &str) -> String {
        serde_json::json!({
            "app_version": version, "mode": mode, "desktop_instance_id": instance,
        }).to_string()
    }

    #[test]
    fn readiness_requires_this_instance_and_a_ready_database() {
        let (url, server) = server(vec![
            (200, runtime("0.2.0-rc.2", "desktop", "this-launch")),
            (200, r#"{"status":"ready"}"#.into()),
        ]);
        let client = probe_client(Duration::from_secs(1)).unwrap();
        assert!(api_ready(&client, &url, "0.2.0-rc.2", "this-launch"));
        server.join().unwrap();
    }

    #[test]
    fn rejects_other_services_versions_and_instances() {
        for body in [
            runtime("0.2.0-rc.2", "web", "this-launch"),
            runtime("0.1.0", "desktop", "this-launch"),
            runtime("0.2.0-rc.2", "desktop", "another-launch"),
            "{}".into(),
        ] {
            let (url, server) = server(vec![(200, body)]);
            let client = probe_client(Duration::from_secs(1)).unwrap();
            assert!(!api_ready(&client, &url, "0.2.0-rc.2", "this-launch"));
            server.join().unwrap();
        }
    }

    #[test]
    fn rejects_unready_or_failed_database_responses() {
        for (status, body) in [(200, r#"{"status":"starting"}"#), (503, r#"{"status":"ready"}"#)] {
            let (url, server) = server(vec![
                (200, runtime("0.2.0-rc.2", "desktop", "this-launch")),
                (status, body.into()),
            ]);
            let client = probe_client(Duration::from_secs(1)).unwrap();
            assert!(!api_ready(&client, &url, "0.2.0-rc.2", "this-launch"));
            server.join().unwrap();
        }
    }

    #[test]
    fn occupied_port_and_non_http_service_are_not_ready() {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        assert!(!port_available(port));
        let client = probe_client(Duration::from_millis(200)).unwrap();
        assert!(!api_ready(&client, &format!("http://127.0.0.1:{port}"), "v", "id"));
    }
}
