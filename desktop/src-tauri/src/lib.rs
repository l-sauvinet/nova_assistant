mod engine;

use std::sync::Mutex;

use engine::{Engine, ServerConfig};
use tauri::{Manager, RunEvent, State};

struct EngineState(Mutex<Option<Engine>>);

#[tauri::command]
fn server_config(state: State<'_, EngineState>) -> Result<ServerConfig, String> {
    state
        .0
        .lock()
        .map_err(|_| "État du moteur indisponible".to_string())?
        .as_ref()
        .map(|engine| engine.config.clone())
        .ok_or_else(|| "Le moteur NOVA n'a pas démarré.".to_string())
}

/// The standalone engine the installer ships under `resources/engine/` (see `tauri.bundle.conf.json`).
/// Debug builds always run the Python project directly, so `tauri dev` needs no engine build.
fn bundled_engine(app: &tauri::App) -> Option<std::path::PathBuf> {
    if cfg!(debug_assertions) {
        return None;
    }
    let name = if cfg!(windows) { "nova-engine.exe" } else { "nova-engine" };
    let executable = app.path().resource_dir().ok()?.join("engine").join(name);
    executable.exists().then_some(executable)
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let engine = Engine::start(bundled_engine(app))?;
            app.manage(EngineState(Mutex::new(Some(engine))));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![server_config])
        .build(tauri::generate_context!())
        .expect("failed to build NOVA");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(state) = handle.try_state::<EngineState>() {
                if let Ok(mut engine) = state.0.lock() {
                    if let Some(engine) = engine.as_mut() {
                        engine.stop();
                    }
                }
            }
        }
    });
}
