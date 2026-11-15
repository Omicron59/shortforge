// Empeche l'ouverture d'une console en plus de la fenetre sous Windows (build release).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! ShortForge : la fenetre (interface React) et le moteur local (backend Python empaquete).
//!
//! Dans l'application installee, le moteur est livre dans les ressources (`backend/`). Il est lance
//! au demarrage avec un dossier de donnees et un fichier de reglages propres a l'utilisateur, puis
//! arrete a la fermeture. En developpement, s'il est absent, on lance le backend a la main.

use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::{Manager, RunEvent};

struct Backend(Mutex<Option<Child>>);

fn backend_executable(app: &tauri::AppHandle) -> Option<PathBuf> {
    let name = if cfg!(windows) { "shortforge-backend.exe" } else { "shortforge-backend" };
    let path = app.path().resource_dir().ok()?.join("backend").join(name);
    path.is_file().then_some(path)
}

fn start_backend(app: &tauri::AppHandle) -> Option<Child> {
    let exe = backend_executable(app)?;
    let data_dir = app.path().app_data_dir().ok()?;
    let config_dir = app.path().app_config_dir().ok()?;
    let _ = std::fs::create_dir_all(&data_dir);
    let _ = std::fs::create_dir_all(&config_dir);

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&exe, std::fs::Permissions::from_mode(0o755));
    }

    let mut command = Command::new(&exe);
    command
        .current_dir(&data_dir)
        .env("SHORTFORGE_DATA_DIR", &data_dir)
        .env("SHORTFORGE_ENV_FILE", config_dir.join("reglages.env"))
        .env("SHORTFORGE_HOST", "127.0.0.1")
        .env("SHORTFORGE_PORT", "8787");

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    match command.spawn() {
        Ok(child) => Some(child),
        Err(err) => {
            eprintln!("Moteur local non lancé : {err}");
            None
        }
    }
}

fn main() {
    let app = tauri::Builder::default()
        // Ouvre la connexion Google dans le navigateur et montre les fichiers dans leur dossier.
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let child = start_backend(app.handle());
            app.manage(Backend(Mutex::new(child)));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("erreur au lancement de ShortForge");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(state) = handle.try_state::<Backend>() {
                if let Ok(mut guard) = state.0.lock() {
                    if let Some(mut child) = guard.take() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        }
    });
}
