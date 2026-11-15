"""Moteurs de voix off.

- Piper : voix neuronales locales et gratuites (programme `piper` + fichier de voix .onnx).
- Voix du systeme : deja installees, sans telechargement (Windows : SAPI ; macOS : `say` ;
  Linux : espeak-ng). Qualite plus modeste, mais rien a configurer.
- ElevenLabs : service payant optionnel (ta propre voix clonee). Chaque depense est confirmee.

Chaque moteur produit un fichier WAV 48 kHz stereo.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from shortforge.config import Settings
from shortforge.media import MediaToolError, run, to_wav


class TTSError(RuntimeError):
    """Erreur de voix off ; le message est destine a l'utilisateur."""


@dataclass(slots=True)
class EngineStatus:
    id: str
    name: str
    local: bool
    available: bool
    detail: str = ""


class TTSEngine(Protocol):
    id: str
    name: str
    local: bool

    def status(self) -> EngineStatus: ...

    def synthesize(self, text: str, dest: Path, *, language: str = "fr", speed: float = 1.0) -> Path: ...

    def estimate_cost(self, text: str) -> float | None: ...


class PiperEngine:
    id, name, local = "piper", "Piper (local)", True

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _binary(self) -> str | None:
        return shutil.which(self.settings.piper_path)

    def status(self) -> EngineStatus:
        if not self.settings.piper_voice:
            return EngineStatus(self.id, self.name, True, False, "aucune voix : renseigne PIPER_VOICE (.onnx)")
        if not Path(self.settings.piper_voice).is_file():
            return EngineStatus(self.id, self.name, True, False, f"voix introuvable : {self.settings.piper_voice}")
        if not self._binary():
            return EngineStatus(self.id, self.name, True, False, "programme piper introuvable (PIPER_PATH)")
        return EngineStatus(self.id, self.name, True, True, Path(self.settings.piper_voice).stem)

    def synthesize(self, text: str, dest: Path, *, language: str = "fr", speed: float = 1.0) -> Path:
        status = self.status()
        if not status.available:
            raise TTSError(f"Piper indisponible : {status.detail}.")
        raw = dest.with_suffix(".piper.wav")
        length_scale = f"{1 / max(0.5, min(2.0, speed)):.3f}"  # plus petit = plus rapide
        try:
            run([str(self._binary()), "--model", self.settings.piper_voice, "--length_scale", length_scale,
                 "--output_file", str(raw)], input_text=text, timeout_s=600, what="Piper")
            return to_wav(self.settings, raw, dest)
        except MediaToolError as exc:
            raise TTSError(str(exc)) from exc
        finally:
            raw.unlink(missing_ok=True)

    def estimate_cost(self, text: str) -> float | None:
        return 0.0


class SystemEngine:
    """Voix deja installees avec le systeme d'exploitation."""

    id, local = "system", True

    def __init__(self, settings: Settings, platform: str | None = None) -> None:
        self.settings = settings
        self.platform = platform or sys.platform
        self.name = {"win32": "Voix Windows", "darwin": "Voix macOS"}.get(self.platform, "espeak-ng (Linux)")

    def _program(self) -> str | None:
        if self.platform == "win32":
            return shutil.which("powershell") or shutil.which("pwsh")
        if self.platform == "darwin":
            return shutil.which("say")
        return shutil.which("espeak-ng") or shutil.which("espeak")

    def status(self) -> EngineStatus:
        program = self._program()
        detail = self.settings.system_voice or "voix par défaut du système"
        return EngineStatus(self.id, self.name, True, program is not None,
                            detail if program else "aucune synthèse vocale trouvée sur ce système")

    def command(self, text_file: Path, raw: Path, *, language: str, speed: float) -> list[str]:
        program = self._program()
        if program is None:
            raise TTSError("Aucune voix système disponible.")
        voice = self.settings.system_voice
        if self.platform == "win32":
            rate = round(max(-10, min(10, (speed - 1) * 10)))
            select = f"$s.SelectVoice('{voice.replace(chr(39), '')}');" if voice else (
                f"$v=$s.GetInstalledVoices()|?{{$_.VoiceInfo.Culture.Name -like '{language}*'}}|select -First 1;"
                "if($v){$s.SelectVoice($v.VoiceInfo.Name)};")
            script = ("Add-Type -AssemblyName System.Speech;"
                      "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;" + select +
                      f"$s.Rate={rate};$s.SetOutputToWaveFile('{raw}');"
                      f"$s.Speak([IO.File]::ReadAllText('{text_file}',[Text.Encoding]::UTF8));$s.Dispose()")
            return [program, "-NoProfile", "-NonInteractive", "-Command", script]
        if self.platform == "darwin":
            cmd = [program, "-o", str(raw), "-r", str(round(180 * speed)), "-f", str(text_file)]
            return cmd[:1] + (["-v", voice] if voice else []) + cmd[1:]
        cmd = [program, "-v", voice or language, "-s", str(round(160 * speed)), "-w", str(raw), "-f", str(text_file)]
        return cmd

    def synthesize(self, text: str, dest: Path, *, language: str = "fr", speed: float = 1.0) -> Path:
        suffix = ".aiff" if self.platform == "darwin" else ".wav"
        with tempfile.TemporaryDirectory() as tmp:
            text_file, raw = Path(tmp) / "texte.txt", Path(tmp) / f"voix{suffix}"
            text_file.write_text(text, encoding="utf-8")
            try:
                run(self.command(text_file, raw, language=language, speed=speed), timeout_s=600, what=self.name)
                return to_wav(self.settings, raw, dest)
            except MediaToolError as exc:
                raise TTSError(str(exc)) from exc

    def estimate_cost(self, text: str) -> float | None:
        return 0.0


