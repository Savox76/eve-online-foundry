//! Die Anwendungsschale.
//!
//! Ihre Aufgabe ist klein und genau umrissen: den Backend-Sidecar starten, ihm
//! ein frisches Sitzungsgeheimnis mitgeben, warten bis er antwortet, das
//! Fenster zeigen -- und ihn beim Beenden zuverlaessig mitnehmen.
//!
//! Warum das Geheimnis hier entsteht und nicht im Backend: ein Server auf
//! `127.0.0.1` ist fuer jeden Prozess auf dem Rechner erreichbar. Das
//! Geheimnis erzeugt der Elternprozess einmal je Start, reicht es dem Sidecar
//! ueber die Umgebung durch und dem Fenster ueber eine Initialisierung. Damit
//! kennen es genau zwei Beteiligte, und es ueberlebt keinen Neustart.

use std::sync::Mutex;

use base64::Engine as _;
use rand::RngCore;
use tauri::{Emitter, Manager, RunEvent, WindowEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Haelt den laufenden Sidecar, damit er beim Beenden gezielt gestoppt werden
/// kann. Ohne das bleibt bei einem harten Fensterschluss ein verwaister
/// Python-Prozess auf der Datenbank sitzen -- und der naechste Start scheitert
/// dann an der Instanzsperre, ohne dass jemand versteht warum.
#[derive(Default)]
struct Sidecar(Mutex<Option<CommandChild>>);

/// Das Sitzungsgeheimnis dieses Laufs.
struct SessionSecret(String);

fn generate_secret() -> String {
    let mut bytes = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut bytes);
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(bytes)
}

/// Das Fenster holt sich hierueber das Geheimnis, das es in jeden Request legt.
#[tauri::command]
fn session_secret(state: tauri::State<'_, SessionSecret>) -> String {
    state.0.clone()
}

/// Startet das gebuendelte Backend als Sidecar.
///
/// Die Binaerdatei traegt im Namen das Rust-Target-Triple -- ohne das findet
/// Tauri sie nicht. `scripts/build_sidecar.py` benennt sie entsprechend.
fn spawn_backend(app: &tauri::AppHandle, secret: &str) -> Result<CommandChild, String> {
    let (mut rx, child) = app
        .shell()
        .sidecar("foundry-backend")
        .map_err(|e| format!("Sidecar nicht gefunden: {e}"))?
        .env("FOUNDRY_SESSION_SECRET", secret)
        .env("FOUNDRY_HOST", "127.0.0.1")
        .env("FOUNDRY_PORT", "8000")
        .spawn()
        .map_err(|e| format!("Sidecar liess sich nicht starten: {e}"))?;

    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                // Die Ausgabe des Backends landet im Log der Schale. Bei einem
                // Startfehler -- fehlgeschlagene Migration, zweite Instanz --
                // steht die Begruendung sonst nirgends, wo jemand sie findet.
                CommandEvent::Stderr(line) => {
                    log::warn!("[backend] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Stdout(line) => {
                    log::info!("[backend] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Terminated(payload) => {
                    log::error!("Backend beendet: {payload:?}");
                    let _ = handle.emit("backend-terminated", payload.code);
                }
                _ => {}
            }
        }
    });

    Ok(child)
}

pub fn run() {
    let secret = generate_secret();

    tauri::Builder::default()
        // Zwei Instanzen wuerden um dieselbe SQLite-Datei streiten. Das Backend
        // sichert sich zusaetzlich mit einer Dateisperre ab; hier faengt es die
        // Schale schon vorher ab und holt stattdessen das offene Fenster nach
        // vorn -- was der Nutzer ohnehin will.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        // Der Systembrowser fuer den SSO-Login (Phase 1). Ein eingebettetes
        // Login-Formular waere von Phishing nicht zu unterscheiden -- der
        // Nutzer soll die echte Adresszeile von CCP sehen.
        .plugin(tauri_plugin_opener::init())
        .manage(Sidecar::default())
        .manage(SessionSecret(secret.clone()))
        .invoke_handler(tauri::generate_handler![session_secret])
        .setup(move |app| {
            let handle = app.handle().clone();
            match spawn_backend(&handle, &secret) {
                Ok(child) => {
                    *handle.state::<Sidecar>().0.lock().unwrap() = Some(child);
                }
                Err(message) => {
                    // Im Entwicklungsbetrieb laeuft das Backend von Hand; dann
                    // gibt es keinen Sidecar und das ist in Ordnung.
                    log::warn!("{message}");
                }
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::Destroyed = event {
                stop_backend(window.app_handle());
            }
        })
        .build(tauri::generate_context!())
        .expect("Anwendung liess sich nicht aufbauen")
        .run(|handle, event| {
            if let RunEvent::ExitRequested { .. } | RunEvent::Exit = event {
                stop_backend(handle);
            }
        });
}

fn stop_backend(handle: &tauri::AppHandle) {
    if let Some(state) = handle.try_state::<Sidecar>() {
        if let Ok(mut guard) = state.0.lock() {
            if let Some(child) = guard.take() {
                let _ = child.kill();
            }
        }
    }
}
