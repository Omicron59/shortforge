"""Client du serveur local ComfyUI et bibliotheque de workflows (format API JSON).

Deroulement d'une generation : envoi du workflow (`POST /prompt`), suivi de la progression par
WebSocket (`/ws`, avec repli sur l'interrogation de `/history` si le WebSocket est indisponible),
puis telechargement des fichiers produits (`GET /view`).
"""

from __future__ import annotations

import copy
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ProgressCallback = Callable[[float, str], None]  # (fraction 0-1, message)

WORKFLOW_SUFFIX = ".json"
MAPPING_SUFFIX = ".shortforge.json"
INPUT_KEYS = ("prompt", "negative_prompt", "width", "height", "seed", "model", "input_image", "last_image",
              "duration_s", "frames", "fps")
VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".gif", ".webp")


class ComfyUIError(RuntimeError):
    """Erreur ComfyUI ; le message est destine a l'utilisateur."""


@dataclass(frozen=True, slots=True)
class InputRef:
    node: str
    field: str


@dataclass(slots=True)
class WorkflowSpec:
    id: str
    name: str
    kind: str  # image | video
    path: Path
    inputs: dict[str, InputRef] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)
    user: bool = False


@dataclass(frozen=True, slots=True)
class ComfyOutput:
    filename: str
    subfolder: str
    type: str

    @property
    def is_video(self) -> bool:
        return self.filename.lower().endswith(VIDEO_EXTENSIONS)


# ── Workflows ──


def validate_api_workflow(workflow: Any) -> dict[str, Any]:
    """Verifie qu'un workflow est au format API (et non au format interface de ComfyUI)."""
    if isinstance(workflow, dict) and "nodes" in workflow and isinstance(workflow["nodes"], list):
        raise ComfyUIError("Ce workflow est au format interface : exporte-le avec « Workflow → Export (API) ».")
    if not isinstance(workflow, dict) or not workflow:
        raise ComfyUIError("Workflow vide ou illisible.")
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or "class_type" not in node or not isinstance(node.get("inputs"), dict):
            raise ComfyUIError(f"Le nœud {node_id} n'est pas au format API (class_type et inputs attendus).")
    return workflow


def guess_inputs(workflow: dict[str, Any]) -> dict[str, InputRef]:
    """Devine les entrees d'un workflow simple (KSampler, CLIPTextEncode, EmptyLatentImage, LoadImage...)."""
    found: dict[str, InputRef] = {}
    for node_id, node in workflow.items():
        inputs, cls = node["inputs"], node["class_type"]
        if "seed" in inputs and "positive" in inputs and "seed" not in found:
            found["seed"] = InputRef(node_id, "seed")
            for key, link in (("prompt", inputs.get("positive")), ("negative_prompt", inputs.get("negative"))):
                if isinstance(link, list) and link and "text" in workflow.get(str(link[0]), {}).get("inputs", {}):
                    found[key] = InputRef(str(link[0]), "text")
        if cls.startswith("Empty") and "width" in inputs and "height" in inputs and "width" not in found:
            found["width"], found["height"] = InputRef(node_id, "width"), InputRef(node_id, "height")
        if "ckpt_name" in inputs and "model" not in found:
            found["model"] = InputRef(node_id, "ckpt_name")
        if cls == "LoadImage" and "input_image" not in found:
            found["input_image"] = InputRef(node_id, "image")
    return found


def apply_inputs(workflow: dict[str, Any], spec: WorkflowSpec, values: dict[str, Any]) -> dict[str, Any]:
    """Copie du workflow avec les valeurs remplacees. Les valeurs `None` sont ignorees."""
    result = copy.deepcopy(workflow)
    for key, value in {**spec.defaults, **values}.items():
        if value is None:
            continue
        ref = spec.inputs.get(key)
        if ref is None:
            if key in ("prompt",):
                raise ComfyUIError(f"Le workflow « {spec.name} » n'indique pas où placer le prompt.")
            continue  # entree facultative absente de ce workflow
        node = result.get(ref.node)
        if node is None:
            raise ComfyUIError(f"Le workflow « {spec.name} » ne contient pas le nœud {ref.node}.")
        node["inputs"][ref.field] = value
    return result


