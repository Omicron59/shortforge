// Reglages > Intelligence artificielle : fournisseurs, cles, modeles reellement disponibles, choix par tache.
// Aucun appel a un fournisseur ne part d'ici : tout passe par le moteur local.
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "../api/client";
import type { AiModel, AiProviderInfo, AiTask, AiTaskInput, AiTestResult } from "../api/types";
import { Btn, Collapsible, Dialog, Dot, Labeled, Notice, Page, Panel, Pill, SecretInput, Skeleton, Tag, fieldClass, type Tone } from "../components/ds";
import { useToasts } from "../stores/toasts";

const message = (error: unknown) => (error instanceof Error ? error.message : "Erreur inconnue.");
const MODE_LABEL = { local: "Mon PC", cloud: "Cloud" } as const;
const BILLING_LABEL = { free: "Gratuit", subscription: "Abonnement", usage: "Payé à l'usage" } as const;
const price = (v: number | null) => (v === null ? "?" : v === 0 ? "0 $" : `${v < 1 ? v.toFixed(2) : v.toFixed(1)} $`);
const gigabytes = (bytes: number) => `${(bytes / 1e9).toFixed(1)} Go`;

export default function SettingsAI() {
  const providers = useQuery({ queryKey: ["ai", "providers"], queryFn: api.aiProviders });
  const tasks = useQuery({ queryKey: ["ai", "tasks"], queryFn: api.aiTasks });
  const security = useQuery({ queryKey: ["security"], queryFn: api.security });
  const [selected, setSelected] = useState("ollama");
  const [picking, setPicking] = useState<AiModel | null>(null);
  const provider = providers.data?.find((p) => p.id === selected);

  return (
    <Page title="Intelligence artificielle" subtitle="Choisis où tournent les modèles de texte : sur ton PC ou dans le cloud avec tes propres clés. Un modèle différent peut servir à chaque tâche.">
      {security.data && !security.data.vault_available && (
        <Notice tone="warning" title="Coffre à secrets indisponible">
          {security.data.vault_message} Tant qu'il est indisponible, aucune clé API ne peut être enregistrée. Ollama sur ton PC fonctionne sans clé.
        </Notice>
      )}
      {security.data?.vault_available && (
        <Notice tone="success" title="Clés chiffrées">
          Les clés sont chiffrées sur ton disque. La clé de chiffrement est gardée par : {security.data.vault_protection}.
        </Notice>
      )}

      <Panel title="Fournisseurs" hint="Sélectionne un fournisseur pour le régler et voir ses modèles.">
        {providers.isLoading && <Skeleton className="h-9 w-72" />}
        {providers.isError && <LoadError error={providers.error} retry={() => void providers.refetch()} />}
        <div className="flex flex-wrap gap-2">
          {providers.data?.map((p) => (
            <Pill key={p.id} active={p.id === selected} onClick={() => setSelected(p.id)} dot={statusTone(p)}>{p.label}</Pill>
          ))}
        </div>
        {provider && <ProviderSettings key={provider.id} provider={provider} vaultOk={security.data?.vault_available ?? false} />}
      </Panel>

      {provider && <Models provider={provider} tasks={tasks.data ?? []} onPick={setPicking} />}

      <Panel title="Modèle par tâche" hint="Sans réglage, ShortForge utilise Ollama et le modèle de ton fichier de réglages, comme avant.">
        {tasks.isLoading && <Skeleton className="h-24" />}
        {tasks.isError && <LoadError error={tasks.error} retry={() => void tasks.refetch()} />}
        <div className="space-y-3">
          {tasks.data?.map((t) => <TaskRow key={t.task} task={t} providers={providers.data ?? []} />)}
        </div>
      </Panel>

      <Journal />
      {picking && <PickDialog model={picking} tasks={tasks.data ?? []} onClose={() => setPicking(null)} />}
    </Page>
  );
}

function statusTone(p: AiProviderInfo): Tone {
  if (p.reachable === false) return "danger"; // serveur local eteint, meme si un ancien test avait reussi
  if (p.last_test) return !p.last_test.ok ? "danger" : p.last_test.key_checked || !p.needs_key ? "success" : "warning";
  if (p.reachable) return "success";
  return "neutral"; // fournisseur cloud pas encore teste
}

