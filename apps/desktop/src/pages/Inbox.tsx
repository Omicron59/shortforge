// Boite de validation : toutes les decisions qui t'attendent, tous Shorts confondus.
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAction } from "../api/hooks";
import type { Validation } from "../api/types";
import { Alert, Badge, Button, Empty, PageHeader } from "../components/ui";
import { dateTime } from "../lib/format";
import { useProjectStore } from "../stores/project";

const KIND: Record<string, { label: string; to: string; tone: "yellow" | "violet" | "blue" | "red" | "green" }> = {
  idee: { label: "Idée", to: "/idees", tone: "blue" },
  script: { label: "Script", to: "/script", tone: "blue" },
  depense: { label: "Dépense", to: "/scenes", tone: "yellow" },
  apercu: { label: "Aperçu", to: "/apercu", tone: "violet" },
  rendu_final: { label: "Rendu final", to: "/apercu", tone: "violet" },
  publication: { label: "Publication", to: "/apercu", tone: "green" },
  autre: { label: "Validation", to: "/", tone: "yellow" },
};

export default function Inbox() {
  const items = useQuery({ queryKey: ["validations"], queryFn: api.validations, refetchInterval: 4000 });
  const setCurrent = useProjectStore((s) => s.setCurrent);
  const navigate = useNavigate();
  const approveScript = useAction((v: Validation) => api.approve(v.project_id, v.step).then(() => api.autopilot(v.project_id)),
    "Script validé : la suite avance toute seule.");

  const open = (v: Validation) => {
    setCurrent(v.project_id);
    navigate(v.kind === "depense" && v.step === "generate_voice" ? "/voix" : KIND[v.kind].to);
  };

  return (
    <>
      <PageHeader title="À valider" subtitle="Un clic par Short : ouvre, vérifie, valide. Les validations restent toujours les tiennes." />
      {items.data?.length ? (
        <ul className="space-y-2">
          {items.data.map((v) => (
            <li key={`${v.project_id}-${v.step}`} className="flex flex-wrap items-center gap-3 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
              <Badge tone={KIND[v.kind].tone}>{KIND[v.kind].label}</Badge>
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{v.project_title}</p>
                <p className="text-xs text-zinc-500">{v.label}{v.planned_for && ` · prévu le ${dateTime(v.planned_for)}`}</p>
                {v.message && <p className="mt-1 whitespace-pre-line text-sm text-amber-200">{v.message}</p>}
              </div>
              {v.kind === "script" && (
                <Button variant="ghost" busy={approveScript.isPending} onClick={() => approveScript.mutate(v)}>Valider sans relire</Button>
              )}
              <Button variant="primary" onClick={() => open(v)}>Ouvrir</Button>
            </li>
          ))}
        </ul>
      ) : (
        <Empty>Rien à valider pour l'instant.</Empty>
      )}
      <div className="mt-6"><Alert tone="blue">Le rendu final et la publication se valident toujours dans l'écran Aperçu, après avoir regardé la vidéo.</Alert></div>
    </>
  );
}
