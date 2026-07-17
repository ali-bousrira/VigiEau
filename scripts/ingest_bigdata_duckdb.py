"""
scripts/ingest_bigdata_duckdb.py — Importe un échantillon depuis un système
big data (DuckDB + Parquet), source #4 des 5 exigées pour C1.

Le jeu de données Kaggle historique du projet (`water_potability.csv`,
déjà dans le dépôt, utilisé pour l'entraînement du modèle) est converti en
Parquet — le format explicitement recommandé par le REAC pour ce type de
source ("essayez d'avoir un format dédié, comme Parquet") — puis requêté
via **DuckDB** plutôt qu'un simple `pandas.read_csv`. L'objectif de cette
compétence est de prouver la maîtrise de la techno big data, pas de
trouver un vrai gisement pétaoctet-scale ("Si vous n'avez rien à mettre
dans un système big data, importez-y des données tabulaires standard.
L'important est de prouver votre maîtrise des technos associées.").

Les colonnes du CSV Kaggle correspondent déjà exactement aux 9 features
VigiEau (`ph, Hardness, Solids, Chloramines, Sulfate, Conductivity,
Organic_carbon, Trihalomethanes, Turbidity`) — l'harmonisation ici porte
sur le FORMAT (CSV -> Parquet -> requêtage colonne) plutôt que sur les
noms de colonnes, contrairement aux sources scraping/DB de ce même lot.

Usage :
    python scripts/ingest_bigdata_duckdb.py
    python scripts/ingest_bigdata_duckdb.py --sample 20 --dry-run
"""

import sys
import os
import argparse
import logging

import duckdb

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import SessionLocal, init_db, Client, Prelevement, IngestionSource, utcnow
from routes import _save_prelevement, _save_prediction, run_prediction

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

logger = logging.getLogger(__name__)

ROOT_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH     = os.path.join(ROOT_DIR, "water_potability.csv")
PARQUET_PATH = os.path.join(ROOT_DIR, "water_potability.parquet")

SYSTEM_CLIENT_ID   = "OPENDATA-BIGDATA"
SYSTEM_CLIENT_NAME = "Import big data (DuckDB/Parquet)"
SYSTEM_CLIENT_ADDR = "Jeu de données Kaggle water_potability.csv, requêté via DuckDB"

FEATURES = [
    "ph", "Hardness", "Solids", "Chloramines", "Sulfate",
    "Conductivity", "Organic_carbon", "Trihalomethanes", "Turbidity",
]


def ensure_parquet() -> None:
    """Convertit le CSV en Parquet s'il n'existe pas déjà (idempotent)."""
    if os.path.exists(PARQUET_PATH):
        return
    if not os.path.exists(CSV_PATH):
        raise RuntimeError(f"{CSV_PATH} introuvable — impossible de générer le Parquet.")
    con = duckdb.connect()
    try:
        con.execute(
            f"COPY (SELECT * FROM read_csv_auto('{CSV_PATH}')) "
            f"TO '{PARQUET_PATH}' (FORMAT PARQUET)"
        )
    finally:
        con.close()
    logger.info("Parquet généré : %s", PARQUET_PATH)


def fetch_complete_sample(sample_size: int) -> list[dict]:
    """
    Requête DuckDB sur le fichier Parquet : ne garde que les lignes ayant
    les 9 features renseignées (pas de None dans ce jeu de données, mais
    le filtre reste explicite plutôt qu'implicite), échantillon aléatoire
    reproductible.
    """
    ensure_parquet()
    cols = ", ".join(FEATURES)
    con = duckdb.connect()
    try:
        query = f"""
            SELECT {cols}
            FROM read_parquet('{PARQUET_PATH}')
            WHERE {" AND ".join(f"{f} IS NOT NULL" for f in FEATURES)}
            USING SAMPLE {sample_size} (reservoir, 42)
        """
        cursor = con.execute(query)
        rows = cursor.fetchall()
        col_names = [d[0] for d in cursor.description]
    finally:
        con.close()
    return [dict(zip(col_names, row)) for row in rows]


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


def import_bigdata_sample(db, sample_size: int, dry_run: bool) -> int:
    rows = fetch_complete_sample(sample_size)
    print(f"  {len(rows)} ligne(s) échantillonnée(s) depuis le Parquet via DuckDB.")

    if dry_run:
        for i, row in enumerate(rows):
            print(f"  · échantillon {i} — ph={row['ph']:.2f}")
        return 0

    client = _get_or_create_system_client(db)
    inserted = 0

    for i, mesures in enumerate(rows):
        tag = f"[bigdata:{i}]"
        existing = (db.query(Prelevement)
                      .filter(Prelevement.client_id == client.id,
                              Prelevement.observations.contains(tag))
                      .first())
        if existing:
            continue

        prev = _save_prelevement(
            db, client, mesures, IngestionSource.BIGDATA,
            ocr_data={
                "lieu": "Échantillon Parquet (DuckDB)",
                "warnings": [],
                "observations": f"{tag} Import big data — {os.path.basename(PARQUET_PATH)}",
            },
        )

        result = run_prediction(mesures)   # les 9 features sont toujours présentes ici
        _save_prediction(db, prev, result)

        inserted += 1

    return inserted


def main():
    parser = argparse.ArgumentParser(
        description="Importe un échantillon depuis water_potability.parquet via DuckDB")
    parser.add_argument("--sample", type=int, default=20,
                        help="Nombre de lignes à échantillonner (défaut : 20)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Affiche le résumé sans rien insérer en base")
    args = parser.parse_args()

    print("═" * 60)
    print("  VigiEau — Import big data (DuckDB + Parquet)")
    print("═" * 60)

    init_db()
    db = SessionLocal()
    try:
        inserted = import_bigdata_sample(db, args.sample, args.dry_run)
    finally:
        db.close()

    print("═" * 60)
    print("  Terminé." if args.dry_run else f"  Terminé — {inserted} prélèvement(s) inséré(s).")
    print("═" * 60)


if __name__ == "__main__":
    main()
