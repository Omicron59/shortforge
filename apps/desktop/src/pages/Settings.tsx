// Parametres : budget, moteurs video, regles de choix, tendances manuelles et workflows ComfyUI.
// Les cles API ne se saisissent jamais ici : elles restent dans le fichier .env local.
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAction } from "../api/hooks";
import type { Budget, Importance, Provider } from "../api/types";
import { Alert, Badge, Button, Card, Field, Loading, PageHeader, inputClass } from "../components/ui";
import { IMPORTANCE_LABELS } from "../lib/format";
import { openExternal } from "../lib/open";

export default function Settings() {
  return (
    <>
      <PageHeader title="Paramètres" subtitle="Budget, moteurs vidéo et sources d'inspiration." />
      <div className="space-y-6">
        <BudgetSettings />
        <ProviderSettings />
        <EngineRules />
        <TrendsAndWorkflows />
        <YouTubeSettings />
        <Alert tone="blue" title="Clés API et publication">
          Les clés API (Gemini, MiniMax, Kling, Runway, YouTube…) se renseignent uniquement dans le fichier .env, jamais dans l'application.
          Redémarre le backend après une modification. La publication YouTube reste désactivée tant que YOUTUBE_PUBLISH_ENABLED=false.
        </Alert>
      </div>
    </>
  );
}

const LIMITS = [
  ["budget_max_per_scene", "Par scène"],
  ["budget_max_per_short", "Par Short"],
  ["budget_max_per_day", "Par jour"],
  ["budget_max_per_month", "Par mois"],
] as const;
type LimitKey = (typeof LIMITS)[number][0];

function BudgetSettings() {
  const budget = useQuery({ queryKey: ["budget"], queryFn: api.budget });
  const [values, setValues] = useState<Partial<Record<LimitKey, string>>>({});
  const save = useAction((body: Partial<Budget>) => api.setBudget(body), "Plafonds enregistrés.");
  useEffect(() => {
    if (budget.data) setValues(Object.fromEntries(LIMITS.map(([k]) => [k, String(budget.data[k])])));
  }, [budget.data]);
  if (!budget.data) return <Loading />;

  const parsed = Object.fromEntries(LIMITS.map(([k]) => [k, Number(String(values[k] ?? "").replace(",", "."))])) as Record<LimitKey, number>;
  const invalid = Object.values(parsed).some((v) => Number.isNaN(v) || v < 0);

  return (
    <Card title="Budget (dollars)">
      <div className="grid gap-4 md:grid-cols-4">
        {LIMITS.map(([key, label]) => (
          <Field key={key} label={label}>
            <input className={inputClass} inputMode="decimal" value={values[key] ?? ""} onChange={(e) => setValues({ ...values, [key]: e.target.value })} />
          </Field>
        ))}
      </div>
      <p className="mt-3 text-xs text-zinc-500">Une dépense qui dépasse un plafond est refusée : la scène passe alors en ComfyUI local. Chaque dépense demande ta confirmation.</p>
      <Button className="mt-3" variant="primary" disabled={invalid} busy={save.isPending} onClick={() => save.mutate(parsed)}>Enregistrer les plafonds</Button>
    </Card>
  );
}

function ProviderSettings() {
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers });
  return (
    <Card title="Moteurs vidéo">
      {providers.data ? (
        <div className="divide-y divide-zinc-800">
          {providers.data.map((p) => <ProviderRow key={p.id} provider={p} />)}
        </div>
      ) : (
        <Loading />
      )}
    </Card>
  );
}

