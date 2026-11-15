// Ouvre une adresse dans le navigateur, ou montre un fichier dans l'Explorateur / le Finder (application Tauri).
const inTauri = () => "__TAURI_INTERNALS__" in window;

export async function openExternal(url: string): Promise<void> {
  if (inTauri()) {
    const { openUrl } = await import("@tauri-apps/plugin-opener");
    await openUrl(url);
    return;
  }
  window.open(url, "_blank", "noopener");
}

/** Montre le fichier (ou le dossier) dans l'Explorateur Windows ou le Finder. */
export async function openPath(path: string): Promise<void> {
  if (inTauri()) {
    const { revealItemInDir } = await import("@tauri-apps/plugin-opener");
    await revealItemInDir(path);
    return;
  }
  await navigator.clipboard?.writeText(path).catch(() => undefined);
  window.alert(`Chemin copié : ${path}`);
}
