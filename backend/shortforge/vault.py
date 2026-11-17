"""Coffre a secrets : cles API et jetons chiffres au repos.

Comment la cle de chiffrement est protegee
------------------------------------------
Les secrets sont chiffres (Fernet : AES-128-CBC + HMAC-SHA256) avec une cle maitresse qui n'est
JAMAIS ecrite dans la base ni dans un fichier de ShortForge. Elle est rangee dans le trousseau du
systeme : Gestionnaire d'identification sous Windows, Trousseau sous macOS, Secret Service sous Linux.
Ce trousseau est lui-meme chiffre avec la session de l'utilisateur.

Apres un redemarrage, le moteur relit la cle dans le trousseau (ouvert par la session) et dechiffre
les secrets a la demande : rien a ressaisir. La base seule, copiee sur un autre ordinateur ou un autre
compte, ne permet pas de les lire.

Sans trousseau (serveur sans session graphique), la cle peut venir de la variable d'environnement
SHORTFORGE_SECRET_KEY. Sans l'un ni l'autre, le coffre refuse d'enregistrer un secret plutot que
d'ecrire une cle en clair a cote des donnees.
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from shortforge.models import Secret

ENV_KEY = "SHORTFORGE_SECRET_KEY"
KEYRING_SERVICE = "ShortForge"
KEYRING_USER = "coffre-v1"


class VaultError(RuntimeError):
    """Erreur du coffre ; le message est destine a l'utilisateur."""


class VaultUnavailableError(VaultError):
    pass


class KeyStore(Protocol):
    label: str

    def load(self) -> str | None: ...

    def save(self, key: str) -> None: ...


class EnvKeyStore:
    """Cle derivee de la phrase SHORTFORGE_SECRET_KEY (jamais ecrite sur le disque par ShortForge)."""

    label = "variable d'environnement SHORTFORGE_SECRET_KEY"

    def load(self) -> str | None:
        phrase = os.environ.get(ENV_KEY, "")
        if len(phrase) < 16:
            raise VaultUnavailableError(f"{ENV_KEY} doit contenir au moins 16 caractères.")
        raw = hashlib.scrypt(phrase.encode(), salt=b"shortforge-coffre-v1", n=2**14, r=8, p=1, dklen=32)
        return base64.urlsafe_b64encode(raw).decode()

    def save(self, key: str) -> None:  # la cle vient de l'environnement : rien a enregistrer
        raise VaultUnavailableError(f"La clé du coffre vient de {ENV_KEY} et ne peut pas être remplacée ici.")


class KeyringKeyStore:
    """Cle rangee dans le trousseau du systeme d'exploitation."""

    def __init__(self) -> None:
        import keyring

        self._keyring = keyring
        self.label = f"trousseau du système ({type(keyring.get_keyring()).__module__.rsplit('.', 1)[-1]})"

    def load(self) -> str | None:
        value: str | None = self._keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
        return value

    def save(self, key: str) -> None:
        self._keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)


class MemoryKeyStore:
    """Pour les tests : la cle vit en memoire."""

    label = "mémoire (tests)"

    def __init__(self) -> None:
        self.key: str | None = None

    def load(self) -> str | None:
        return self.key

    def save(self, key: str) -> None:
        self.key = key


def default_keystore() -> KeyStore | None:
    """Trousseau du systeme, sinon variable d'environnement, sinon rien (coffre indisponible)."""
    if os.environ.get(ENV_KEY):
        return EnvKeyStore()
    try:
        import keyring

        backend = keyring.get_keyring()
        if float(getattr(backend, "priority", 0)) <= 0:  # « fail » ou « null » : pas de vrai trousseau
            return None
        return KeyringKeyStore()
    except Exception:
        return None


def hint_of(value: str) -> str:
    """Fin du secret pour le reconnaitre a l'ecran, sans le reveler."""
    return f"…{value[-4:]}" if len(value) >= 12 else "…"


class Vault:
    def __init__(self, keystore: KeyStore | None) -> None:
        self._keystore = keystore
        self._fernet: Fernet | None = None

    @property
    def protection(self) -> str:
        return self._keystore.label if self._keystore else ""

    @property
    def available(self) -> bool:
        try:
            self._cipher()
        except VaultError:
            return False
        return True

    def _cipher(self) -> Fernet:
        if self._fernet is not None:
            return self._fernet
        if self._keystore is None:
            raise VaultUnavailableError(
                "Coffre indisponible : aucun trousseau système trouvé. Définis la variable d'environnement "
                f"{ENV_KEY} (16 caractères minimum) pour protéger les secrets, puis relance ShortForge.")
        try:
            key = self._keystore.load()
            if key is None:
                key = Fernet.generate_key().decode()
                self._keystore.save(key)
                if self._keystore.load() != key:  # le trousseau n'a pas garde la cle : ne rien chiffrer avec
                    raise VaultUnavailableError("Le trousseau système n'a pas conservé la clé du coffre.")
            self._fernet = Fernet(key.encode())
        except VaultError:
            raise
        except Exception as exc:
            message = f"Coffre indisponible : le trousseau système a refusé l'accès ({exc})."
            raise VaultUnavailableError(message) from exc
        return self._fernet

    def encrypt(self, value: str) -> str:
        return self._cipher().encrypt(value.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._cipher().decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise VaultError("Secret illisible : la clé du coffre a changé. Ressaisis ce secret.") from exc

    def set(self, session: Session, name: str, value: str) -> None:
        value = value.strip()
        if not value:
            raise VaultError("Le secret est vide.")
        ciphertext = self.encrypt(value)
        if self.decrypt(ciphertext) != value:
            raise VaultError("Le coffre n'a pas pu vérifier le secret : rien n'a été enregistré.")
        row = session.get(Secret, name)
        if row is None:
            session.add(Secret(name=name, ciphertext=ciphertext, hint=hint_of(value)))
        else:
            row.ciphertext, row.hint = ciphertext, hint_of(value)
        session.flush()

    def get(self, session: Session, name: str) -> str | None:
        row = session.get(Secret, name)
        return None if row is None else self.decrypt(row.ciphertext)

    def hint(self, session: Session, name: str) -> str | None:
        """Indice d'affichage ; None si aucun secret n'est enregistre sous ce nom."""
        row = session.get(Secret, name)
        return None if row is None else row.hint

    def delete(self, session: Session, name: str) -> bool:
        row = session.get(Secret, name)
        if row is None:
            return False
        session.delete(row)
        session.flush()
        return True
