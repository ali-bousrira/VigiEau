"""
scripts/ingest_legacy_db.py — Importe des prélèvements historiques depuis
une base SQLite représentant un ancien système départemental (source #3
des 5 exigées pour C1, une source "DB").

Génération de la base source : scripts/seed_legacy_db.py (schéma distinct
de VigiEau, français abrégé, gitignorée comme les autres .db — voir
.gitignore).

Correspondance entre les colonnes du système légataire et les 9 features
VigiEau — harmonisation réelle (C3), pas une copie de colonnes identiques :

    Colonne legacy_system.db  | feature VigiEau   | fiabilité
    ---------------------------|-------------------|----------------------
    acidite                    | ph                | directe
    durete_totale               | Hardness          | directe (déjà en
                                |                   | mg/L CaCO3 dans ce
                                |                   | système, contrairement
                                |                   | à Hub'Eau qui donne
                                |                   | des degrés français —
                                |                   | pas de conversion ici)
    matieres_dissoutes         | Solids            | directe
    chlore_combine              | Chloramines       | directe
    sulfates                    | Sulfate           | directe
    conductivite                | Conductivity      | directe
    carbone_organique           | Organic_carbon    | directe
    trihalomethanes_totaux      | Trihalomethanes   | directe
    turbidite                   | Turbidity         | directe
    date_releve (DD/MM/YYYY)    | date_prelevement  | reformatage de date
                                |                   | uniquement (français
                                |                   | -> ISO 8601)

Ce système historique couvre les 9 features (contrairement à Hub'Eau ou
au scraping, partiels) — utile pour montrer que la complétude dépend de
la source, pas d'un choix arbitraire de mapping.

Usage :
    python scripts/ingest_legacy_db.py
    python scripts/ingest_legacy_db.py --dry-run
"""

import sys
import os
import sqlite3
import argparse
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import SessionLocal, init_db, Client, Prelevement, IngestionSource, utcnow
from routes import _save_prelevement, _save_prediction, run_prediction

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

logger = logging.getLogger(__name__)

LEGACY_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "legacy_system.db")

SYSTEM_CLIENT_ID   = "OPENDATA-LEGACY"
SYSTEM_CLIENT_NAME = "Import base légataire (open data)"
SYSTEM_CLIENT_ADDR = "Ancien système départemental de suivi qualité de l'eau"

FEATURES = [
    "ph", "Hardness", "Solids", "Chloramines", "Sulfate",
    "Conductivity", "Organic_carbon", "Trihalomethanes", "Turbidity",
]

# colonne legacy -> feature VigiEau
COLUMN_MAP = {
    "acidite":                "ph",
    "durete_totale":           "Hardness",
    "matieres_dissoutes":     "Solids",
    "chlore_combine":          "Chloramines",
    "sulfates":                "Sulfate",
    "conductivite":            "Conductivity",
    "carbone_organique":       "Organic_carbon",
    "trihalomethanes_totaux":  "Trihalomethanes",
    "turbidite":               "Turbidity",
}


def _parse_date_fr(date_str: str) -> str | None:
    """DD/MM/YYYY (format du système legacy) -> YYYY-MM-DD (ISO, attendu par _save_prelevement)."""
    try:
        return datetime.strptime(date_str, "%d/%m/%Y").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def fetch_legacy_rows() -> list[dict]:
    if not os.path.exists(LEGACY_DB_PATH):
        raise RuntimeError(
            f"{LEGACY_DB_PATH} introuvable — lancez d'abord "
            "`python scripts/seed_legacy_db.py`."
        )
    conn = sqlite3.connect(LEGACY_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM releves_qualite_eau").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _build_mesures(row: dict) -> tuple[dict, list[str]]:
    mesures = {f: None for f in FEATURES}
    for legacy_col, feature in COLUMN_MAP.items():
        value = row.get(legacy_col)
        if value is not None:
            mesures[feature] = value
    missing = [f for f in FEATURES if mesures[f] is None]
    return mesures, missing


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


def import_legacy(db, dry_run: bool) -> int:
    rows = fetch_legacy_rows()
    print(f"  {len(rows)} relevé(s) legacy trouvé(s).")

    if dry_run:
        for row in rows:
            mesures, missing = _build_mesures(row)
            print(f"  · id_releve={row['id_releve']} ({row['commune']}) — "
                  f"features manquantes : {missing or 'aucune'}")
        return 0

    client = _get_or_create_system_client(db)
    inserted = 0

    for row in rows:
        tag = f"[legacy:{row['id_releve']}]"
        existing = (db.query(Prelevement)
                      .filter(Prelevement.client_id == client.id,
                              Prelevement.observations.contains(tag))
                      .first())
        if existing:
            continue

        mesures, missing = _build_mesures(row)
        date_iso = _parse_date_fr(row.get("date_releve"))

        prev = _save_prelevement(
            db, client, mesures, IngestionSource.LEGACY_DB,
            ocr_data={
                "lieu": row.get("commune"),
                "date_prelevement": date_iso,
                "warnings": [f"Paramètre non disponible dans le système legacy : {m}" for m in missing],
                "observations": f"{tag} Import base légataire (SQLite, id_releve={row['id_releve']})",
            },
        )

        try:
            result = run_prediction(mesures)
            _save_prediction(db, prev, result)
        except ValueError:
            pass

        inserted += 1
        print(f"  ✓  id_releve={row['id_releve']} — {row['commune']} "
              f"({len(missing)} feature(s) manquante(s))")

    return inserted


def main():
    parser = argparse.ArgumentParser(
        description="Importe des prélèvements depuis la base légataire (legacy_system.db)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Affiche le résumé sans rien insérer en base")
    args = parser.parse_args()

    print("═" * 60)
    print("  VigiEau — Import base légataire (source DB)")
    print("═" * 60)

    init_db()
    db = SessionLocal()
    try:
        inserted = import_legacy(db, args.dry_run)
    finally:
        db.close()

    print("═" * 60)
    print("  Terminé." if args.dry_run else f"  Terminé — {inserted} prélèvement(s) inséré(s).")
    print("═" * 60)


if __name__ == "__main__":
    main()
