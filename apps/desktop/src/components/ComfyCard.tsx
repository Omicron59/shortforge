// ComfyUI : detection automatique du port, adresse modifiable, choix du modele d'image, bouton Tester.
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAction } from "../api/hooks";
import { Alert, Button, Card, Field, inputClass } from "./ui";

export function ComfyCard() {
  const check = useQuery({ queryKey: ["comfy-check"], queryFn: api.comfyCheck });
  const [url, setUrl] = useState("");
  const save = useAction((body: { url?: string; checkpoint?: string }) => api.setComfy(body), "Réglage ComfyUI enregistré.");
  const c = check.data;
  useEffect(() => { if (c) setUrl(c.url); }, [c?.url]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Card title="ComfyUI (images et vidéos locales)"
      actions={<Button className="text-xs" busy={check.isFetching} onClick={() => void check.refetch()}>Tester</Button>}>
      {c && <Alert tone={c.ready ? "green" : c.running ? "yellow" : "red"}>{c.message}{c.switched ? ` Trouvé sur ${c.url}.` : ""}</Alert>}
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <Field label="Adresse de ComfyUI" hint="ShortForge essaie tout seul 8000 (Comfy Desktop) puis 8188. Change-la seulement si ComfyUI utilise un autre port.">
          <div className="flex gap-2">
            <input className={inputClass} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://127.0.0.1:8000" />
            <Button onClick={() => save.mutate({ url }, { onSuccess: () => void check.refetch() })}>Enregistrer</Button>
          </div>
        </Field>
        <Field label="Modèle d'image" hint={c?.checkpoints.length ? "Modèles trouvés dans ComfyUI." : "Aucun modèle trouvé pour l'instant."}>
          <select className={inputClass} value={c?.chosen_checkpoint ?? ""} disabled={!c?.checkpoints.length}
            onChange={(e) => save.mutate({ checkpoint: e.target.value }, { onSuccess: () => void check.refetch() })}>
            <option value="">Celui du workflow ({c?.expected_checkpoint || "aucun"})</option>
            {c?.checkpoints.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
        </Field>
      </div>
    </Card>
  );
}
