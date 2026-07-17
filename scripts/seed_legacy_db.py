"""
scripts/seed_legacy_db.py — Génère une base SQLite représentant un ancien
système départemental de suivi de la qualité de l'eau, utilisée comme
source #3 par scripts/ingest_legacy_db.py (source DB pour C1).

Schéma volontairement différent de celui de VigiEau (noms de colonnes en
français abrégé, dates au format français DD/MM/YYYY) pour que
l'harmonisation (C3) soit réelle, pas simulée par une simple copie de
colonnes identiques.

Usage :
    python scripts/seed_legacy_db.py
"""

import os
import sqlite3

LEGACY_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "legacy_system.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS releves_qualite_eau (
    id_releve            INTEGER PRIMARY KEY AUTOINCREMENT,
    commune               TEXT NOT NULL,
    date_releve            TEXT NOT NULL,  -- format DD/MM/YYYY
    acidite                REAL,           -- pH
    durete_totale          REAL,           -- mg/L CaCO3 (déjà converti, contrairement à Hub'Eau)
    matieres_dissoutes     REAL,           -- mg/L
    chlore_combine         REAL,           -- mg/L
    sulfates               REAL,           -- mg/L
    conductivite           REAL,           -- µS/cm
    carbone_organique      REAL,           -- mg/L
    trihalomethanes_totaux REAL,           -- µg/L
    turbidite              REAL            -- NTU
);
"""

SAMPLES = [
    ("Commune de Digne-les-Bains",  "12/03/2024", 7.3, 198.0, 17200.0, 6.8, 295.0, 388.0, 12.9, 61.0, 3.2),
    ("Commune de Digne-les-Bains",  "04/09/2024", 7.1, 210.5, 19800.0, 7.4, 302.0, 401.0, 13.5, 58.5, 4.1),
    ("Syndicat des Eaux du Verdon", "22/06/2024", 6.9, 175.0, 15400.0, 8.1, 260.0, 355.0, 11.2, 70.2, 5.8),
    ("Syndicat des Eaux du Verdon", "15/11/2024", 7.6, 188.2, 16100.0, 5.9, 271.0, 362.0, 10.8, 63.0, 3.9),
]


def seed(reset: bool = False):
    if reset and os.path.exists(LEGACY_DB_PATH):
        os.remove(LEGACY_DB_PATH)

    conn = sqlite3.connect(LEGACY_DB_PATH)
    try:
        conn.executescript(SCHEMA)
        existing = conn.execute("SELECT COUNT(*) FROM releves_qualite_eau").fetchone()[0]
        if existing:
            print(f"  ⚠  {existing} relevé(s) déjà présent(s) — pas de doublon ajouté.")
            return
        conn.executemany(
            """INSERT INTO releves_qualite_eau
               (commune, date_releve, acidite, durete_totale, matieres_dissoutes,
                chlore_combine, sulfates, conductivite, carbone_organique,
                trihalomethanes_totaux, turbidite)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            SAMPLES,
        )
        conn.commit()
        print(f"  ✓  {len(SAMPLES)} relevé(s) historique(s) inséré(s) dans {LEGACY_DB_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    print("═" * 60)
    print("  VigiEau — Seed base légataire (legacy_system.db)")
    print("═" * 60)
    seed()
    print("═" * 60)
