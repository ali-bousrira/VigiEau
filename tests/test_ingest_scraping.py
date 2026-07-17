"""
tests/test_ingest_scraping.py — Tests du script d'import scraping (C1, source
web scraping).

Le HTML de test reprend la structure réelle de la table Wikipédia
"Comparison of parametric values" (colonnes fusionnées via rowspan/colspan
incluses), vérifiée par un appel réel avant d'écrire le script — voir
scripts/ingest_scraping.py pour le détail de la correspondance. Aucun appel
réseau réel dans la suite pytest : `requests.get` est mocké.
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
import ingest_scraping

_mock_model  = MagicMock()
_mock_model.predict.return_value       = np.array([1])
_mock_model.predict_proba.return_value = np.array([[0.1, 0.9]])
_mock_scaler = MagicMock()
_mock_scaler.transform.side_effect = lambda x: x

predict_service._model         = _mock_model
predict_service._scaler        = _mock_scaler
predict_service._model_version = "mock"

init_db()

# Structure minimale mais fidèle à la vraie table : en-tête à 5 colonnes,
# une ligne "pH" avec rowspan sur la colonne "Table" (pour vérifier que le
# parseur de grille gère bien le décalage), une ligne "Sulphate" (dont le
# libellé contient "ph" en sous-chaîne — piège réel rencontré en testant
# contre la vraie page), une ligne non mappée à ignorer.
_FAKE_HTML = """
<html><body>
<h2>Comparison of parametric values</h2>
<table class="wikitable">
<tr><th>Parameter</th><th>Table</th><th>World Health Organization</th><th>European Union</th><th>India (BIS)</th></tr>
<tr><td rowspan="2">pH</td><td rowspan="2">-</td><td>6.5 to 8.5</td><td></td><td>6.5 to 8.5</td></tr>
<tr><td>-</td><td></td><td>-</td></tr>
<tr><td>Sulphate</td><td>SO4</td><td></td><td></td><td>200 mg/L</td></tr>
<tr><td>hardness</td><td>CaCO3</td><td></td><td></td><td>0-75 mg/L = soft</td></tr>
<tr><td>Arsenic</td><td>As</td><td>10 ug/L</td><td>10 ug/L</td><td>10 ug/L</td></tr>
</table>
</body></html>
"""


def _mock_response():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.text = _FAKE_HTML
    return resp


class TestFetchRegulatoryLimits:

    def test_ph_mappe_correctement_pas_confondu_avec_sulphate(self):
        with patch("ingest_scraping.requests.get", return_value=_mock_response()):
            par_organisme = ingest_scraping.fetch_regulatory_limits()
        # piège réel : "ph" en sous-chaîne de "sulPHate" écrasait la feature
        # "ph" avec la valeur Sulfate (200.0) de l'India (BIS) avant le
        # correctif \b (frontière de mot) — sans le fix, cette assertion
        # échoue avec ph == 200.0 au lieu du vrai milieu de plage 6.5-8.5.
        assert par_organisme["India (BIS)"]["ph"] == pytest.approx(7.5)

    def test_sulfate_mappe_sur_la_bonne_organisation(self):
        with patch("ingest_scraping.requests.get", return_value=_mock_response()):
            par_organisme = ingest_scraping.fetch_regulatory_limits()
        assert par_organisme["India (BIS)"]["Sulfate"] == 200.0

    def test_classification_floue_ignoree_pas_devinee(self):
        with patch("ingest_scraping.requests.get", return_value=_mock_response()):
            par_organisme = ingest_scraping.fetch_regulatory_limits()
        # "0-75 mg/L = soft" contient un "=" -> _extract_number renvoie None
        assert par_organisme["India (BIS)"]["Hardness"] is None

    def test_organisme_sans_aucune_feature_exploitable_absent(self):
        with patch("ingest_scraping.requests.get", return_value=_mock_response()):
            par_organisme = ingest_scraping.fetch_regulatory_limits()
        # "European Union" n'a de valeur que pour Arsenic (non mappé) -> absent
        assert "European Union" not in par_organisme


class TestExtractNumber:

    @pytest.mark.parametrize("text,expected", [
        ("200 mg/L", 200.0),
        ("<1000 ppm", 1000.0),
        ("6.5 to 8.5", 7.5),
        ("2500 μS/cm at 20 °C", 2500.0),
        ("0-75 mg/L = soft", None),
        ("", None),
    ])
    def test_cas(self, text, expected):
        result = ingest_scraping._extract_number(text)
        if expected is None:
            assert result is None
        else:
            assert result == pytest.approx(expected)


class TestImportLimits:

    def test_dry_run_ne_persiste_rien(self):
        db = SessionLocal()
        try:
            with patch("ingest_scraping.requests.get", return_value=_mock_response()):
                inserted = ingest_scraping.import_limits(db, dry_run=True)
            assert inserted == 0
            assert db.query(Client).filter_by(id_client="OPENDATA-SCRAPING").first() is None
        finally:
            db.close()

    def test_import_puis_reimport_est_idempotent(self):
        db = SessionLocal()
        try:
            with patch("ingest_scraping.requests.get", return_value=_mock_response()):
                first = ingest_scraping.import_limits(db, dry_run=False)
                second = ingest_scraping.import_limits(db, dry_run=False)

            assert first == 2   # World Health Organization + India (BIS)
            assert second == 0

            client = db.query(Client).filter_by(id_client="OPENDATA-SCRAPING").first()
            assert client is not None

            matches = db.query(Prelevement).filter(
                Prelevement.client_id == client.id,
                Prelevement.observations.contains("[scraping:"),
            ).all()
            assert len(matches) == 2
            assert all(m.source == IngestionSource.SCRAPING for m in matches)
        finally:
            db.close()
