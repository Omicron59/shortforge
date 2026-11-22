// Etape 1 : le brief. Peu de champs, des valeurs par defaut, le reste dans une section repliee.
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { wizard, type Brief, type WizardOptions } from "../../api/wizard";
import { Btn, Collapsible, Labeled, Notice, Page, Panel, Pill, Skeleton, fieldClass } from "../../components/ds";
import { useProjectStore } from "../../stores/project";
import { ArchivedProjects, ProjectRowActions } from "../../components/ProjectLifecycle";
import { EngineNote, NoModel, SaveBadge, Stepper, message, useAutosave, useWizard } from "./shared";

const DRAFT_KEY = "shortforge.brief-draft";

function loadDraft(defaults: Brief): Brief {
  try {
    return { ...defaults, ...(JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "{}") as Partial<Brief>) };
  } catch {
    return defaults;
  }
}

export default function BriefPage() {
  const { id } = useParams();
  const options = useQuery({ queryKey: ["wizard", "options"], queryFn: wizard.options, staleTime: Infinity });
  return (
    <Page title={id ? "Brief" : "Nouveau Short"} subtitle="Dis en quelques mots ce que tu veux créer. Tout le reste a une valeur par défaut, modifiable à tout moment.">
      {options.isLoading && <Skeleton className="h-64" />}
      {options.isError && <Notice tone="danger" title="Moteur injoignable">{message(options.error)}</Notice>}
      {options.data && (id ? <Existing id={id} options={options.data} /> : <Fresh options={options.data} />)}
    </Page>
  );
}

function Fresh({ options }: { options: WizardOptions }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const setCurrent = useProjectStore((s) => s.setCurrent);
  const [brief, setBrief] = useState<Brief>(() => loadDraft(options.defaults));
  const engines = useQuery({ queryKey: ["wizard", "engines"], queryFn: wizard.engines });
  useEffect(() => {
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify(brief)); } catch { /* stockage indisponible : le brief reste a l'ecran */ }
  }, [brief]);
  const ready = brief.subject.trim().length > 0 || brief.niche.trim().length > 0;
  const create = useMutation({
    mutationFn: async (manual: boolean) => {
      const state = await wizard.create(brief);
      if (manual) await wizard.manualScript(state.project.id);
      return { id: state.project.id, manual };
    },
    onSuccess: ({ id, manual }) => {
      try { localStorage.removeItem(DRAFT_KEY); } catch { /* rien */ }
      void queryClient.invalidateQueries({ queryKey: ["projects"] }); // le menu affiche tout de suite le nouveau projet
      setCurrent(id);
      navigate(manual ? `/creer/${id}/script` : `/creer/${id}/idees`, { state: { generate: !manual } });
    },
  });
  const ideasEngine = engines.data?.ideas;
  const canGenerate = !ideasEngine || ideasEngine.configured !== false;

  return (
    <>
      <Stepper />
      <BriefForm brief={brief} onChange={setBrief} options={options} />
      <NoModel engine={ideasEngine}>
        <Btn disabled={!ready} busy={create.isPending} onClick={() => create.mutate(true)}>Écrire le script moi-même</Btn>
      </NoModel>
      {create.isError && <Notice tone="danger" title="Création impossible">{message(create.error)} Ton brief est conservé.</Notice>}
      <div className="flex flex-wrap items-center gap-4">
        <Btn variant="primary" disabled={!ready || !canGenerate} busy={create.isPending} onClick={() => create.mutate(false)}>Générer 5 idées</Btn>
        <SaveBadge status="idle" label="Brouillon gardé sur cet appareil" />
        <EngineNote engine={ideasEngine} />
      </div>
      {!ready && <p className="text-sm text-sf-muted">Indique au moins un sujet ou une niche pour continuer.</p>}
      <Drafts />
    </>
  );
}

function Existing({ id, options }: { id: string; options: WizardOptions }) {
  const query = useWizard(id);
  const navigate = useNavigate();
  const [brief, setBrief] = useState<Brief | null>(null);
  useEffect(() => { if (query.data && !brief) setBrief(query.data.brief); }, [query.data, brief]);
  const status = useAutosave(brief, (value) => (value ? wizard.saveBrief(id, value).then(() => query.refetch()) : Promise.resolve()), !!brief);
  if (!brief || !query.data) return <Skeleton className="h-64" />;
  return (
    <>
      <Stepper id={id} state={query.data} />
      <BriefForm brief={brief} onChange={setBrief} options={options} />
      <div className="flex flex-wrap items-center gap-4">
        <Btn variant="primary" onClick={() => navigate(`/creer/${id}/idees`)}>Continuer vers les idées</Btn>
        <SaveBadge status={status} />
      </div>
      <p className="text-sm text-sf-muted">Modifier le brief ne change pas les idées ni le script déjà créés : il sert aux prochaines générations.</p>
    </>
  );
}

