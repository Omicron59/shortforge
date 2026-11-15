// Ouvre une adresse dans le navigateur de l'utilisateur (Tauri) ou un nouvel onglet (navigateur).
export async function openExternal(url: string): Promise<void> {
  if ("__TAURI_INTERNALS__" in window) {
    const { openUrl } = await import("@tauri-apps/plugin-opener");
    await openUrl(url);
    return;
  }
  window.open(url, "_blank", "noopener");
}
