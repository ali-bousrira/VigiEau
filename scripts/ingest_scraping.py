"""
scripts/ingest_scraping.py — Importe des valeurs limites réglementaires
par web scraping (source #2 des 5 exigées pour C1, après l'API Hub'Eau).

Source : la table "Comparison of parametric values" de la page Wikipédia
"Drinking water quality standards" — vraie balise HTML <table>, pas un
tableau généré en JS, vérifiée par un appel réel avant d'écrire ce script
(voir docs/rapport_e1.md §2.1 pour le contexte complet).

    https://en.wikipedia.org/wiki/Drinking_water_quality_standards

Nature des données : contrairement à Hub'Eau ou à l'OCR (qui donnent des
mesures ponctuelles réelles), cette source donne des VALEURS LIMITES
réglementaires par organisme normatif (OMS, UE, États-Unis, Chine, Canada,
Inde/BIS) — chaque organisme devient un "prélèvement" de référence dans le
même schéma, avec `lieu` = nom de l'organisme. C'est une différence de
nature honnêtement documentée, pas une tentative de faire passer une
norme pour une mesure de terrain.

Correspondance entre les lignes du tableau Wikipédia et les 9 features
VigiEau (vérifiée en inspectant le HTML réel — les cellules fusionnées
via rowspan/colspan de MediaWiki décalent les colonnes si on les ignore,
d'où le parseur de grille ci-dessous plutôt qu'un simple find_all) :

    Ligne Wikipédia (paramètre)  | feature VigiEau | fiabilité
    ------------------------------|-----------------|---------------------
    pH                            | ph              | directe (plage, on
                                   |                 | prend le milieu)
    Total dissolved solids        | Solids          | directe (ppm ≈ mg/L)
    Sulphate                      | Sulfate         | directe
    hardness                      | Hardness        | directe si valeur
                                   |                 | numérique ; ignorée
                                   |                 | si classification
                                   |                 | floue ("0–75 = soft")
    electrical conductivity       | Conductivity    | directe
    (aucune ligne exploitable)    | Chloramines     | pas de paramètre
                                   |                 | comparable dans ce
                                   |                 | tableau — reste None
    (aucune ligne exploitable)    | Organic_carbon  | idem
    (aucune ligne exploitable)    | Trihalomethanes | présente dans le
                                   |                 | tableau mais sans
                                   |                 | valeur numérique
                                   |                 | dans les colonnes
                                   |                 | disponibles — reste
                                   |                 | None plutôt que
                                   |                 | deviné
    (aucune ligne exploitable)    | Turbidity       | idem

Usage :
    python scripts/ingest_scraping.py
    python scripts/ingest_scraping.py --dry-run
"""

import sys
import os
import re
import argparse
import logging

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import SessionLocal, init_db, Client, Prelevement, IngestionSource, utcnow
from routes import _save_prelevement, _save_prediction, run_prediction

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

logger = logging.getLogger(__name__)

SOURCE_URL = "https://en.wikipedia.org/wiki/Drinking_water_quality_standards"
USER_AGENT = "Mozilla/5.0 (VigiEau educational project; RNCP 37827 C1)"

SYSTEM_CLIENT_ID   = "OPENDATA-SCRAPING"
SYSTEM_CLIENT_NAME = "Import scraping (open data)"
SYSTEM_CLIENT_ADDR = "Wikipedia — Drinking water quality standards"

FEATURES = [
    "ph", "Hardness", "Solids", "Chloramines", "Sulfate",
    "Conductivity", "Organic_carbon", "Trihalomethanes", "Turbidity",
]

# Libellé de ligne Wikipédia (en minuscules, recherche par sous-chaîne) -> feature VigiEau
ROW_MAP = {
    "ph":                     "ph",
    "total dissolved solids": "Solids",
    "sulphate":               "Sulfate",
    "hardness":               "Hardness",
    "electrical conductivity": "Conductivity",
}

_NUM_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def _extract_number(text: str) -> float | None:
    """
    Extrait une valeur numérique unique d'une cellule de norme réglementaire.
    Refuse volontairement les classifications floues ("0–75 mg/L = soft")
    plutôt que d'en deviner une valeur : cohérent avec la consigne du
    projet ("Si valeur floue -> null, ne devine pas", voir ocr_service.py).
    """
    if not text or "=" in text:
        return None
    numbers = [float(n.replace(",", ".")) for n in _NUM_RE.findall(text)]
    if not numbers:
        return None
    if len(numbers) >= 2 and (" to " in text or "–" in text or "-" in text):
        return round(sum(numbers[:2]) / 2, 3)
    return numbers[0]


