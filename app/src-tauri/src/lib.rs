//! Eternal Silver Asset Viewer's shell: a window, and the backend it talks to.
//!
//! Nothing is decoded here. The UI (`../src`) calls the Python backend
//! directly over HTTP; this crate only decides WHICH library folder that
//! backend serves, starts it (`backend.rs`), and tells the UI where it
//! listens.

mod backend;

use std::path::{Path, PathBuf};
use std::sync::Arc;

use backend::{Backend, State};
use serde::{Deserialize, Serialize};
use tauri::{Manager, RunEvent};

/// The library folder chosen in the app, remembered in its config directory.
#[derive(Serialize, Deserialize, Default)]
struct Settings {
    library: Option<PathBuf>,
}

fn settings_path(app: &tauri::AppHandle) -> Option<PathBuf> {
    app.path()
        .app_config_dir()
        .ok()
        .map(|d| d.join("settings.json"))
}

fn load_settings(app: &tauri::AppHandle) -> Settings {
    settings_path(app)
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_default()
}

fn save_settings(app: &tauri::AppHandle, s: &Settings) -> Result<(), String> {
    let path = settings_path(app).ok_or("no config directory")?;
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    std::fs::write(
        path,
        serde_json::to_string_pretty(s).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())
}

/// Which library to serve: ASSET_VIEWER_LIBRARY if set, then the folder
/// chosen before. None leaves it to the backend's default folder.
fn initial_library(app: &tauri::AppHandle) -> Option<PathBuf> {
    if let Some(dir) = std::env::var_os("ASSET_VIEWER_LIBRARY").filter(|v| !v.is_empty()) {
        return Some(PathBuf::from(dir));
    }
    load_settings(app).library
}

#[tauri::command]
fn backend_state(state: tauri::State<'_, Arc<Backend>>) -> State {
    state.state()
}

/// Serve another library folder (None: back to the default one).
#[tauri::command]
fn set_library(
    path: Option<String>,
    app: tauri::AppHandle,
    state: tauri::State<'_, Arc<Backend>>,
) -> Result<(), String> {
    let library = match path {
        Some(path) => {
            let dir = PathBuf::from(&path);
            if !dir.is_dir() {
                return Err(format!("not a folder: {path}"));
            }
            Some(absolute(&dir).map_err(|e| e.to_string())?)
        }
        None => None,
    };
    save_settings(
        &app,
        &Settings {
            library: library.clone(),
        },
    )?;
    state.inner().start(library);
    Ok(())
}

/// `dir` absolute, its links resolved. Windows answers that as a verbatim
/// path (`\\?\C:\…`), which the backend would pass on to the person reading
/// it; a drive's path is written plainly.
fn absolute(dir: &Path) -> std::io::Result<PathBuf> {
    let path = dir.canonicalize()?;
    #[cfg(windows)]
    if let Some(rest) = path.to_str().and_then(|p| p.strip_prefix(r"\\?\"))
        && rest.as_bytes().get(1) == Some(&b':')
    {
        return Ok(PathBuf::from(rest));
    }
    Ok(path)
}

#[tauri::command]
fn restart_backend(app: tauri::AppHandle, state: tauri::State<'_, Arc<Backend>>) {
    state.inner().start(initial_library(&app));
}

pub fn run() {
    let backend = Arc::new(Backend::default());
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(backend.clone())
        .setup(|app| {
            let handle = app.handle().clone();
            let backend = app.state::<Arc<Backend>>().inner().clone();
            backend.start(initial_library(&handle));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend_state,
            set_library,
            restart_backend
        ])
        .build(tauri::generate_context!())
        .expect("error while building the app");

    app.run(move |_, event| {
        if let RunEvent::Exit = event {
            backend.stop();
        }
    });
}
