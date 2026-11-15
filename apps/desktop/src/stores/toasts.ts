// Messages temporaires affiches en bas de l'ecran (succes ou erreur).
import { create } from "zustand";

export interface Toast {
  id: number;
  message: string;
  kind: "success" | "error";
}

interface ToastStore {
  toasts: Toast[];
  push: (message: string, kind?: Toast["kind"]) => void;
  dismiss: (id: number) => void;
}

let next = 1;

export const useToasts = create<ToastStore>((set) => ({
  toasts: [],
  push: (message, kind = "success") => {
    const id = next++;
    set((s) => ({ toasts: [...s.toasts, { id, message, kind }] }));
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), kind === "error" ? 8000 : 3500);
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));
