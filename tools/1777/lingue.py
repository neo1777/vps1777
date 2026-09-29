#!/usr/bin/env python3
"""lingue.py — i documenti per i contributori, in una lingua o in due (K5, F2.3).

La regola (K5): l'italiano c'è sempre ed è il sorgente; se il repo è pubblico c'è anche
l'inglese, che è la sua traduzione. Quale dei due è il file principale (`AGENTS.md`, quello
che GitHub mostra) lo dice la risposta copier `doc_lingua_primaria`:
  en  → AGENTS.md inglese, AGENTS.it.md italiano (come vps1777)
  it  → AGENTS.md italiano, AGENTS.en.md inglese
Un repo privato ha solo l'italiano, nel file principale.

Una copia in due lingue ha un modo solo di morire: le due divergono in silenzio, e quella
vecchia continua a sembrare buona. Per questo, se il repo è pubblico, `controlla` è rosso se:
  - manca uno dei due file, o uno non rimanda all'altro;
  - non sono ALLINEATI: stessi nomi fra backtick, stessi id «derivata»/«derived», stesso
    numero di titoli e di righe di tabella (la forma di una traduzione, non la prosa);
  - la traduzione è STANTIA: l'impronta del sorgente italiano non è quella registrata in
    tools/1777/traduzioni.json (la prosa). Il blocco C3, che scrive la prova, non conta.
E sempre, pubblico o no, è rosso se una sigla dei documenti non è nel glossario
(tools/1777/GLOSSARIO.md, o GLOSSARIO.it.md): le sigle vengono dalle decisioni del template,
e chi arriva da fuori non ha altro modo di leggerle.

Uso: python3 tools/1777/lingue.py            controlla (lo chiama conformita.py)
     python3 tools/1777/lingue.py mostra     lo stato delle traduzioni, senza scrivere
     python3 tools/1777/lingue.py registra   dopo aver AGGIORNATO la traduzione inglese:
                                             registra l'impronta del sorgente com'è ora.
Registrare senza aver tradotto trasforma il controllo in un timbro.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

BASI = ("AGENTS", "RIGHE", "tools/1777/GLOSSARIO")
REGISTRO = "tools/1777/traduzioni.json"
C3 = re.compile(r"<!-- C3:inizio.*?<!-- C3:fine -->", re.DOTALL)
SIGLA = re.compile(
    r"(?<![\w.-])(?:DD-P8\.\d+|K[a-e]\.\d+|K-[a-e]|K\d|AP\.\d+|D\d{1,2}|C\d{1,2}"
    r"|M\.\d+|R\.\d+|T\d|F\d?\.\d+|Pr\.\d+)(?!\w)"
)


def risposte(radice: pathlib.Path) -> dict[str, str]:
    f = radice / ".copier-answers.yml"
    if not f.is_file():
        return {}
    out = {}
    for riga in f.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z_][\w]*):\s*['\"]?([^'\"#]*?)['\"]?\s*$", riga)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def piano(radice: pathlib.Path) -> tuple[bool, list[tuple[str, str, str | None]]]:
    """(pubblico, [(base, file italiano, file inglese o None)])."""
    r = risposte(radice)
    pubblico = r.get("pubblico", "false").lower() == "true"
    primaria = r.get("doc_lingua_primaria", "en") or "en"
    docs = []
    for b in BASI:
        if not pubblico:
            docs.append((b, f"{b}.md", None))
        elif primaria == "it":
            docs.append((b, f"{b}.md", f"{b}.en.md"))
        else:
            docs.append((b, f"{b}.it.md", f"{b}.md"))
    return pubblico, docs


def impronta(f: pathlib.Path) -> str:
    """sha256 del testo senza il blocco C3 (lo riscrive la prova) e senza spazi ai bordi."""
    t = C3.sub("", f.read_text(encoding="utf-8")).strip()
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def forma(testo: str) -> dict[str, object]:
    """La forma di un documento: quello che una traduzione fedele non cambia."""
    t = C3.sub("", testo)
    nomi = {
        re.sub(r"\.(?:it|en)\.md$", ".md", x) for x in re.findall(r"`([^`\n]+)`", t)
    }
    return {
        "nomi fra backtick": nomi,
        "id derivati": set(re.findall(r"(?:derivata|derived): `([a-z0-9-]+)`", t)),
        "titoli": sum(1 for r in t.splitlines() if re.match(r"#{1,6} ", r)),
        "righe di tabella": sum(1 for r in t.splitlines() if r.startswith("|")),
    }


def voci_glossario(testo: str) -> list[re.Pattern[str]]:
    """Le sigle spiegate: la prima cella di ogni riga di tabella; «n» sta per un numero."""
    voci = []
    for riga in testo.splitlines():
        m = re.match(r"^\|\s*([^|]+?)\s*\|", riga)
        if not m or set(m.group(1)) <= set("-: "):
            continue
        for v in re.split(r",\s*", m.group(1)):
            esc = re.escape(v.strip())
            voci.append(re.compile(re.sub(r"(?<=[.A-Za-z])n$", r"\\d+", esc) + r"\Z"))
    return voci


def controlla(radice: pathlib.Path) -> tuple[list[str], list[str]]:
    """(rossi, note). Ogni rosso comincia con la sua regola fra parentesi quadre."""
    rossi: list[str] = []
    note: list[str] = []
    pubblico, docs = piano(radice)

    # --- il glossario: ogni sigla dei documenti è spiegata (pubblico o no)
    glo = next((it for b, it, _ in docs if b.endswith("GLOSSARIO")), "")
    gf = radice / glo
    if not gf.is_file():
        rossi.append(f"[glossario] manca {glo}: le sigle dei documenti non si leggono")
    else:
        voci = voci_glossario(gf.read_text(encoding="utf-8"))
        for _, it, en in docs:
            for nome in (it, en):
                f = radice / nome if nome else None
                if f is None or not f.is_file() or f == gf:
                    continue
                ignote = sorted(
                    {
                        s
                        for s in SIGLA.findall(f.read_text(encoding="utf-8"))
                        if not any(v.match(s) for v in voci)
                    }
                )
                if ignote:
                    rossi.append(
                        f"[glossario] {nome} usa {', '.join(ignote)}, che {glo} non spiega: "
                        "aggiungi la voce, o scrivi la cosa per esteso"
                    )

    if not pubblico:
        return rossi, note

    # --- K5: tutte e due le lingue, che si rimandano
    for _, it, en in docs:
        assert en is not None
        mancano = [n for n in (it, en) if not (radice / n).is_file()]
        if mancano:
            rossi.append(
                f"[lingua] il repo è pubblico e manca {', '.join(mancano)}: K5 vuole il "
                f"documento in italiano ({it}) e in inglese ({en})"
            )
            continue
        ti = (radice / it).read_text(encoding="utf-8")
        te = (radice / en).read_text(encoding="utf-8")
        for a, ta, b in ((it, ti, en), (en, te, it)):
            if pathlib.Path(b).name not in ta:
                rossi.append(f"[lingua] {a} non rimanda a {pathlib.Path(b).name}")
        # --- allineati nella forma
        fi, fe = forma(ti), forma(te)
        for chiave in fi:
            if fi[chiave] != fe[chiave]:
                if isinstance(fi[chiave], set):
                    solo_it = sorted(fi[chiave] - fe[chiave])[:3]  # type: ignore[operator]
                    solo_en = sorted(fe[chiave] - fi[chiave])[:3]  # type: ignore[operator]
                    diff = f"solo in {it}: {solo_it}; solo in {en}: {solo_en}"
                else:
                    diff = f"{it}: {fi[chiave]}, {en}: {fe[chiave]}"
                rossi.append(
                    f"[lingua] {it} e {en} non sono allineati ({chiave}): {diff}"
                )

    # --- la traduzione non è stantia: l'impronta del sorgente è quella registrata
    reg = radice / REGISTRO
    if not reg.is_file():
        rossi.append(
            f"[lingua] manca {REGISTRO}: senza, una traduzione vecchia sembra buona. "
            f"Dopo aver verificato le traduzioni: python3 tools/1777/lingue.py registra"
        )
        return rossi, note
    try:
        registrate = json.loads(reg.read_text(encoding="utf-8"))["traduzioni"]
    except (json.JSONDecodeError, KeyError, TypeError):
        rossi.append(
            f"[lingua] {REGISTRO} non si legge (JSON con la chiave «traduzioni»)"
        )
        return rossi, note
    for _, it, en in docs:
        if not (radice / it).is_file():
            continue
        voce = registrate.get(en) or {}
        if voce.get("sorgente") != it:
            rossi.append(
                f"[lingua] {REGISTRO} non registra {en} come traduzione di {it}"
            )
        elif voce.get("sorgente_sha256") != impronta(radice / it):
            rossi.append(
                f"[lingua] traduzione STANTIA: {it} è cambiato dopo che {en} è stato tradotto. "
                "Cura: aggiorna l'inglese, POI python3 tools/1777/lingue.py registra"
            )
    return rossi, note


def registra(radice: pathlib.Path, scrivi: bool) -> int:
    pubblico, docs = piano(radice)
    if not pubblico:
        print(
            "il repo non è pubblico: un documento solo, in italiano, niente da registrare"
        )
        return 0
    reg = radice / REGISTRO
    dati = {"_nota": "", "traduzioni": {}}
    if reg.is_file():
        dati = json.loads(reg.read_text(encoding="utf-8"))
    dati["_nota"] = (
        "Per ogni traduzione inglese, l'impronta (sha256, senza il blocco C3) del sorgente "
        "italiano quando è stata tradotta. conformita.py [lingua] è rosso se il sorgente si "
        "muove: si aggiorna la traduzione, POI python3 tools/1777/lingue.py registra."
    )
    cambiate = 0
    for _, it, en in docs:
        assert en is not None
        nuova = impronta(radice / it)
        vecchia = dati["traduzioni"].get(en, {}).get("sorgente_sha256")
        print(f"  {'fresca ' if vecchia == nuova else 'STANTIA'}  {en}  ←  {it}")
        if vecchia != nuova:
            cambiate += 1
            dati["traduzioni"][en] = {"sorgente": it, "sorgente_sha256": nuova}
    if scrivi and cambiate:
        reg.write_text(
            json.dumps(dati, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(
            f"registrate {cambiate} impronte (le traduzioni le hai DAVVERO aggiornate?)"
        )
    return 0


def main() -> int:
    radice = pathlib.Path(__file__).resolve().parents[2]
    cmd = sys.argv[1] if len(sys.argv) > 1 else "controlla"
    if cmd in ("registra", "mostra"):
        return registra(radice, scrivi=cmd == "registra")
    rossi, note = controlla(radice)
    for n in note:
        print(n)
    for r in rossi:
        print(f"✗ ROSSO {r}", file=sys.stderr)
    return 1 if rossi else 0


if __name__ == "__main__":
    sys.exit(main())
