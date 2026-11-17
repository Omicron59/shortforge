// /creer/:id : rouvre le projet a l'etape ou l'utilisateur s'etait arrete.
import { Navigate, useParams } from "react-router-dom";
import { Page } from "../../components/ds";
import { StateGate, useWizard } from "./shared";

export default function Resume() {
  const { id = "" } = useParams();
  const query = useWizard(id);
  return (
    <Page title="Reprise du projet">
      <StateGate query={query}>
        {(state) => <Navigate replace to={`/creer/${id}/${state.step === "studio" ? "studio" : state.step === "script" ? "script" : "idees"}`} />}
      </StateGate>
    </Page>
  );
}