def _parse_grid(table) -> tuple[list[str], list[list[str]]]:
    """
    Développe un tableau HTML en grille complète en tenant compte de
    rowspan/colspan — un find_all naïf décale les colonnes dès qu'une
    cellule fusionnée apparaît plus haut dans le tableau (constaté en
    inspectant le HTML réel : ignorer rowspan/colspan aurait attribué la
    valeur de l'Inde à l'OMS pour plusieurs lignes).
    """
    rows = table.find_all("tr")
    grid: list[list[str]] = []
    pending: dict[int, tuple[str, int]] = {}

    for tr in rows:
        cells = tr.find_all(["th", "td"])
        row_out: list[str] = []
        col = 0
        cell_iter = iter(cells)
        current = next(cell_iter, None)
        while current is not None or col in pending:
            if col in pending:
                text, remaining = pending[col]
                row_out.append(text)
                pending[col] = (text, remaining - 1) if remaining > 1 else None
                if pending[col] is None:
                    del pending[col]
                col += 1
                continue
            text = current.get_text(" ", strip=True)
            colspan = int(current.get("colspan", 1))
            rowspan = int(current.get("rowspan", 1))
            for k in range(colspan):
                row_out.append(text)
                if rowspan > 1:
                    pending[col + k] = (text, rowspan - 1)
            col += colspan
            current = next(cell_iter, None)
        grid.append(row_out)

    return grid[0], grid[1:]


def fetch_regulatory_limits() -> dict[str, dict]:
    """
    Récupère et parse la table de comparaison. Retourne un dict
    {nom_organisme: {feature: valeur}} pour chaque organisme ayant au
    moins une feature exploitable.
    """
    resp = requests.get(SOURCE_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    tables = soup.find_all("table", class_="wikitable")
    if not tables:
        raise RuntimeError("Table 'wikitable' introuvable — structure de la page modifiée.")

    header, rows = _parse_grid(tables[0])
    organismes = [h for h in header if h not in ("Parameter", "Table") and h.strip()]

    par_organisme: dict[str, dict] = {name: {f: None for f in FEATURES} for name in organismes}

    for row in rows:
        if not row:
            continue
        label = row[0].lower()
        # \b (frontière de mot) plutôt qu'un simple "in" : une clé courte
        # comme "ph" matche sinon en sous-chaîne dans "sulPHate" et écrase
        # la mauvaise feature — trouvé en testant ce script contre la page
        # réelle, pas en le relisant.
        feature = next((v for k, v in ROW_MAP.items()
                         if re.search(rf"\b{re.escape(k)}\b", label)), None)
        if not feature:
            continue
        row_dict = dict(zip(header, row))
        for organisme in organismes:
            value = _extract_number(row_dict.get(organisme, ""))
            if value is not None:
                par_organisme[organisme][feature] = value

    # Ne garde que les organismes avec au moins une feature exploitable
    return {name: mesures for name, mesures in par_organisme.items()
            if any(v is not None for v in mesures.values())}


def _get_or_create_system_client(db) -> Client:
    client = db.query(Client).filter_by(id_client=SYSTEM_CLIENT_ID).first()
    if client:
        return client
    client = Client(
        id_client=SYSTEM_CLIENT_ID,
        denomination=SYSTEM_CLIENT_NAME,
        adresse=SYSTEM_CLIENT_ADDR,
        actif=True,
        rgpd_consent=True,
        rgpd_consent_at=utcnow(),
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    print(f"  ✓  Client système créé : {SYSTEM_CLIENT_ID}")
    return client


def import_limits(db, dry_run: bool) -> int:
    par_organisme = fetch_regulatory_limits()
    print(f"  {len(par_organisme)} organisme(s) avec au moins une valeur exploitable.")

    if dry_run:
        for organisme, mesures in par_organisme.items():
            missing = [f for f in FEATURES if mesures[f] is None]
            print(f"  · {organisme} — features manquantes : {missing or 'aucune'}")
        return 0

    client = _get_or_create_system_client(db)
    inserted = 0

    for organisme, mesures in par_organisme.items():
        tag = f"[scraping:{organisme}]"
        existing = (db.query(Prelevement)
                      .filter(Prelevement.client_id == client.id,
                              Prelevement.observations.contains(tag))
                      .first())
        if existing:
            continue

        missing = [f for f in FEATURES if mesures[f] is None]
        prev = _save_prelevement(
            db, client, mesures, IngestionSource.SCRAPING,
            ocr_data={
                "lieu": f"Valeurs limites — {organisme}",
                "warnings": [f"Paramètre non disponible dans la table source : {m}" for m in missing],
                "observations": f"{tag} Import scraping — {SOURCE_URL}",
            },
        )

        try:
            result = run_prediction(mesures)
            _save_prediction(db, prev, result)
        except ValueError:
            pass  # features manquantes — attendu pour la plupart des organismes

        inserted += 1
        print(f"  ✓  {organisme} ({len(missing)} feature(s) manquante(s))")

    return inserted


def main():
    parser = argparse.ArgumentParser(
        description="Importe des valeurs limites réglementaires par scraping (Wikipedia)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Affiche le résumé sans rien insérer en base")
    args = parser.parse_args()

    print("═" * 60)
    print("  VigiEau — Import scraping (valeurs limites réglementaires)")
    print("═" * 60)

    init_db()
    db = SessionLocal()
    try:
        inserted = import_limits(db, args.dry_run)
    finally:
        db.close()

    print("═" * 60)
    print("  Terminé." if args.dry_run else f"  Terminé — {inserted} prélèvement(s) inséré(s).")
    print("═" * 60)


if __name__ == "__main__":
    main()