function ProviderRow({ provider }: { provider: Provider }) {
  const [cost, setCost] = useState(provider.cost_per_second_usd?.toString() ?? "");
  const [model, setModel] = useState(provider.config.model ?? "");
  const patch = useAction((body: Parameters<typeof api.patchProvider>[1]) => api.patchProvider(provider.id, body), `${provider.name} mis à jour.`);
  const costValue = Number(cost.replace(",", "."));
  const changed = cost !== (provider.cost_per_second_usd?.toString() ?? "") || model !== (provider.config.model ?? "");

  return (
    <div className="flex flex-wrap items-end gap-4 py-3">
      <div className="min-w-[220px] flex-1">
        <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
          {provider.name}
          <Badge tone={provider.kind === "local" ? "green" : "blue"}>{provider.kind === "local" ? "local" : "externe"}</Badge>
          {provider.tier === "premium" && <Badge tone="yellow">premium</Badge>}
          {provider.is_default && <Badge tone="violet">par défaut</Badge>}
          <Badge tone={provider.configured ? "green" : "red"}>{provider.configured ? "configuré" : "non configuré"}</Badge>
        </p>
        {!provider.configured && provider.configuration_hint && <p className="mt-1 text-xs text-zinc-500">{provider.configuration_hint}</p>}
      </div>
      {provider.kind === "external" && (
        <>
          <Field label="Tarif ($ / seconde)">
            <input className={`${inputClass} w-28`} inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} placeholder="inconnu" />
          </Field>
          <Field label="Modèle">
            <input className={`${inputClass} w-48`} value={model} onChange={(e) => setModel(e.target.value)} placeholder="par défaut" />
          </Field>
          <Button disabled={!changed || (cost !== "" && (Number.isNaN(costValue) || costValue < 0))}
            onClick={() => patch.mutate({ ...(cost !== "" ? { cost_per_second_usd: costValue } : {}), config: { ...provider.config, model } })}>
            Enregistrer
          </Button>
        </>
      )}
      {provider.id !== "comfyui_local" && (
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={provider.enabled} onChange={(e) => patch.mutate({ enabled: e.target.checked })} />
          Activé
        </label>
      )}
    </div>
  );
}

function EngineRules() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers });
  const [rules, setRules] = useState<Record<string, string>>({});
  const save = useAction((r: Record<string, string>) => api.updateSettings({ engine_rules: r as Record<Importance, string> }), "Règles enregistrées.");
  useEffect(() => {
    if (settings.data) setRules(settings.data.engine_rules);
  }, [settings.data]);
  if (!settings.data) return null;

  return (
    <Card title="Règles du mode « Personnalisé »">
      <p className="mb-3 text-xs text-zinc-500">Moteur utilisé pour chaque type de scène quand un projet est en mode Personnalisé.</p>
      <div className="grid gap-4 md:grid-cols-4">
        {(Object.keys(IMPORTANCE_LABELS) as Importance[]).map((importance) => (
          <Field key={importance} label={`Scène ${IMPORTANCE_LABELS[importance].toLowerCase()}`}>
            <select className={inputClass} value={rules[importance] ?? ""} onChange={(e) => setRules({ ...rules, [importance]: e.target.value })}>
              {providers.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </Field>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="primary" busy={save.isPending} onClick={() => save.mutate(rules)}>Enregistrer</Button>
        {Object.entries(settings.data.preset_rules).map(([name, preset]) => (
          <Button key={name} variant="ghost" onClick={() => setRules(preset)}>Partir du mode {name}</Button>
        ))}
      </div>
    </Card>
  );
}

function TrendsAndWorkflows() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const workflows = useQuery({ queryKey: ["workflows"], queryFn: api.workflows });
  const [trends, setTrends] = useState("");
  const [wfId, setWfId] = useState("");
  const [wfKind, setWfKind] = useState<"image" | "video">("video");
  const [wfJson, setWfJson] = useState("");
  const saveTrends = useAction((list: string[]) => api.updateSettings({ manual_trends: list }), "Tendances enregistrées.");
  const saveWorkflow = useAction((id: string) => api.updateSettings({ comfyui_image_workflow: id }), "Workflow d'image choisi.");
  const addWorkflow = useAction(async () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(wfJson);
    } catch {
      throw new Error("Ce fichier n'est pas du JSON valide.");
    }
    return api.addWorkflow({ id: wfId.trim(), name: wfId.trim(), kind: wfKind, workflow: parsed as Record<string, unknown> });
  }, "Workflow ajouté.");
  useEffect(() => {
    if (settings.data) setTrends(settings.data.manual_trends.join("\n"));
  }, [settings.data]);

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Tendances saisies à la main">
        <Field label="Une tendance par ligne" hint="Ajoutées à Google Trends et YouTube comme sources d'inspiration (jamais recopiées).">
          <textarea className={inputClass} rows={8} value={trends} onChange={(e) => setTrends(e.target.value)} />
        </Field>
        <Button className="mt-3" variant="primary" busy={saveTrends.isPending} onClick={() => saveTrends.mutate(trends.split("\n"))}>Enregistrer</Button>
      </Card>

      <Card title="Workflows ComfyUI">
        {settings.data && workflows.data && (
          <Field label="Workflow utilisé pour les images">
            <select className={inputClass} value={settings.data.comfyui_image_workflow} onChange={(e) => saveWorkflow.mutate(e.target.value)}>
              {workflows.data.filter((w) => w.kind === "image").map((w) => <option key={w.id} value={w.id}>{w.name || w.id}</option>)}
            </select>
          </Field>
        )}
        <ul className="my-3 space-y-1 text-sm">
          {workflows.data?.map((w) => (
            <li key={w.id} className="flex items-center gap-2">
              <Badge tone={w.kind === "video" ? "blue" : "violet"}>{w.kind === "video" ? "vidéo" : "image"}</Badge>
              <span>{w.id}</span>
              {w.user && <Badge>ajouté</Badge>}
              <span className="text-xs text-zinc-500">entrées : {w.inputs.join(", ") || "aucune"}</span>
            </li>
          ))}
        </ul>
        <p className="mb-2 text-xs text-zinc-500">
          Dans ComfyUI, exporte ton workflow avec « Export (API) ». Pour un moteur local, utilise l'identifiant wan22_local, ltx_video_local, cogvideox_local ou comfyui_local.
        </p>
        <div className="grid gap-2">
          <div className="grid grid-cols-2 gap-2">
            <input className={inputClass} value={wfId} onChange={(e) => setWfId(e.target.value)} placeholder="Identifiant (ex. wan22_local)" />
            <select className={inputClass} value={wfKind} onChange={(e) => setWfKind(e.target.value as "image" | "video")}>
              <option value="video">Vidéo</option>
              <option value="image">Image</option>
            </select>
          </div>
          <input type="file" accept=".json,application/json" className="text-sm text-zinc-400"
            onChange={(e) => { const file = e.target.files?.[0]; if (file) void file.text().then(setWfJson); }} />
          <Button disabled={!wfId.trim() || !wfJson} busy={addWorkflow.isPending} onClick={() => addWorkflow.mutate(undefined)}>Ajouter le workflow</Button>
        </div>
      </Card>
    </div>
  );
}

