"""
tests/test_ingest_bigdata_duckdb.py — Tests du script d'import big data
(C1, source big data via DuckDB/Parquet).

Utilise un petit CSV synthétique (pas le vrai water_potability.csv à
~3000 lignes) pour rester rapide et isolé.
"""

import os
import sys
import csv
from unittest.mock import MagicMock

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import predict_service
from db import SessionLocal, init_db, Client, Prelevement, IngestionSource
import ingest_bigdata_duckdb as bigdata

_mock_model  = MagicMock()
_mock_model.predict.return_value       = np.array([1])
_mock_model.predict_proba.return_value = np.array([[0.1, 0.9]])
_mock_scaler = MagicMock()
_mock_scaler.transform.side_effect = lambda x: x

predict_service._model         = _mock_model
predict_service._scaler        = _mock_scaler
predict_service._model_version = "mock"

init_db()

_ROWS = [
    {"ph": 7.1, "Hardness": 200.0, "Solids": 18000.0, "Chloramines": 7.0,
     "Sulfate": 300.0, "Conductivity": 400.0, "Organic_carbon": 14.0,
     "Trihalomethanes": 60.0, "Turbidity": 3.5, "Potability": 1},
    {"ph": 6.5, "Hardness": 210.0, "Solids": 19000.0, "Chloramines": 7.5,
     "Sulfate": 310.0, "Conductivity": 410.0, "Organic_carbon": 15.0,
     "Trihalomethanes": 65.0, "Turbidity": 4.0, "Potability": 0},
    {"ph": 8.0, "Hardness": 190.0, "Solids": 17000.0, "Chloramines": 6.5,
     "Sulfate": 290.0, "Conductivity": 390.0, "Organic_carbon": 13.0,
     "Trihalomethanes": 55.0, "Turbidity": 3.0, "Potability": 1},
]


@pytest.fixture
def fake_csv(tmp_path, monkeypatch):
    csv_path = tmp_path / "water_potability.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(_ROWS[0].keys()))
        writer.writeheader()
        writer.writerows(_ROWS)
    parquet_path = tmp_path / "water_potability.parquet"
    monkeypatch.setattr(bigdata, "CSV_PATH", str(csv_path))
    monkeypatch.setattr(bigdata, "PARQUET_PATH", str(parquet_path))
    return csv_path, parquet_path


class TestEnsureParquet:

    def test_genere_le_parquet_si_absent(self, fake_csv):
        _, parquet_path = fake_csv
        assert not os.path.exists(parquet_path)
        bigdata.ensure_parquet()
        assert os.path.exists(parquet_path)

    def test_ne_regenere_pas_si_deja_present(self, fake_csv):
        _, parquet_path = fake_csv
        bigdata.ensure_parquet()
        mtime_first = os.path.getmtime(parquet_path)
        bigdata.ensure_parquet()
        assert os.path.getmtime(parquet_path) == mtime_first

    def test_erreur_explicite_si_csv_absent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bigdata, "CSV_PATH", str(tmp_path / "nope.csv"))
        monkeypatch.setattr(bigdata, "PARQUET_PATH", str(tmp_path / "nope.parquet"))
        with pytest.raises(RuntimeError, match="introuvable"):
            bigdata.ensure_parquet()


class TestFetchCompleteSample:

    def test_echantillon_a_les_9_features(self, fake_csv):
        rows = bigdata.fetch_complete_sample(2)
        assert len(rows) == 2
        assert set(bigdata.FEATURES) <= set(rows[0].keys())

    def test_echantillon_borne_par_la_taille_reelle(self, fake_csv):
        # seulement 3 lignes dans le CSV de test, demander plus ne doit pas planter
        rows = bigdata.fetch_complete_sample(100)
        assert len(rows) == 3


class TestImportBigdataSample:

    def test_dry_run_ne_persiste_rien(self, fake_csv):
        db = SessionLocal()
        try:
            inserted = bigdata.import_bigdata_sample(db, sample_size=2, dry_run=True)
            assert inserted == 0
            assert db.query(Client).filter_by(id_client="OPENDATA-BIGDATA").first() is None
        finally:
            db.close()

    def test_import_cree_des_prelevements_puis_reimport_est_idempotent(self, fake_csv):
        # Les deux imports doivent être dans le même test : la DB de test
        # est partagée entre méthodes (pas de reset), donc un import "seul"
        # dans un test séparé se comporte comme un réimport si un test
        # précédent a déjà inséré les mêmes tags [bigdata:0]/[bigdata:1].
        db = SessionLocal()
        try:
            first = bigdata.import_bigdata_sample(db, sample_size=2, dry_run=False)
            second = bigdata.import_bigdata_sample(db, sample_size=2, dry_run=False)
            assert first == 2
            assert second == 0

            client = db.query(Client).filter_by(id_client="OPENDATA-BIGDATA").first()
            assert client is not None

            matches = db.query(Prelevement).filter(
                Prelevement.client_id == client.id,
                Prelevement.observations.contains("[bigdata:"),
            ).all()
            assert len(matches) == 2
            assert all(m.source == IngestionSource.BIGDATA for m in matches)
        finally:
            db.close()
