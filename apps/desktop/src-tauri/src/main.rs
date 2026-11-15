// Empeche l'ouverture d'une console en plus de la fenetre sous Windows (build release).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // L'interface parle au backend FastAPI local (http://127.0.0.1:8787), lance a part.
    tauri::Builder::default()
        // Ouvre la connexion Google (chaine YouTube) dans le navigateur de l'utilisateur.
        .plugin(tauri_plugin_opener::init())
        .run(tauri::generate_context!())
        .expect("erreur au lancement de ShortForge");
}