class WorkflowLibrary:
    """Workflows du projet (`assets/workflows`) et de l'utilisateur (dossier de donnees)."""

    def __init__(self, dirs: list[Path], user_dir: Path) -> None:
        self.dirs = dirs
        self.user_dir = user_dir

    def list(self) -> list[WorkflowSpec]:
        specs: dict[str, WorkflowSpec] = {}
        for directory in [*self.dirs, self.user_dir]:
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob(f"*{WORKFLOW_SUFFIX}")):
                if path.name.endswith(MAPPING_SUFFIX):
                    continue
                try:
                    specs[path.stem] = self._spec(path, user=directory == self.user_dir)
                except (ComfyUIError, json.JSONDecodeError, OSError):
                    continue  # un fichier illisible n'empeche pas de lister les autres
        return list(specs.values())

    def get(self, workflow_id: str) -> WorkflowSpec:
        for spec in self.list():
            if spec.id == workflow_id:
                return spec
        raise ComfyUIError(f"Workflow « {workflow_id} » introuvable : ajoute-le dans les paramètres.")

    def load(self, workflow_id: str) -> tuple[dict[str, Any], WorkflowSpec]:
        spec = self.get(workflow_id)
        return validate_api_workflow(json.loads(spec.path.read_text(encoding="utf-8"))), spec

    def add(self, workflow_id: str, workflow: dict[str, Any], *, name: str = "", kind: str = "image",
            inputs: dict[str, dict[str, str]] | None = None) -> WorkflowSpec:
        """Enregistre un workflow de l'utilisateur, avec la description de ses entrees."""
        if not workflow_id.replace("_", "").replace("-", "").isalnum():
            raise ComfyUIError("Identifiant de workflow invalide : lettres, chiffres, - et _ uniquement.")
        if kind not in ("image", "video"):
            raise ComfyUIError("Type de workflow inconnu : image ou video.")
        validate_api_workflow(workflow)
        refs = {k: InputRef(**v) for k, v in (inputs or {}).items()} if inputs else guess_inputs(workflow)
        for key, ref in refs.items():
            if key not in INPUT_KEYS:
                raise ComfyUIError(f"Entrée inconnue : {key}.")
            if ref.node not in workflow:
                raise ComfyUIError(f"Le nœud {ref.node} indiqué pour « {key} » n'existe pas dans le workflow.")
        self.user_dir.mkdir(parents=True, exist_ok=True)
        path = self.user_dir / f"{workflow_id}{WORKFLOW_SUFFIX}"
        path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
        mapping = {"name": name or workflow_id, "kind": kind,
                   "inputs": {k: {"node": r.node, "field": r.field} for k, r in refs.items()}}
        (self.user_dir / f"{workflow_id}{MAPPING_SUFFIX}").write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._spec(path, user=True)

    @staticmethod
    def _spec(path: Path, *, user: bool) -> WorkflowSpec:
        workflow = validate_api_workflow(json.loads(path.read_text(encoding="utf-8")))
        mapping_path = path.with_name(path.stem + MAPPING_SUFFIX)
        meta: dict[str, Any] = {}
        if mapping_path.exists():
            meta = json.loads(mapping_path.read_text(encoding="utf-8"))
        inputs = ({k: InputRef(str(v["node"]), str(v["field"])) for k, v in meta.get("inputs", {}).items()}
                  if meta.get("inputs") else guess_inputs(workflow))
        return WorkflowSpec(id=path.stem, name=meta.get("name", path.stem), kind=meta.get("kind", "image"),
                            path=path, inputs=inputs, defaults=meta.get("defaults", {}), user=user)


# ── Client HTTP / WebSocket ──


# Ports habituels : ComfyUI Desktop (8000) et ComfyUI classique ou portable (8188).
DEFAULT_COMFYUI_URLS = ("http://127.0.0.1:8000", "http://127.0.0.1:8188")


