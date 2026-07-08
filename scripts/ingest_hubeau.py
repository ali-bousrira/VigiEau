"""
scripts/ingest_hubeau.py — Importe des prélèvements depuis l'API ouverte Hub'Eau.

Source : Hub'Eau — Qualité de l'eau potable (résultats du contrôle sanitaire
des eaux distribuées), API publique gratuite, sans clé :
    https://hubeau.eaufrance.fr/api/v1/qualite_eau_potable/resultats_dis

Correspondance entre les paramètres Hub'Eau et les 9 features Waterflow
(vérifiée par appel réel sur la commune 75056 / Paris) :

    code_parametre_se | feature Waterflow | fiabilité
    ------------------|-------------------|----------------------------------
    PH                | ph                | directe
    CDT25             | Conductivity      | directe
    TURBNFU           | Turbidity         | approximative (NFU proche de NTU)
    SO4               | Sulfate           | directe
    TH                | Hardness          | conversion °f → mg/L CaCO3 (× 10)
    CL2TOT            | Chloramines       | approximation (chlore total utilisé
                       |                   | comme proxy, pas une équivalence
                       |                   | chimique exacte)
    COT               | Organic_carbon    | directe
    THM4              | Trihalomethanes   | directe
    (aucun)           | Solids            | pas d'équivalent en contrôle
                       |                   | sanitaire français — reste None

Usage :
    python scripts/ingest_hubeau.py --commune 75056
    python scripts/ingest_hubeau.py --commune 75056 --dry-run
    python scripts/ingest_hubeau.py --commune 75056 --date-min 2025-01-01 --date-max 2025-12-31
"""

import sys
import os
import argparse
import logging
from datetime import datetime, timedelta

import requests

# Ajoute la racine du projet au chemin Python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import SessionLocal, init_db, Client, Prelevement, IngestionSource, utcnow
from routes import _save_prelevement, _save_prediction, run_prediction

try:
    sys.stdout.reconfigure(encoding="utf-8")   # évite un crash sur console Windows cp1252
except (AttributeError, ValueError):
    pass

logger = logging.getLogger(__name__)

HUBEAU_URL = "https://hubeau.eaufrance.fr/api/v1/qualite_eau_potable/resultats_dis"
PAGE_SIZE  = 500

SYSTEM_CLIENT_ID     = "OPENDATA-HUBEAU"
SYSTEM_CLIENT_NAME   = "Import Hub'Eau (open data)"
SYSTEM_CLIENT_ADDR   = "Ministère chargé de la Santé — Hub'Eau (data.eaufrance.fr)"

FEATURES = [
    "ph", "Hardness", "Solids", "Chloramines", "Sulfate",
    "Conductivity", "Organic_carbon", "Trihalomethanes", "Turbidity",
]

# code_parametre_se Hub'Eau -> (feature Waterflow, fonction de conversion)
PARAM_MAP = {
    "PH":     ("ph",              None),
    "CDT25":  ("Conductivity",    None),
    "TURBNFU":("Turbidity",       None),
    "SO4":    ("Sulfate",         None),
    "TH":     ("Hardness",        lambda v: v * 10.0),   # degré français -> mg/L CaCO3
    "CL2TOT": ("Chloramines",     None),
    "COT":    ("Organic_carbon",  None),
    "THM4":   ("Trihalomethanes", None),
    # Pas de paramètre "Solids" (matières dissoutes totales) en contrôle
    # sanitaire français — la feature reste toujours None.
}


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


