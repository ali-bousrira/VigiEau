"""
tests/test_ingest_hubeau.py — Tests du script d'import Hub'Eau (C1, source ouverte).

Le payload de test reprend la forme réelle de l'API Hub'Eau (vérifiée par un
appel direct sur la commune 75056/Paris), réduite à un seul `code_prelevement`
couvrant les 8 paramètres mappés + un paramètre non mappé (ECOLI) pour
vérifier qu'il est ignoré sans erreur.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import predict_service
from db import SessionLocal, init_db, Client, Prelevement, IngestionSource
import ingest_hubeau

_mock_model  = MagicMock()
_mock_model.predict.return_value       = np.array([1])
_mock_model.predict_proba.return_value = np.array([[0.1, 0.9]])
_mock_scaler = MagicMock()
_mock_scaler.transform.side_effect = lambda x: x

predict_service._model         = _mock_model
predict_service._scaler        = _mock_scaler
predict_service._model_version = "mock"

init_db()

CODE_PRELEVEMENT = "07500215464"

HUBEAU_ROWS = [
    {"code_prelevement": CODE_PRELEVEMENT, "code_parametre_se": "ECOLI",
     "resultat_numerique": 0.0, "nom_commune": "PARIS", "code_commune": "75056",
     "date_prelevement": "2026-01-30T13:05:00", "conclusion_conformite_prelevement": "Conforme"},
    {"code_prelevement": CODE_PRELEVEMENT, "code_parametre_se": "PH",
     "resultat_numerique": 7.4, "nom_commune": "PARIS", "code_commune": "75056",
     "date_prelevement": "2026-01-30T13:05:00", "conclusion_conformite_prelevement": "Conforme"},
    {"code_prelevement": CODE_PRELEVEMENT, "code_parametre_se": "CDT25",
     "resultat_numerique": 410.0, "nom_commune": "PARIS", "code_commune": "75056",
     "date_prelevement": "2026-01-30T13:05:00", "conclusion_conformite_prelevement": "Conforme"},
    {"code_prelevement": CODE_PRELEVEMENT, "code_parametre_se": "TURBNFU",
     "resultat_numerique": 0.3, "nom_commune": "PARIS", "code_commune": "75056",
     "date_prelevement": "2026-01-30T13:05:00", "conclusion_conformite_prelevement": "Conforme"},
    {"code_prelevement": CODE_PRELEVEMENT, "code_parametre_se": "SO4",
     "resultat_numerique": 28.0, "nom_commune": "PARIS", "code_commune": "75056",
     "date_prelevement": "2026-01-30T13:05:00", "conclusion_conformite_prelevement": "Conforme"},
    {"code_prelevement": CODE_PRELEVEMENT, "code_parametre_se": "TH",
     "resultat_numerique": 20.9, "nom_commune": "PARIS", "code_commune": "75056",
     "date_prelevement": "2026-01-30T13:05:00", "conclusion_conformite_prelevement": "Conforme"},
    {"code_prelevement": CODE_PRELEVEMENT, "code_parametre_se": "CL2TOT",
     "resultat_numerique": 0.25, "nom_commune": "PARIS", "code_commune": "75056",
     "date_prelevement": "2026-01-30T13:05:00", "conclusion_conformite_prelevement": "Conforme"},
    {"code_prelevement": CODE_PRELEVEMENT, "code_parametre_se": "COT",
     "resultat_numerique": 1.2, "nom_commune": "PARIS", "code_commune": "75056",
     "date_prelevement": "2026-01-30T13:05:00", "conclusion_conformite_prelevement": "Conforme"},
    {"code_prelevement": CODE_PRELEVEMENT, "code_parametre_se": "THM4",
     "resultat_numerique": 42.0, "nom_commune": "PARIS", "code_commune": "75056",
     "date_prelevement": "2026-01-30T13:05:00", "conclusion_conformite_prelevement": "Conforme"},
]


def _mock_response(rows):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"count": len(rows), "next": None, "data": rows}
    return resp


class TestBuildMesures:

    def test_mapping_et_conversion_th(self):
        mesures, missing = ingest_hubeau._build_mesures(HUBEAU_ROWS)
        assert mesures["ph"] == 7.4
        assert mesures["Conductivity"] == 410.0
        assert mesures["Hardness"] == pytest.approx(209.0)   # 20.9 °f * 10
        assert mesures["Chloramines"] == 0.25

    def test_solids_toujours_absent(self):
        mesures, missing = ingest_hubeau._build_mesures(HUBEAU_ROWS)
        assert mesures["Solids"] is None
        assert "Solids" in missing

    def test_parametre_non_mappe_ignore(self):
        # ECOLI est présent dans HUBEAU_ROWS mais n'a pas d'entrée dans PARAM_MAP
        mesures, _ = ingest_hubeau._build_mesures(HUBEAU_ROWS)
        assert set(mesures) == set(ingest_hubeau.FEATURES)


class TestImportCommune:

    def test_dry_run_ne_persiste_rien(self):
        db = SessionLocal()
        try:
            with patch("ingest_hubeau.requests.get", return_value=_mock_response(HUBEAU_ROWS)):
                inserted = ingest_hubeau.import_commune(
                    db, "75056", "2026-01-01", "2026-02-01", max_pages=1, dry_run=True)
            assert inserted == 0
            assert db.query(Prelevement).filter(
                Prelevement.observations.contains(f"[hubeau:{CODE_PRELEVEMENT}]")
            ).count() == 0
        finally:
            db.close()

    def test_import_puis_reimport_est_idempotent(self):
        db = SessionLocal()
        try:
            with patch("ingest_hubeau.requests.get", return_value=_mock_response(HUBEAU_ROWS)):
                first = ingest_hubeau.import_commune(
                    db, "75056", "2026-01-01", "2026-02-01", max_pages=1, dry_run=False)
                second = ingest_hubeau.import_commune(
                    db, "75056", "2026-01-01", "2026-02-01", max_pages=1, dry_run=False)

            assert first == 1
            assert second == 0

            client = db.query(Client).filter_by(id_client="OPENDATA-HUBEAU").first()
            assert client is not None

            matches = db.query(Prelevement).filter(
                Prelevement.client_id == client.id,
                Prelevement.observations.contains(f"[hubeau:{CODE_PRELEVEMENT}]"),
            ).all()
            assert len(matches) == 1
            assert matches[0].source == IngestionSource.OPENDATA
        finally:
            db.close()