class ComfyUIClient:
    def __init__(self, base_url: str, *, timeout_s: float = 1800, poll_interval_s: float = 1.0,
                 use_websocket: bool = True, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep, candidates: list[str] | None = None) -> None:
        self.timeout_s = timeout_s
        self.poll_interval_s = poll_interval_s
        self.use_websocket = use_websocket
        self._sleep = sleep
        self._transport = transport
        # Adresses essayees si l'adresse actuelle ne repond pas (detection automatique du port).
        self.candidates = [u.rstrip("/") for u in (candidates or [])]
        self.set_base_url(base_url)

    def set_base_url(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(base_url=self.base_url, timeout=60, transport=self._transport)

    def _responds(self, url: str) -> bool:
        try:
            with httpx.Client(transport=self._transport, timeout=2) as probe:
                res = probe.get(f"{url}/system_stats")
        except httpx.HTTPError:
            return False
        return res.status_code == 200

    def detect(self) -> str | None:
        """Adresse qui repond (l'actuelle d'abord, puis les ports habituels) ; bascule dessus. None sinon."""
        for url in dict.fromkeys([self.base_url, *self.candidates]):
            if self._responds(url):
                if url != self.base_url:
                    self.set_base_url(url)
                return url
        return None

    def checkpoints(self) -> list[str]:
        """Modeles d'image (checkpoints) installes dans ComfyUI."""
        try:
            res = self._http.get("/object_info/CheckpointLoaderSimple", timeout=10)
            res.raise_for_status()
            info = res.json().get("CheckpointLoaderSimple", {})
            names = info.get("input", {}).get("required", {}).get("ckpt_name", [[]])[0]
        except (httpx.HTTPError, ValueError, AttributeError, IndexError, TypeError):
            return []
        return [str(n) for n in names] if isinstance(names, list) else []

    def system_stats(self) -> dict[str, Any]:
        try:
            res = self._http.get("/system_stats")
            res.raise_for_status()
        except httpx.HTTPError as exc:
            raise ComfyUIError(f"ComfyUI ne répond pas à {self.base_url}. Lance ComfyUI Desktop.") from exc
        data: dict[str, Any] = res.json()
        return data

    def is_running(self) -> bool:
        try:
            self.system_stats()
        except ComfyUIError:
            return self.detect() is not None  # ComfyUI a peut-etre un autre port : on le cherche
        return True

    def upload_image(self, path: Path) -> str:
        """Envoie une image d'entree dans ComfyUI et renvoie le nom a placer dans le workflow."""
        with path.open("rb") as fh:
            res = self._request("POST", "/upload/image", files={"image": (path.name, fh, "image/png")},
                                data={"overwrite": "true"})
        name = res.json().get("name", path.name)
        sub = res.json().get("subfolder", "")
        return f"{sub}/{name}" if sub else str(name)

    def queue(self, workflow: dict[str, Any], client_id: str) -> str:
        res = self._http.post("/prompt", json={"prompt": workflow, "client_id": client_id})
        if res.status_code >= 400:
            raise ComfyUIError(self._describe_error(res))
        prompt_id = res.json().get("prompt_id")
        if not prompt_id:
            raise ComfyUIError("ComfyUI n'a pas accepté le workflow.")
        return str(prompt_id)

    def history(self, prompt_id: str) -> dict[str, Any] | None:
        entry = self._request("GET", f"/history/{prompt_id}").json().get(prompt_id)
        return entry if isinstance(entry, dict) else None

    def wait(self, prompt_id: str, client_id: str, on_progress: ProgressCallback | None = None) -> dict[str, Any]:
        """Attend la fin de la generation et renvoie l'entree d'historique."""
        if self.use_websocket:
            try:
                self._listen(prompt_id, client_id, on_progress)
            except ComfyUIError:
                raise
            except Exception:  # WebSocket indisponible : on bascule sur l'interrogation de /history
                pass
        deadline = time.monotonic() + self.timeout_s
        while True:
            entry = self.history(prompt_id)
            if entry is not None:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise ComfyUIError("La génération a échoué dans ComfyUI : " + _execution_error(status))
                if status.get("completed", True) and entry.get("outputs") is not None:
                    if on_progress:
                        on_progress(1.0, "Terminé")
                    return entry
            if time.monotonic() > deadline:
                raise ComfyUIError("ComfyUI met trop de temps à répondre : génération abandonnée.")
            self._sleep(self.poll_interval_s)

    @staticmethod
    def outputs(entry: dict[str, Any]) -> list[ComfyOutput]:
        files = []
        for node_output in entry.get("outputs", {}).values():
            for key in ("images", "gifs", "videos", "video"):
                for item in node_output.get(key, []) or []:
                    if isinstance(item, dict) and item.get("filename"):
                        files.append(ComfyOutput(item["filename"], item.get("subfolder", ""),
                                                 item.get("type", "output")))
        return [f for f in files if f.type == "output"] or files

    def download(self, output: ComfyOutput, dest_dir: Path) -> Path:
        res = self._request("GET", "/view", params={"filename": output.filename, "subfolder": output.subfolder,
                                                    "type": output.type})
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / Path(output.filename).name
        path.write_bytes(res.content)
        return path

    def run(self, workflow: dict[str, Any], dest_dir: Path, on_progress: ProgressCallback | None = None) -> list[Path]:
        """Envoie le workflow, attend la fin et telecharge les fichiers produits."""
        client_id = uuid.uuid4().hex
        prompt_id = self.queue(workflow, client_id)
        entry = self.wait(prompt_id, client_id, on_progress)
        files = self.outputs(entry)
        if not files:
            raise ComfyUIError("Le workflow s'est terminé sans produire de fichier (nœud de sauvegarde manquant ?).")
        return [self.download(f, dest_dir) for f in files]

    def interrupt(self) -> None:
        self._request("POST", "/interrupt")

    # ── Interne ──

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            res = self._http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise ComfyUIError(f"ComfyUI ne répond pas à {self.base_url}. Lance ComfyUI Desktop.") from exc
        if res.status_code >= 400:
            raise ComfyUIError(f"ComfyUI a renvoyé une erreur {res.status_code} sur {url}.")
        return res

    def _listen(self, prompt_id: str, client_id: str, on_progress: ProgressCallback | None) -> None:
        from websockets.sync.client import connect

        ws_url = self.base_url.replace("http", "ws", 1) + f"/ws?clientId={client_id}"
        deadline = time.monotonic() + self.timeout_s
        with connect(ws_url, open_timeout=5) as ws:
            while time.monotonic() < deadline:
                raw = ws.recv(timeout=self.timeout_s)
                if not isinstance(raw, str):
                    continue  # apercus binaires
                msg = json.loads(raw)
                data = msg.get("data", {})
                if data.get("prompt_id") not in (None, prompt_id):
                    continue
                kind = msg.get("type")
                if kind == "progress" and on_progress and data.get("max"):
                    on_progress(float(data["value"]) / float(data["max"]), "Génération en cours")
                elif kind == "execution_error":
                    raise ComfyUIError("La génération a échoué dans ComfyUI : "
                                       + str(data.get("exception_message", "erreur inconnue")))
                elif kind == "execution_success" or (
                    kind == "executing" and data.get("node") is None and data.get("prompt_id") == prompt_id
                ):
                    return

    @staticmethod
    def _describe_error(res: httpx.Response) -> str:
        try:
            body = res.json()
        except ValueError:
            return f"ComfyUI a refusé le workflow (erreur {res.status_code})."
        details = []
        for node_id, err in (body.get("node_errors") or {}).items():
            for e in err.get("errors", []):
                details.append(f"nœud {node_id} ({err.get('class_type', '?')}) : {e.get('message', '')} "
                               f"{e.get('details', '')}".strip())
        message = body.get("error", {}).get("message", "") if isinstance(body.get("error"), dict) else ""
        return "ComfyUI a refusé le workflow : " + ("; ".join(details) or message or f"erreur {res.status_code}")


def _execution_error(status: dict[str, Any]) -> str:
    for message in status.get("messages", []):
        if isinstance(message, list) and len(message) == 2 and message[0] == "execution_error":
            return str(message[1].get("exception_message", "erreur inconnue"))
    return "erreur inconnue"
