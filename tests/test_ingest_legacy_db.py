"""
tests/test_ingest_legacy_db.py — Tests du script d'import base légataire
(C1, source DB).

Utilise une base SQLite temporaire (pas legacy_system.db lui-même) pour
rester isolé des autres tests et de tout état local.
"""

import os
import sys
import sqlite3
from unittest.mock import MagicMock

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import predict_service
from db import SessionLocal, init_db, Client, Prelevement, IngestionSource
import ingest_legacy_db

_mock_model  = MagicMock()
_mock_model.predict.return_value       = np.array([1])
_mock_model.predict_proba.return_value = np.array([[0.1, 0.9]])
_mock_scaler = MagicMock()
_mock_scaler.transform.side_effect = lambda x: x

predict_service._model         = _mock_model
predict_service._scaler        = _mock_scaler
predict_service._model_version = "mock"

init_db()

ROW = {
    "id_releve": 1, "commune": "Commune de Test", "date_releve": "12/03/2024",
    "acidite": 7.3, "durete_totale": 198.0, "matieres_dissoutes": 17200.0,
    "chlore_combine": 6.8, "sulfates": 295.0, "conductivite": 388.0,
    "carbone_organique": 12.9, "trihalomethanes_totaux": 61.0, "turbidite": 3.2,
}


class TestParseDateFr:

    def test_conversion_reussie(self):
        assert ingest_legacy_db._parse_date_fr("12/03/2024") == "2024-03-12"

    def test_format_invalide_renvoie_none(self):
        assert ingest_legacy_db._parse_date_fr("2024-03-12") is None
        assert ingest_legacy_db._parse_date_fr(None) is None


class TestBuildMesures:

    def test_toutes_les_features_mappees(self):
        mesures, missing = ingest_legacy_db._build_mesures(ROW)
        assert missing == []
        assert mesures["ph"] == 7.3
        assert mesures["Hardness"] == 198.0
        assert mesures["Turbidity"] == 3.2

    def test_valeur_manquante_reportee(self):
        row = dict(ROW)
        row["sulfates"] = None
        mesures, missing = ingest_legacy_db._build_mesures(row)
        assert "Sulfate" in missing
        assert mesures["Sulfate"] is None


class TestImportLegacy:

    @pytest.fixture
    def legacy_db(self, tmp_path, monkeypatch):
        path = tmp_path / "legacy_test.db"
        conn = sqlite3.connect(path)
        conn.executescript(
            """CREATE TABLE releves_qualite_eau (
                id_releve INTEGER PRIMARY KEY, commune TEXT, date_releve TEXT,
                acidite REAL, durete_totale REAL, matieres_dissoutes REAL,
                chlore_combine REAL, sulfates REAL, conductivite REAL,
                carbone_organique REAL, trihalomethanes_totaux REAL, turbidite REAL
            )"""
        )
        conn.execute(
            """INSERT INTO releves_qualite_eau VALUES
               (1, 'Commune de Test', '12/03/2024', 7.3, 198.0, 17200.0, 6.8, 295.0, 388.0, 12.9, 61.0, 3.2)"""
        )
        conn.commit()
        conn.close()
        monkeypatch.setattr(ingest_legacy_db, "LEGACY_DB_PATH", str(path))
        return path

    def test_fichier_absent_leve_une_erreur_explicite(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ingest_legacy_db, "LEGACY_DB_PATH", str(tmp_path / "nope.db"))
        with pytest.raises(RuntimeError, match="seed_legacy_db"):
            ingest_legacy_db.fetch_legacy_rows()

    def test_dry_run_ne_persiste_rien(self, legacy_db):
        db = SessionLocal()
        try:
            inserted = ingest_legacy_db.import_legacy(db, dry_run=True)
            assert inserted == 0
            assert db.query(Client).filter_by(id_client="OPENDATA-LEGACY").first() is None
        finally:
            db.close()

    def test_import_puis_reimport_est_idempotent(self, legacy_db):
        db = SessionLocal()
        try:
            first = ingest_legacy_db.import_legacy(db, dry_run=False)
            second = ingest_legacy_db.import_legacy(db, dry_run=False)

            assert first == 1
            assert second == 0

            client = db.query(Client).filter_by(id_client="OPENDATA-LEGACY").first()
            assert client is not None

            matches = db.query(Prelevement).filter(
                Prelevement.client_id == client.id,
                Prelevement.observations.contains("[legacy:1]"),
            ).all()
            assert len(matches) == 1
            assert matches[0].source == IngestionSource.LEGACY_DB
            assert matches[0].lieu == "Commune de Test"
            assert matches[0].date_prelevement.strftime("%Y-%m-%d") == "2024-03-12"
        finally:
            db.close()
