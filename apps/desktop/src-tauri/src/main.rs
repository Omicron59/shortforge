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

/// Jeton de session de l'API locale : cree a chaque lancement, connu seulement de la fenetre et du moteur.
struct ApiToken(String);

/// Jeton aleatoire sans dependance : SipHash avec les cles aleatoires que le systeme donne au processus.
fn new_token() -> String {
    use std::collections::hash_map::RandomState;
    use std::hash::{BuildHasher, Hasher};
    let mut out = String::new();
    for round in 0..4u64 {
        let mut hasher = RandomState::new().build_hasher();
        hasher.write_u64(round);
        hasher.write_u128(std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0));
        hasher.write_u32(std::process::id());
        out.push_str(&format!("{:016x}", hasher.finish()));
    }
    out
}

/// Donne le jeton a l'interface (vide si le moteur n'a pas ete lance par l'application : developpement).
#[tauri::command]
fn api_token(token: tauri::State<ApiToken>) -> String {
    token.0.clone()
}

fn backend_executable(app: &tauri::AppHandle) -> Option<PathBuf> {
    let name = if cfg!(windows) { "shortforge-backend.exe" } else { "shortforge-backend" };
    let path = app.path().resource_dir().ok()?.join("backend").join(name);
    path.is_file().then_some(path)
}

fn start_backend(app: &tauri::AppHandle, token: &str) -> Option<Child> {
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
        .env("SHORTFORGE_PORT", "8787")
        .env("SHORTFORGE_API_TOKEN", token);

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
        .invoke_handler(tauri::generate_handler![api_token])
        .setup(|app| {
            let token = new_token();
            let child = start_backend(app.handle(), &token);
            // Sans moteur lance ici (developpement), pas de jeton : le backend lance a la main n'en attend pas.
            app.manage(ApiToken(if child.is_some() { token } else { String::new() }));
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