class ElevenLabsEngine:
    id, name, local = "elevenlabs", "ElevenLabs (payant)", False
    base_url = "https://api.elevenlabs.io"

    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self._http = httpx.Client(base_url=self.base_url, timeout=180, transport=transport)

    def status(self) -> EngineStatus:
        if self.settings.elevenlabs_api_key is None or not self.settings.elevenlabs_voice_id:
            return EngineStatus(self.id, self.name, False, False,
                                "ajoute ELEVENLABS_API_KEY et ELEVENLABS_VOICE_ID dans le fichier .env")
        if self.settings.elevenlabs_cost_per_1000_chars is None:
            return EngineStatus(self.id, self.name, False, True,
                                "tarif inconnu : renseigne ELEVENLABS_COST_PER_1000_CHARS pour pouvoir l'utiliser")
        return EngineStatus(self.id, self.name, False, True, f"voix {self.settings.elevenlabs_voice_id}")

    def estimate_cost(self, text: str) -> float | None:
        rate = self.settings.elevenlabs_cost_per_1000_chars
        return None if rate is None else round(len(text) / 1000 * rate, 4)

    def synthesize(self, text: str, dest: Path, *, language: str = "fr", speed: float = 1.0) -> Path:
        key = self.settings.elevenlabs_api_key
        if key is None or not self.settings.elevenlabs_voice_id:
            raise TTSError("ElevenLabs n'est pas configuré : ajoute sa clé et sa voix dans le fichier .env.")
        res = self._http.post(f"/v1/text-to-speech/{self.settings.elevenlabs_voice_id}",
                              headers={"xi-api-key": key.get_secret_value(), "accept": "audio/mpeg"},
                              json={"text": text, "model_id": self.settings.elevenlabs_model,
                                    "voice_settings": {"speed": max(0.7, min(1.2, speed))}})
        if res.status_code in (401, 403):
            raise TTSError("ElevenLabs refuse la clé API : vérifie ELEVENLABS_API_KEY.")
        if res.status_code == 402 or res.status_code == 429:
            raise TTSError("ElevenLabs : crédit épuisé ou trop de demandes.")
        if res.status_code >= 400:
            raise TTSError(f"Erreur ElevenLabs {res.status_code}.")
        mp3 = dest.with_suffix(".mp3")
        mp3.write_bytes(res.content)
        try:
            return to_wav(self.settings, mp3, dest)
        except MediaToolError as exc:
            raise TTSError(str(exc)) from exc
        finally:
            mp3.unlink(missing_ok=True)


def all_engines(settings: Settings, *, transport: httpx.BaseTransport | None = None) -> list[TTSEngine]:
    return [PiperEngine(settings), SystemEngine(settings), ElevenLabsEngine(settings, transport=transport)]


def pick_engine(settings: Settings, choice: str | None = None, *,
                transport: httpx.BaseTransport | None = None) -> TTSEngine:
    """Moteur demande, ou en mode « auto » : Piper s'il est pret, sinon la voix du systeme."""
    engines = {e.id: e for e in all_engines(settings, transport=transport)}
    wanted = (choice or settings.tts_engine or "auto").lower()
    if wanted in engines:
        return engines[wanted]
    if engines["piper"].status().available:
        return engines["piper"]
    return engines["system"]
