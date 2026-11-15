"""Transcription locale avec faster-whisper (optionnelle).

Sert a minuter les sous-titres mot par mot sur la voix off et a decouper une video longue.
Si faster-whisper n'est pas installe, l'application continue avec un minutage calcule.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class TranscriptionError(RuntimeError):
    """Erreur de transcription ; le message est destine a l'utilisateur."""


class Transcriber(Protocol):
    def available(self) -> bool: ...

    def transcribe(self, path: Path, *, language: str = "fr") -> list[dict[str, Any]]:
        """Segments [{start, end, text, words: [{word, start, end}]}]."""
        ...


class FasterWhisper:
    def __init__(self, model: str = "small") -> None:
        self.model_name = model
        self._model: Any = None

    def available(self) -> bool:
        try:
            import faster_whisper  # type: ignore[import-not-found,unused-ignore]  # noqa: F401
        except ImportError:
            return False
        return True

    def transcribe(self, path: Path, *, language: str = "fr") -> list[dict[str, Any]]:
        if not self.available():
            raise TranscriptionError("Transcription indisponible : installe faster-whisper "
                                     "(pip install \"shortforge[media]\").")
        from faster_whisper import WhisperModel  # type: ignore[import-not-found,unused-ignore]

        if self._model is None:  # premier appel : telechargement du modele (une seule fois)
            self._model = WhisperModel(self.model_name, device="auto", compute_type="int8")
        try:
            segments, _ = self._model.transcribe(str(path), language=language or None, word_timestamps=True,
                                                 vad_filter=True)
            return [{"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip(),
                     "words": [{"word": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)}
                               for w in (s.words or [])]}
                    for s in segments]
        except Exception as exc:  # erreurs de decodage, memoire...
            raise TranscriptionError(f"La transcription a échoué : {exc}") from exc