function YouTubeSettings() {
  const status = useQuery({ queryKey: ["youtube-status"], queryFn: api.youtubeStatus, refetchInterval: 5000 });
  const connect = useAction(async () => {
    const { url } = await api.youtubeConnect();
    await openExternal(url);
  }, "Page de connexion Google ouverte dans le navigateur.");
  const s = status.data;
  if (!s) return null;

  return (
    <Card title="Chaîne YouTube">
      <div className="space-y-3 text-sm">
        <p className="flex flex-wrap items-center gap-2">
          Publication :
          <Badge tone={s.publish_enabled ? "yellow" : "green"}>{s.publish_enabled ? "activée dans le .env" : "désactivée (par défaut)"}</Badge>
        </p>
        <p className="flex flex-wrap items-center gap-2">
          Chaîne : {s.channel ? <Badge tone="green">{s.channel.title}</Badge> : <Badge>non connectée</Badge>}
        </p>
        <p className="text-zinc-400">Mention ajoutée aux descriptions : « {s.ai_disclosure_text} »</p>
        {!s.client_secrets_configured ? (
          <Alert tone="blue" title="Pour connecter une chaîne">
            1. Dans Google Cloud, active « YouTube Data API v3 » et crée un identifiant OAuth de type « Application de bureau ».{"\n"}
            2. Télécharge le fichier JSON et indique son chemin dans le .env : YOUTUBE_CLIENT_SECRETS_FILE=…{"\n"}
            3. Redémarre le backend puis reviens ici.
          </Alert>
        ) : (
          <Button busy={connect.isPending} onClick={() => connect.mutate(undefined)}>
            {s.channel ? "Reconnecter la chaîne" : "Connecter ma chaîne YouTube"}
          </Button>
        )}
        <p className="text-xs text-zinc-500">
          La connexion autorise seulement l'envoi de vidéos et la lecture de la chaîne. Chaque publication reste soumise à la vérification finale et à ta confirmation.
          Pour publier, il faut aussi YOUTUBE_PUBLISH_ENABLED=true dans le .env.
        </p>
      </div>
    </Card>
  );
}
