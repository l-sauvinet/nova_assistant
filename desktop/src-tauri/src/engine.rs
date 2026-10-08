//! Starts and stops NOVA's Python engine (`nova serve`) next to the window.

use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};

#[derive(Clone, serde::Serialize)]
pub struct ServerConfig {
    pub port: u16,
    pub token: String,
}

pub struct Engine {
    pub config: ServerConfig,
    child: Child,
}

impl Engine {
    /// `bundled` is the standalone engine shipped by the installer; without it (development), the engine
    /// runs from the Python project through `uv`.
    pub fn start(bundled: Option<PathBuf>) -> Result<Engine, String> {
        let config = ServerConfig {
            port: free_local_port()?,
            token: format!("{}{}", uuid::Uuid::new_v4().simple(), uuid::Uuid::new_v4().simple()),
        };
        let mut command = match bundled {
            Some(executable) => {
                // Settings (.env) are read from the working directory: keep them with NOVA's other user data.
                let data_dir = home_dir().join(".nova");
                std::fs::create_dir_all(&data_dir)
                    .map_err(|error| format!("Impossible de créer {} : {error}", data_dir.display()))?;
                let mut command = Command::new(executable);
                command.arg("serve").current_dir(data_dir);
                command
            }
            None => {
                let project_dir = project_dir();
                let mut command = Command::new(uv_executable());
                command.args(["run", "--project"]).arg(&project_dir).args(["nova", "serve"]).current_dir(&project_dir);
                command
            }
        };
        hide_console_window(&mut command);
        let child = command
            .env("NOVA_SERVER_PORT", config.port.to_string())
            .env("NOVA_SERVER_TOKEN", &config.token)
            .stdin(Stdio::null())
            .spawn()
            .map_err(|error| format!("Impossible de démarrer le moteur NOVA : {error}"))?;
        Ok(Engine { config, child })
    }

    pub fn stop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn free_local_port() -> Result<u16, String> {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|listener| listener.local_addr())
        .map(|address| address.port())
        .map_err(|error| format!("Aucun port local disponible : {error}"))
}

/// Folder holding NOVA's Python project (pyproject.toml, .env). In development: the repository root.
fn project_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("NOVA_PROJECT_DIR") {
        return PathBuf::from(dir);
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join("..")
}

fn home_dir() -> PathBuf {
    PathBuf::from(std::env::var("USERPROFILE").or_else(|_| std::env::var("HOME")).unwrap_or_default())
}

/// The engine is a console program: without this, Windows opens a terminal window next to NOVA's.
#[cfg(windows)]
fn hide_console_window(command: &mut Command) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    command.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
fn hide_console_window(_command: &mut Command) {}

fn uv_executable() -> PathBuf {
    if let Ok(path) = std::env::var("NOVA_UV") {
        return PathBuf::from(path);
    }
    let local = home_dir().join(".local").join("bin").join(if cfg!(windows) { "uv.exe" } else { "uv" });
    if local.exists() {
        local
    } else {
        PathBuf::from("uv")
    }
}
