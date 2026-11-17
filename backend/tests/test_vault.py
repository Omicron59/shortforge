"""Coffre a secrets : chiffrement au repos, cle hors de la base, reprise apres redemarrage."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.models import YoutubeChannel
from shortforge.services.youtube import YouTubeClient, YouTubeError, token_path
from shortforge.vault import EnvKeyStore, MemoryKeyStore, Vault, VaultError, VaultUnavailableError, hint_of

SECRET = "sk-or-v1-0123456789abcdefWXYZ"


def test_secret_is_encrypted_at_rest_and_key_is_not_in_the_database(session: Session, settings: Settings) -> None:
    store = MemoryKeyStore()
    vault = Vault(store)
    vault.set(session, "ai:openrouter", SECRET)
    session.commit()

    raw = sqlite3.connect(settings.database_url.removeprefix("sqlite:///")).execute(
        "SELECT ciphertext, hint FROM secrets").fetchone()
    assert SECRET not in raw[0] and raw[1] == "…WXYZ"
    dump = Path(settings.database_url.removeprefix("sqlite:///")).read_bytes()
    assert SECRET.encode() not in dump and (store.key or "").encode() not in dump
    assert vault.get(session, "ai:openrouter") == SECRET


def test_secret_is_read_again_after_restart_with_the_same_keystore(session: Session) -> None:
    store = MemoryKeyStore()
    Vault(store).set(session, "ai:openrouter", SECRET)
    assert Vault(store).get(session, "ai:openrouter") == SECRET  # nouveau processus, meme trousseau


def test_database_alone_cannot_reveal_the_secret(session: Session) -> None:
    Vault(MemoryKeyStore()).set(session, "ai:openrouter", SECRET)
    with pytest.raises(VaultError, match="illisible"):
        Vault(MemoryKeyStore()).get(session, "ai:openrouter")  # autre machine : autre cle


def test_without_keystore_nothing_is_stored(session: Session) -> None:
    vault = Vault(None)
    assert not vault.available
    with pytest.raises(VaultUnavailableError, match="SHORTFORGE_SECRET_KEY"):
        vault.set(session, "ai:openrouter", SECRET)
    assert vault.hint(session, "ai:openrouter") is None


def test_environment_key_gives_the_same_key_every_start(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHORTFORGE_SECRET_KEY", "une phrase assez longue")
    Vault(EnvKeyStore()).set(session, "x", SECRET)
    assert Vault(EnvKeyStore()).get(session, "x") == SECRET
    monkeypatch.setenv("SHORTFORGE_SECRET_KEY", "court")
    assert not Vault(EnvKeyStore()).available


def test_hint_never_reveals_a_short_secret() -> None:
    assert hint_of("abcdefgh") == "…" and hint_of(SECRET) == "…WXYZ"


def channel_with_plain_token(session: Session, settings: Settings) -> YoutubeChannel:
    path = token_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"access_token": "acces", "refresh_token": "durable", "expires_at": 9e12}))
    channel = YoutubeChannel(channel_id="UC1", title="Ma chaîne", token_path=str(path), is_default=True)
    session.add(channel)
    session.flush()
    return channel


def test_existing_youtube_token_is_encrypted_in_place_and_still_works(session: Session, settings: Settings) -> None:
    channel = channel_with_plain_token(session, settings)
    store = MemoryKeyStore()
    client = YouTubeClient(settings, vault=Vault(store))
    assert client.token_encrypted(Path(channel.token_path)) is False
    assert client.access_token(channel) == "acces"  # premiere lecture : le jeton est chiffre sur place

    raw = Path(channel.token_path).read_text()
    assert "durable" not in raw and "acces" not in raw and client.token_encrypted(Path(channel.token_path)) is True
    assert YouTubeClient(settings, vault=Vault(store)).access_token(channel) == "acces"  # apres redemarrage


def test_youtube_token_is_left_untouched_when_the_vault_is_unavailable(session: Session, settings: Settings) -> None:
    channel = channel_with_plain_token(session, settings)
    before = Path(channel.token_path).read_text()
    assert YouTubeClient(settings, vault=Vault(None)).access_token(channel) == "acces"
    assert Path(channel.token_path).read_text() == before


def test_encrypted_youtube_token_with_a_lost_key_asks_to_reconnect(session: Session, settings: Settings) -> None:
    channel = channel_with_plain_token(session, settings)
    YouTubeClient(settings, vault=Vault(MemoryKeyStore())).access_token(channel)
    with pytest.raises(YouTubeError, match="reconnecte"):
        YouTubeClient(settings, vault=Vault(MemoryKeyStore())).access_token(channel)