function LoadError({ error, retry }: { error: unknown; retry: () => void }) {
  return (
    <Notice tone="danger" title={error instanceof ApiError && error.status === 0 ? "Connexion au moteur perdue" : "Chargement impossible"}>
      <p>{message(error)}</p>
      <Btn className="mt-2" onClick={retry}>Réessayer</Btn>
    </Notice>
  );
}

function useInvalidate() {
  const client = useQueryClient();
  return () => Promise.all([client.invalidateQueries({ queryKey: ["ai"] }), client.invalidateQueries({ queryKey: ["status"] })]);
}

function ProviderSettings({ provider, vaultOk }: { provider: AiProviderInfo; vaultOk: boolean }) {
  const push = useToasts((s) => s.push);
  const invalidate = useInvalidate();
  const [url, setUrl] = useState(provider.base_url);
  const [key, setKey] = useState("");
  const [result, setResult] = useState<AiTestResult | null>(null);
  const onError = (e: Error) => push(e.message, "error");
  const save = useMutation({
    mutationFn: (body: { base_url?: string; api_key?: string }) => api.aiUpdateProvider(provider.id, body),
    onSuccess: () => { setKey(""); setResult(null); push("Réglage enregistré.", "success"); void invalidate(); },
    onError,
  });
  const removeKey = useMutation({
    mutationFn: () => api.aiDeleteKey(provider.id),
    onSuccess: () => { setResult(null); push("Clé supprimée.", "success"); void invalidate(); },
    onError,
  });
  const test = useMutation({ mutationFn: () => api.aiTestProvider(provider.id), onSuccess: (r) => { setResult(r); void invalidate(); }, onError });
  const shown = result ?? provider.last_test;

  return (
    <div className="mt-5 space-y-4 border-t border-sf-border pt-5">
      <div className="flex flex-wrap items-center gap-2">
        <Tag tone={provider.mode === "local" ? "success" : "primary"}>{MODE_LABEL[provider.mode]}</Tag>
        <Tag tone={provider.billing === "free" ? "neutral" : "warning"}>{BILLING_LABEL[provider.billing]}</Tag>
        {provider.id === "ollama" && <span className="text-xs text-sf-muted">Ollama tourne sur ton PC, mais les modèles « :cloud » s'exécutent sur les serveurs d'Ollama : tes textes quittent alors ton PC.</span>}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Labeled label="Adresse du serveur" hint={provider.base_url_editable ? `Par défaut : ${provider.default_base_url}` : "Adresse fixe pour ce fournisseur."}>
          {(id) => (
            <div className="flex gap-2">
              <input id={id} className={fieldClass} value={url} disabled={!provider.base_url_editable} onChange={(e) => setUrl(e.target.value)} placeholder={provider.default_base_url} />
              {provider.base_url_editable && url !== provider.base_url && <Btn busy={save.isPending} onClick={() => save.mutate({ base_url: url })}>Enregistrer</Btn>}
            </div>
          )}
        </Labeled>
        {provider.needs_key && (
          <Labeled label="Clé API" hint={provider.key_help}>
            {(id) => (
              <>
                {provider.key_set && (
                  <p className="flex flex-wrap items-center gap-2 text-sm text-sf-muted">
                    <Dot tone="success" /> Clé enregistrée, se terminant par <code className="text-sf-text">{provider.key_hint}</code>
                    <Btn variant="danger" className="min-h-[32px] px-2.5" busy={removeKey.isPending} onClick={() => removeKey.mutate()}>Supprimer</Btn>
                  </p>
                )}
                <SecretInput id={id} value={key} disabled={!vaultOk} onChange={(e) => setKey(e.target.value)} placeholder={provider.key_set ? "Coller une nouvelle clé pour la remplacer" : "Coller la clé ici"} />
                {key.trim().length >= 8 && <Btn className="self-start" busy={save.isPending} onClick={() => save.mutate({ api_key: key.trim() })}>Enregistrer la clé</Btn>}
              </>
            )}
          </Labeled>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Btn variant="primary" busy={test.isPending} onClick={() => test.mutate()}>Tester la connexion</Btn>
        {test.isPending && <span className="text-sm text-sf-muted">Requête réelle en cours…</span>}
      </div>
      {shown && !test.isPending && (
        <Notice tone={!shown.ok ? "danger" : shown.key_checked || !provider.needs_key ? "success" : "warning"}
          title={!shown.ok ? "Connexion en échec" : shown.key_checked || !provider.needs_key ? "Connexion réussie" : "Serveur joignable, clé non vérifiée"}>
          {shown.message}
        </Notice>
      )}
    </div>
  );
}

type Filter = "all" | "local" | "cloud" | "free" | "cheap" | "long";
const FILTERS: { id: Filter; label: string; keep: (m: AiModel) => boolean }[] = [
  { id: "all", label: "Tous", keep: () => true },
  { id: "local", label: "Sur mon PC", keep: (m) => m.mode === "local" },
  { id: "cloud", label: "Cloud", keep: (m) => m.mode === "cloud" },
  { id: "free", label: "Gratuits", keep: (m) => m.paid === false },
  { id: "cheap", label: "Économiques (< 1 $ / M jetons)", keep: (m) => m.price_in_per_mtok !== null && m.price_in_per_mtok < 1 && m.paid === true },
  { id: "long", label: "Long contexte (≥ 100 000)", keep: (m) => (m.context_length ?? 0) >= 100_000 },
];
const PAGE = 30;

function Models({ provider, tasks, onPick }: { provider: AiProviderInfo; tasks: AiTask[]; onPick: (m: AiModel) => void }) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [limit, setLimit] = useState(PAGE);
  const models = useQuery({ queryKey: ["ai", "models", provider.id, provider.base_url], queryFn: () => api.aiModels(provider.id), retry: false });
  const usable = useMemo(() => FILTERS.filter((f) => f.id === "all" || models.data?.some(f.keep)), [models.data]);
  const visible = useMemo(() => {
    const words = search.toLowerCase().split(/\s+/).filter(Boolean);
    const keep = FILTERS.find((f) => f.id === filter)?.keep ?? (() => true);
    return (models.data ?? []).filter((m) => keep(m) && words.every((w) => `${m.id} ${m.label}`.toLowerCase().includes(w)));
  }, [models.data, search, filter]);
  const inUse = (m: AiModel) => tasks.filter((t) => t.provider_id === m.provider_id && t.model === m.id).map((t) => t.label);

  return (
    <Panel title={`Modèles de ${provider.label}`} hint="Liste fournie en direct par le fournisseur. Une information absente est indiquée comme inconnue."
      actions={<Btn variant="ghost" busy={models.isFetching} onClick={() => void api.aiModels(provider.id, true).then(() => models.refetch())}>Actualiser</Btn>}>
      {models.isLoading && <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-32" />)}</div>}
      {models.isError && <LoadError error={models.error} retry={() => void models.refetch()} />}
      {models.data && (
        <>
          <div className="mb-4 flex flex-col gap-3">
            <Labeled label="Rechercher un modèle">
              {(id) => <input id={id} type="search" className={fieldClass} value={search} onChange={(e) => { setSearch(e.target.value); setLimit(PAGE); }} placeholder="Nom ou identifiant" />}
            </Labeled>
            {usable.length > 1 && (
              <div className="flex flex-wrap gap-2" role="group" aria-label="Filtres">
                {usable.map((f) => <Pill key={f.id} active={filter === f.id} onClick={() => { setFilter(f.id); setLimit(PAGE); }}>{f.label}</Pill>)}
              </div>
            )}
          </div>
          {models.data.length === 0 && <Notice tone="warning">Ce fournisseur ne déclare aucun modèle pour l'instant{provider.id === "ollama" ? " : installe-en un avec Ollama (par exemple `ollama pull` suivi du nom du modèle)." : "."}</Notice>}
          {models.data.length > 0 && visible.length === 0 && <p className="text-sm text-sf-muted">Aucun modèle ne correspond.</p>}
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {visible.slice(0, limit).map((m) => <ModelCard key={m.id} model={m} provider={provider} usedFor={inUse(m)} onPick={() => onPick(m)} />)}
          </ul>
          {visible.length > limit && (
            <div className="mt-4 flex items-center gap-3 text-sm text-sf-muted">
              <Btn onClick={() => setLimit(limit + PAGE)}>Afficher plus</Btn> {limit} sur {visible.length}
            </div>
          )}
        </>
      )}
    </Panel>
  );
}

function ModelCard({ model, provider, usedFor, onPick }: { model: AiModel; provider: AiProviderInfo; usedFor: string[]; onPick: () => void }) {
  return (
    <li className={`flex flex-col gap-3 rounded-sf border bg-sf-raised p-4 transition duration-sf hover:border-sf-muted/50 ${usedFor.length ? "border-sf-primary/60" : "border-sf-border"}`}>
      <div className="min-w-0">
        <p className="truncate font-medium" title={model.label}>{model.label}</p>
        <p className="truncate text-xs text-sf-muted" title={model.id}>{provider.label} · {model.id}</p>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <Tag tone={model.mode === "local" ? "success" : "primary"}>{MODE_LABEL[model.mode]}</Tag>
        {model.paid === false && <Tag tone="success">Gratuit</Tag>}
        {model.paid === true && <Tag tone="warning">{provider.billing === "usage" ? "Payant" : "Abonnement"}</Tag>}
        {model.paid === null && <Tag tone="warning">Tarif inconnu</Tag>}
        {model.context_length !== null && <Tag>Contexte {model.context_length.toLocaleString("fr-FR")}</Tag>}
        {model.size_bytes !== null && <Tag>{gigabytes(model.size_bytes)}</Tag>}
      </div>
      {model.price_in_per_mtok !== null && model.paid && (
        <p className="text-xs text-sf-muted">{price(model.price_in_per_mtok)} en entrée · {price(model.price_out_per_mtok)} en sortie, par million de jetons</p>
      )}
      {model.description && <p className="line-clamp-2 text-xs text-sf-muted">{model.description}</p>}
      <div className="mt-auto flex items-center justify-between gap-2">
        <span className="truncate text-xs text-violet-300">{usedFor.length ? `Utilisé : ${usedFor.join(", ")}` : ""}</span>
        <Btn onClick={onPick} aria-label={`Choisir ${model.label}`}>Choisir</Btn>
      </div>
    </li>
  );
}

function PickDialog({ model, tasks, onClose }: { model: AiModel; tasks: AiTask[]; onClose: () => void }) {
  const push = useToasts((s) => s.push);
  const invalidate = useInvalidate();
  const [target, setTarget] = useState("all");
  const [agreed, setAgreed] = useState(false);
  const mayCost = model.paid !== false;
  const unknownUsagePrice = model.provider_id === "openrouter" && (model.price_in_per_mtok === null || model.price_out_per_mtok === null);
  const save = useMutation({
    mutationFn: () => {
      const task = target === "all" ? tasks[0] : tasks.find((t) => t.task === target);
      if (!task) throw new Error("Aucune tâche disponible.");
      return api.aiSetTask(task.task, { ...paramsOf(task), provider_id: model.provider_id, model: model.id, confirm_paid: agreed, apply_to_all: target === "all" });
    },
    onSuccess: () => { push("Modèle choisi.", "success"); void invalidate(); onClose(); },
    onError: (e: Error) => push(e.message, "error"),
  });
  return (
    <Dialog title={`Utiliser ${model.label}`} onClose={onClose}
      footer={<><Btn variant="ghost" onClick={onClose}>Annuler</Btn><Btn variant="primary" busy={save.isPending} disabled={unknownUsagePrice || (mayCost && !agreed)} onClick={() => save.mutate()}>Confirmer</Btn></>}>
      {unknownUsagePrice && <Notice tone="danger" title="Tarif non publié">ShortForge ne peut pas plafonner la dépense de ce modèle : il ne peut pas être choisi.</Notice>}
      <Labeled label="Pour quelle tâche ?">
        {(id) => (
          <select id={id} className={fieldClass} value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="all">Toutes les tâches (même modèle partout)</option>
            {tasks.map((t) => <option key={t.task} value={t.task}>{t.label}</option>)}
          </select>
        )}
      </Labeled>
      {mayCost && !unknownUsagePrice && (
        <Notice tone="warning" title="Ce modèle peut être facturé">
          <p>
            {model.price_in_per_mtok !== null
              ? `Tarif annoncé : ${price(model.price_in_per_mtok)} en entrée et ${price(model.price_out_per_mtok)} en sortie par million de jetons.`
              : model.mode === "cloud" && model.paid === true ? "Il tourne dans le cloud et dépend de ton abonnement et de ses limites." : "Son tarif n'est pas communiqué par le fournisseur."}
          </p>
          <label className="mt-2 flex items-start gap-2 text-sf-text">
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-violet-600" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
            J'accepte que ShortForge utilise ce modèle payant pour cette tâche.
          </label>
        </Notice>
      )}
    </Dialog>
  );
}

const paramsOf = (t: AiTask): Omit<AiTaskInput, "provider_id" | "model"> => ({
  fallback_provider_id: t.fallback_provider_id, fallback_model: t.fallback_model, allow_paid_fallback: t.allow_paid_fallback,
  temperature: t.temperature, max_tokens: t.max_tokens, strict_json: t.strict_json, timeout_s: t.timeout_s,
});
const numberOrNull = (text: string) => (text.trim() === "" || Number.isNaN(Number(text)) ? null : Number(text));

function TaskRow({ task, providers }: { task: AiTask; providers: AiProviderInfo[] }) {
  const push = useToasts((s) => s.push);
  const invalidate = useInvalidate();
  const [form, setForm] = useState(() => paramsOf(task));
  const fallbackModels = useQuery({
    queryKey: ["ai", "models", form.fallback_provider_id], queryFn: () => api.aiModels(form.fallback_provider_id ?? ""),
    enabled: !!form.fallback_provider_id, retry: false,
  });
  const fallback = fallbackModels.data?.find((m) => m.id === form.fallback_model);
  const onError = (e: Error) => push(e.message, "error");
  const save = useMutation({
    mutationFn: () => api.aiSetTask(task.task, { ...form, provider_id: task.provider_id, model: task.model }),
    onSuccess: () => { push("Paramètres enregistrés.", "success"); void invalidate(); }, onError,
  });
  const reset = useMutation({ mutationFn: () => api.aiResetTask(task.task), onSuccess: () => { push("Réglage d'origine rétabli.", "success"); void invalidate(); }, onError });

  return (
    <div className="rounded-sf border border-sf-border bg-sf-raised p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium">{task.label}</p>
          <p className="truncate text-sm text-sf-muted">
            {task.model ? <>{task.provider_label} · <span className="text-sf-text">{task.model}</span> · {task.mode === "local" ? "s'exécute sur ton PC" : "s'exécute dans le cloud"}</> : "Aucun modèle choisi : choisis-en un dans la liste ci-dessus."}
            {task.fallback_model && <> · secours : {task.fallback_model}</>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {task.is_default ? <Tag>Réglage d'origine</Tag> : <Btn variant="ghost" busy={reset.isPending} onClick={() => reset.mutate()}>Revenir au réglage d'origine</Btn>}
        </div>
      </div>
      {task.model && (
        <div className="mt-3">
          <Collapsible label="Paramètres avancés">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <Labeled label="Température" hint="0 à 2. Vide = valeur par défaut.">
                {(id) => <input id={id} className={fieldClass} inputMode="decimal" value={form.temperature ?? ""} onChange={(e) => setForm({ ...form, temperature: numberOrNull(e.target.value) })} />}
              </Labeled>
              <Labeled label="Longueur maximale (jetons)" hint="Vide = pas de limite imposée.">
                {(id) => <input id={id} className={fieldClass} inputMode="numeric" value={form.max_tokens ?? ""} onChange={(e) => setForm({ ...form, max_tokens: numberOrNull(e.target.value) })} />}
              </Labeled>
              <Labeled label="Délai maximum (secondes)" hint="Vide = délai du fichier de réglages.">
                {(id) => <input id={id} className={fieldClass} inputMode="numeric" value={form.timeout_s ?? ""} onChange={(e) => setForm({ ...form, timeout_s: numberOrNull(e.target.value) })} />}
              </Labeled>
              <Labeled label="Fournisseur de secours" hint="Utilisé si le modèle principal est en panne, sans clé valide ou hors quota.">
                {(id) => (
                  <select id={id} className={fieldClass} value={form.fallback_provider_id} onChange={(e) => setForm({ ...form, fallback_provider_id: e.target.value, fallback_model: "", allow_paid_fallback: false })}>
                    <option value="">Aucun</option>
                    {providers.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                  </select>
                )}
              </Labeled>
              {form.fallback_provider_id && (
                <Labeled label="Modèle de secours" hint={fallbackModels.isError ? message(fallbackModels.error) : undefined}>
                  {(id) => (
                    <select id={id} className={fieldClass} value={form.fallback_model} disabled={!fallbackModels.data} onChange={(e) => setForm({ ...form, fallback_model: e.target.value, allow_paid_fallback: false })}>
                      <option value="">{fallbackModels.isLoading ? "Chargement…" : "Choisir"}</option>
                      {fallbackModels.data?.map((m) => <option key={m.id} value={m.id}>{m.label}{m.paid === false ? " (gratuit)" : ""}</option>)}
                    </select>
                  )}
                </Labeled>
              )}
            </div>
            <div className="mt-4 space-y-2 text-sm">
              <label className="flex items-start gap-2">
                <input type="checkbox" className="mt-0.5 h-4 w-4 accent-violet-600" checked={form.strict_json ?? true} onChange={(e) => setForm({ ...form, strict_json: e.target.checked })} />
                Réponse JSON stricte (recommandé : ShortForge lit des réponses structurées)
              </label>
              {fallback && fallback.paid !== false && (
                <label className="flex items-start gap-2 text-sf-warning">
                  <input type="checkbox" className="mt-0.5 h-4 w-4 accent-violet-600" checked={form.allow_paid_fallback ?? false} onChange={(e) => setForm({ ...form, allow_paid_fallback: e.target.checked })} />
                  J'autorise le repli automatique vers ce modèle payant. Sans cet accord, il ne sera jamais utilisé.
                </label>
              )}
            </div>
            <Btn className="mt-4" busy={save.isPending} onClick={() => save.mutate()}>Enregistrer les paramètres</Btn>
          </Collapsible>
        </div>
      )}
    </div>
  );
}

function Journal() {
  const calls = useQuery({ queryKey: ["ai", "calls"], queryFn: api.aiCalls });
  return (
    <Panel title="Derniers appels" hint="Ni les textes envoyés ni les clés ne sont enregistrés ici.">
      {calls.isLoading && <Skeleton className="h-16" />}
      {calls.isError && <LoadError error={calls.error} retry={() => void calls.refetch()} />}
      {calls.data?.length === 0 && <p className="text-sm text-sf-muted">Aucun appel pour l'instant.</p>}
      {!!calls.data?.length && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="text-xs text-sf-muted">
              <tr>{["Heure", "Tâche", "Modèle", "Exécution", "Durée", "Jetons", "Coût", "Résultat"].map((h) => <th key={h} scope="col" className="px-2 py-2 font-normal">{h}</th>)}</tr>
            </thead>
            <tbody>
              {calls.data.map((c) => (
                <tr key={c.id} className="border-t border-sf-border">
                  <td className="px-2 py-2 text-sf-muted">{new Date(`${c.at}Z`).toLocaleTimeString("fr-FR")}</td>
                  <td className="px-2 py-2">{c.task}</td>
                  <td className="max-w-[220px] truncate px-2 py-2" title={c.model}>{c.model}{c.used_fallback && " (secours)"}</td>
                  <td className="px-2 py-2">{c.mode === "local" ? "Mon PC" : "Cloud"}</td>
                  <td className="px-2 py-2 tabular-nums">{(c.duration_ms / 1000).toFixed(1)} s</td>
                  <td className="px-2 py-2 tabular-nums">{c.input_tokens ?? "?"} / {c.output_tokens ?? "?"}</td>
                  <td className="px-2 py-2 tabular-nums">{c.cost_usd !== null ? `${c.cost_usd.toFixed(4)} $` : c.billing === "free" ? "0 $" : c.billing === "subscription" ? "abonnement" : "inconnu"}</td>
                  <td className="px-2 py-2">{c.ok ? <Tag tone="success">Réussi</Tag> : <span title={c.error}><Tag tone="danger">{c.error_kind || "Échec"}</Tag></span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
