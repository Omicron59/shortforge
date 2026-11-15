// Projet ouvert dans l'interface (garde d'une session a l'autre).
import { create } from "zustand";

const KEY = "shortforge.currentProject";

function load(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

interface ProjectStore {
  currentId: string | null;
  setCurrent: (id: string | null) => void;
}

export const useProjectStore = create<ProjectStore>((set) => ({
  currentId: load(),
  setCurrent: (id) => {
    try {
      if (id) localStorage.setItem(KEY, id);
      else localStorage.removeItem(KEY);
    } catch {
      /* stockage indisponible : le choix reste en memoire */
    }
    set({ currentId: id });
  },
}));