def _fetch_resultats(commune: str, date_min: str, date_max: str, max_pages: int) -> list[dict]:
    """Récupère toutes les pages de résultats DIS pour une commune et une période."""
    rows = []
    page = 1
    while page <= max_pages:
        resp = requests.get(HUBEAU_URL, params={
            "code_commune":        commune,
            "date_min_prelevement": date_min,
            "date_max_prelevement": date_max,
            "page":                page,
            "size":                PAGE_SIZE,
        }, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        rows.extend(payload.get("data", []))
        logger.info("Hub'Eau page %d/%s — %d lignes cumulées", page, max_pages, len(rows))
        if not payload.get("next"):
            break
        page += 1
    return rows


def _group_by_prelevement(rows: list[dict]) -> dict:
    groups = {}
    for row in rows:
        code = row.get("code_prelevement")
        if code is None:
            continue
        groups.setdefault(code, []).append(row)
    return groups


def _build_mesures(rows: list[dict]) -> tuple[dict, list[str]]:
    """Construit le dict des 9 features à partir des lignes d'un même prélèvement."""
    mesures = {f: None for f in FEATURES}
    for row in rows:
        mapping = PARAM_MAP.get(row.get("code_parametre_se"))
        if not mapping:
            continue
        feature, convert = mapping
        value = row.get("resultat_numerique")
        if value is None:
            continue
        mesures[feature] = convert(value) if convert else value
    missing = [f for f in FEATURES if mesures[f] is None]
    return mesures, missing


def import_commune(db, commune: str, date_min: str, date_max: str,
                    max_pages: int, dry_run: bool) -> int:
    rows = _fetch_resultats(commune, date_min, date_max, max_pages)
    groups = _group_by_prelevement(rows)
    print(f"  {len(rows)} lignes reçues, {len(groups)} prélèvements distincts.")

    if dry_run:
        for code, group_rows in groups.items():
            mesures, missing = _build_mesures(group_rows)
            print(f"  · {code} — features manquantes : {missing or 'aucune'}")
        return 0

    client = _get_or_create_system_client(db)
    inserted = 0

    for code, group_rows in groups.items():
        tag = f"[hubeau:{code}]"
        existing = (db.query(Prelevement)
                      .filter(Prelevement.client_id == client.id,
                              Prelevement.observations.contains(tag))
                      .first())
        if existing:
            continue

        first = group_rows[0]
        mesures, missing = _build_mesures(group_rows)
        observations = (
            f"{tag} Import Hub'Eau — commune {first.get('nom_commune')} "
            f"({first.get('code_commune')}). Conclusion sanitaire : "
            f"{first.get('conclusion_conformite_prelevement')}"
        )

        prev = _save_prelevement(
            db, client, mesures, IngestionSource.OPENDATA,
            ocr_data={
                "lieu":             first.get("nom_commune"),
                "date_prelevement": first.get("date_prelevement"),
                "warnings":         [f"Paramètre non disponible depuis Hub'Eau : {m}" for m in missing],
                "observations":     observations,
            },
        )

        try:
            result = run_prediction(mesures)
            _save_prediction(db, prev, result)
        except ValueError:
            pass  # features manquantes (au minimum Solids) — attendu

        inserted += 1
        print(f"  ✓  {code} — {first.get('nom_commune')} ({len(missing)} feature(s) manquante(s))")

    return inserted


def main():
    parser = argparse.ArgumentParser(
        description="Importe des prélèvements Hub'Eau (qualité de l'eau potable)")
    parser.add_argument("--commune", required=True, help="Code INSEE de la commune")
    parser.add_argument("--date-min", default=None,
                        help="Date de début (YYYY-MM-DD), défaut : 1 an glissant")
    parser.add_argument("--date-max", default=None,
                        help="Date de fin (YYYY-MM-DD), défaut : aujourd'hui")
    parser.add_argument("--max-pages", type=int, default=5,
                        help="Garde-fou anti-moissonnage (défaut : 5 pages de 500 lignes)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Affiche le résumé sans rien insérer en base")
    args = parser.parse_args()

    date_max = args.date_max or datetime.utcnow().strftime("%Y-%m-%d")
    date_min = args.date_min or (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")

    print("═" * 60)
    print("  Waterflow 2 — Import Hub'Eau")
    print("═" * 60)
    print(f"  Commune : {args.commune}  |  Période : {date_min} → {date_max}")

    init_db()
    db = SessionLocal()
    try:
        inserted = import_commune(db, args.commune, date_min, date_max,
                                   args.max_pages, args.dry_run)
    finally:
        db.close()

    print("═" * 60)
    print("  Terminé." if args.dry_run else f"  Terminé — {inserted} prélèvement(s) inséré(s).")
    print("═" * 60)


if __name__ == "__main__":
    main()
