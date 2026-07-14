"""
Il profilo NotebookLM (i cookie di sessione Google) — chi lo possiede lo scrive.

nb1777-mcp è l'UNICO servizio che monta il volume `nlm-auth`: il gateway (che è
l'unico esposto su Internet) e il bot non ci arrivano più, né in lettura né in
scrittura (finding H6). Loro chiedono qui, via endpoint interno.

Formato: la CLI `nlm` 0.7.x salva l'auth come cartella `profiles/default/`
(`cookies.json` + `metadata.json`), non come un singolo `auth.json`. Si carica un
tar.gz di quella cartella.

Modulo stdlib-only e senza dipendenze dal server: si testa da solo.
"""
from __future__ import annotations

import io
import shutil
import tarfile
from pathlib import Path

# Il file che rende il profilo "valido": senza questo, non c'è auth.
COOKIES_REL = Path("profiles") / "default" / "cookies.json"
PENDING_FLAG = "AUTH_PENDING.flag"


def profile_status(auth_dir: Path) -> dict:
    """Stato del profilo — ciò che gateway e bot possono sapere senza vedere i cookie."""
    has_cookies = (auth_dir / COOKIES_REL).is_file()
    pending = (auth_dir / PENDING_FLAG).exists()
    return {
        "ok": has_cookies and not pending,
        "has_cookies": has_cookies,
        "pending": pending,
    }


def _extract_into(content: bytes, dest: Path) -> int:
    """
    Estrae i file sotto `profiles/` da un tar.gz NON FIDATO. Ritorna il #file.

    Difese (l'archivio arriva dall'esterno, via upload):
    - solo file regolari → niente symlink/hardlink/device (no symlink attack);
    - niente path assoluti né `..` → niente traversal fuori da `dest`;
    - si ignora tutto ciò che non sta sotto `profiles/`;
    - permessi 600 sui file scritti.
    """
    n = 0
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
        for m in tar.getmembers():
            if not m.isfile():
                continue
            name = m.name.lstrip("./")
            parts = Path(name).parts
            if name.startswith("/") or ".." in parts:
                raise ValueError(f"percorso non sicuro nel tar: {m.name}")
            if not parts or parts[0] != "profiles":
                continue
            f = tar.extractfile(m)
            if f is None:
                continue
            out = dest / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(f.read())
            out.chmod(0o600)
            n += 1
    return n


def install_profile(content: bytes, auth_dir: Path) -> int:
    """
    Installa il profilo da un tar.gz. Ritorna il #file scritti.

    Non distruttivo: si estrae in una staging, si VALIDA, e solo allora si
    sostituisce il profilo buono (con rollback se lo swap fallisce). Un upload
    malformato lascia intatto il profilo già presente — così un errore non ti
    scollega da NotebookLM.

    Alza ValueError (messaggio per l'utente) se il tar non è un profilo valido.
    """
    if not content:
        raise ValueError("file vuoto")

    auth_dir.mkdir(parents=True, exist_ok=True)
    staging = auth_dir / ".upload-staging"
    prev = auth_dir / ".profiles-prev"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    try:
        try:
            n = _extract_into(content, staging)
        except tarfile.TarError as exc:
            raise ValueError(f"non è un tar.gz valido del profilo nlm ({exc})") from exc

        if not (staging / COOKIES_REL).is_file():
            raise ValueError(
                "il tar non contiene profiles/default/cookies.json — hai taggato la cartella giusta?"
            )

        # swap: profiles/ vecchio da parte, nuovo al suo posto, vecchio via.
        dest = auth_dir / "profiles"
        shutil.rmtree(prev, ignore_errors=True)
        if dest.exists():
            dest.rename(prev)
        try:
            (staging / "profiles").rename(dest)
        except OSError:
            if prev.exists():          # rollback: rimetti quello di prima
                prev.rename(dest)
            raise
        shutil.rmtree(prev, ignore_errors=True)

        # profilo valido → l'auth non è più pendente
        flag = auth_dir / PENDING_FLAG
        if flag.exists():
            flag.unlink()
        return n
    finally:
        shutil.rmtree(staging, ignore_errors=True)
