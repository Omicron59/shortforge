// Hooks React Query : lecture des donnees, actions et suivi en direct du pipeline.
import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, eventsUrl } from "./client";
import type { ProjectDetail } from "./types";
import { useToasts } from "../stores/toasts";

export const keys = {
  project: (id: string) => ["project", id] as const,
  projects: ["projects"] as const,
};

/** Projet + etapes, mis a jour en direct par le WebSocket du backend. */
export function useProject(id: string | null) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: keys.project(id ?? "none"),
    queryFn: () => api.project(id!),
    enabled: !!id,
  });

  useEffect(() => {
    if (!id) return;
    let socket: WebSocket | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let previous = "";

    const connect = () => {
      socket = new WebSocket(eventsUrl(id));
      socket.onmessage = (event) => {
        const data = JSON.parse(String(event.data)) as ProjectDetail & { error?: string };
        if (data.error) return;
        client.setQueryData(keys.project(id), data);
        // Une etape a change : les donnees qui en dependent sont rechargees.
        const signature = data.steps.map((s) => `${s.name}:${s.status}`).join(",");
        if (previous && signature !== previous) {
          for (const key of ["ideas", "script", "scenes", "assets", "jobs", "estimate", "history", "budget", "stats", "render", "draft", "final-check", "subtitles"]) {
            void client.invalidateQueries({ queryKey: [key] });
          }
          void client.invalidateQueries({ queryKey: keys.projects });
        }
        previous = signature;
      };
      socket.onclose = () => {
        if (!closed) retry = setTimeout(connect, 3000);
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      socket?.close();
    };
  }, [id, client]);

  return query;
}

/** Action vers le backend : message d'erreur en francais et rechargement des donnees. */
export function useAction<TArgs, TResult>(fn: (args: TArgs) => Promise<TResult>, success?: string) {
  const client = useQueryClient();
  const push = useToasts((s) => s.push);
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      if (success) push(success, "success");
      void client.invalidateQueries();
    },
    onError: (error: Error) => push(error.message, "error"),
  });
}