function BriefForm({ brief, onChange, options }: { brief: Brief; onChange: (b: Brief) => void; options: WizardOptions }) {
  const set = <K extends keyof Brief>(key: K, value: Brief[K]) => onChange({ ...brief, [key]: value });
  return (
    <Panel>
      <div className="space-y-5">
        <Labeled label="Quel Short veux-tu créer ?" hint="Une idée, un sujet, une question. Quelques mots suffisent.">
          {(fid) => <textarea id={fid} rows={3} className={`${fieldClass} py-2`} value={brief.subject} onChange={(e) => set("subject", e.target.value)} placeholder="Ex. : pourquoi les chats ronronnent" />}
        </Labeled>
        <div className="grid gap-4 md:grid-cols-2">
          <Labeled label="Niche" hint="Le thème de ta chaîne.">
            {(fid) => <input id={fid} className={fieldClass} value={brief.niche} onChange={(e) => set("niche", e.target.value)} placeholder="Ex. : animaux, cuisine, finance perso" />}
          </Labeled>
          <Labeled label="Public visé" hint="Facultatif.">
            {(fid) => <input id={fid} className={fieldClass} value={brief.audience} onChange={(e) => set("audience", e.target.value)} placeholder="Ex. : débutants de 18 à 30 ans" />}
          </Labeled>
        </div>
        <Choice label="Ton" value={brief.tone} choices={options.tones} onPick={(v) => set("tone", v)} />
        <Choice label="Durée visée" value={String(brief.duration_s)} choices={Object.fromEntries(options.durations.map((d) => [String(d), `${d} s`]))} onPick={(v) => set("duration_s", Number(v))} />
        <Collapsible label="Plus de réglages (objectif, plateforme, langue, contraintes)">
          <div className="space-y-5">
            <Choice label="Objectif" value={brief.goal} choices={options.goals} onPick={(v) => set("goal", v)} />
            <Choice label="Plateforme principale" value={brief.platform} choices={options.platforms} onPick={(v) => set("platform", v)} />
            <div className="grid gap-4 md:grid-cols-2">
              <Labeled label="Langue">
                {(fid) => (
                  <select id={fid} className={fieldClass} value={brief.language} onChange={(e) => set("language", e.target.value)}>
                    {Object.entries(options.languages).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                )}
              </Labeled>
              <Labeled label="Style visuel" hint="Facultatif.">
                {(fid) => <input id={fid} className={fieldClass} value={brief.visual_style} onChange={(e) => set("visual_style", e.target.value)} placeholder="Ex. : réaliste, dessin animé, minimaliste" />}
              </Labeled>
            </div>
            <Labeled label="Contraintes" hint="Produit ou marque à citer, format imposé…">
              {(fid) => <textarea id={fid} rows={2} className={`${fieldClass} py-2`} value={brief.constraints} onChange={(e) => set("constraints", e.target.value)} />}
            </Labeled>
            <Labeled label="Sujets à éviter">
              {(fid) => <textarea id={fid} rows={2} className={`${fieldClass} py-2`} value={brief.avoid} onChange={(e) => set("avoid", e.target.value)} />}
            </Labeled>
          </div>
        </Collapsible>
      </div>
    </Panel>
  );
}

function Choice({ label, value, choices, onPick }: { label: string; value: string; choices: Record<string, string>; onPick: (v: string) => void }) {
  return (
    <fieldset>
      <legend className="mb-2 text-sm">{label}</legend>
      <div className="flex flex-wrap gap-2">
        {Object.entries(choices).map(([key, text]) => <Pill key={key} active={value === key} onClick={() => onPick(key)}>{text}</Pill>)}
      </div>
    </fieldset>
  );
}

/** Reprise d'un brouillon : les projets existants s'ouvrent dans le nouveau parcours. */
function Drafts() {
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const setCurrent = useProjectStore((s) => s.setCurrent);
  if (!projects.data) return null;
  return (
    <Panel title="Reprendre un projet" hint="Chaque projet rouvre à l'étape où tu t'étais arrêté. Archiver le retire de la liste sans rien effacer.">
      {projects.data.length === 0 && <p className="text-sm text-sf-muted">Aucun projet en cours.</p>}
      <ul className="divide-y divide-sf-border">
        {projects.data.slice(0, 12).map((p) => (
          <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 py-2.5">
            <div className="min-w-0">
              <p className="truncate">{p.title}</p>
              <p className="text-xs text-sf-muted">Modifié le {new Date(`${p.updated_at}Z`).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" })}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <ProjectRowActions project={p} />
              <Link to={`/creer/${p.id}`} onClick={() => setCurrent(p.id)} className="inline-flex min-h-[40px] items-center rounded-xl border border-sf-border bg-sf-raised px-4 text-sm hover:border-sf-muted/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-sf-primary">Reprendre</Link>
            </div>
          </li>
        ))}
      </ul>
      <ArchivedProjects />
    </Panel>
  );
}
