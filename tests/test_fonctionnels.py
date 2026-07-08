"""
tests/test_fonctionnels.py — Tests fonctionnels Waterflow 2

Teste les parcours utilisateurs principaux de bout en bout :
  - Client : profil → dépôt de mesures → consultation des résultats
  - Expert : dashboard, liste des prélèvements, métriques
  - Admin  : création d'un compte client et génération de clé API

Modèle ML et scaler mockés. Env vars et tokens initialisés par conftest.py.
"""

import pytest
import numpy as np
from unittest.mock import MagicMock

_mock_model  = MagicMock()
_mock_model.predict.return_value       = np.array([1])
_mock_model.predict_proba.return_value = np.array([[0.15, 0.85]])
_mock_scaler = MagicMock()
_mock_scaler.transform.side_effect = lambda x: x

ALICE_HEADER = {"Authorization": "Bearer token-alice"}   # analyste
BOB_HEADER   = {"Authorization": "Bearer token-bob"}     # exploit

MESURES_VALIDES = {
    "ph": 7.2, "Hardness": 198.0, "Solids": 18630.0,
    "Chloramines": 7.1, "Sulfate": 333.0, "Conductivity": 432.0,
    "Organic_carbon": 14.2, "Trihalomethanes": 62.8, "Turbidity": 4.0,
}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    import predict_service
    from api.app       import create_app
    from api.models.db import init_db
    predict_service._model         = _mock_model
    predict_service._scaler        = _mock_scaler
    predict_service._model_version = "mock"
    application = create_app()
    application.config["TESTING"] = True
    init_db()
    return application


@pytest.fixture(scope="module")
def http(app):
    return app.test_client()


@pytest.fixture(scope="module")
def client_key(http):
    r = http.post("/admin/clients",
                  json={"id_client": "FONC-001",
                        "denomination": "Commune Fonctionnelle",
                        "adresse": "1 rue des Tests 75000 Paris"},
                  headers=BOB_HEADER)
    assert r.status_code == 201
    r2 = http.post(f"/admin/clients/{r.get_json()['id']}/apikey",
                   headers=BOB_HEADER)
    assert r2.status_code == 201
    return r2.get_json()["api_key"]


@pytest.fixture(scope="module")
def client_header(client_key):
    return {"X-API-Key": client_key}


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestParcoursSante:
    """Health check accessible sans authentification."""

    def test_health_accessible(self, http):
        r = http.get("/health")
        assert r.status_code == 200
        assert r.get_json()["status"] == "ok"

    def test_health_contient_le_modele(self, http):
        assert "model" in http.get("/health").get_json()


class TestParcoursClient:
    """Parcours complet d'un client : profil → dépôt → résultats."""

    def test_client_voit_son_profil(self, http, client_header):
        r = http.get("/me", headers=client_header)
        assert r.status_code == 200
        d = r.get_json()
        assert d["id_client"] == "FONC-001"
        assert "api_key" not in d

    def test_client_depose_mesures_et_obtient_prediction(self, http, client_header):
        r = http.post("/ingest/manual", json=MESURES_VALIDES, headers=client_header)
        assert r.status_code == 201
        d = r.get_json()
        assert "prelevement_id" in d
        pred = d["prediction"]
        assert pred["potable"] in (0, 1)
        assert 0.0 <= pred["probability"] <= 1.0
        assert pred["label"] in ("Potable", "Non potable")

    def test_client_consulte_ses_prelevements(self, http, client_header):
        http.post("/ingest/manual", json=MESURES_VALIDES, headers=client_header)
        r = http.get("/me/prelevements", headers=client_header)
        assert r.status_code == 200
        assert r.get_json()["total"] >= 1

    def test_client_voit_uniquement_ses_donnees(self, http, client_header):
        r = http.get("/me/prelevements", headers=client_header)
        ids = {p["client_id"] for p in r.get_json()["items"]}
        assert ids == {"FONC-001"}

    def test_client_consulte_ses_resultats(self, http, client_header):
        assert http.get("/me/resultats", headers=client_header).status_code == 200

    def test_client_ne_peut_pas_voir_les_routes_expert(self, http, client_header):
        assert http.get("/analyste/prelevements", headers=client_header).status_code == 401
        assert http.get("/exploitation/metrics",  headers=client_header).status_code == 401


class TestParcoursExpert:
    """Parcours d'un expert : dashboard, prélèvements, métriques."""

    def test_expert_voit_le_dashboard(self, http):
        r = http.get("/analyste/dashboard", headers=ALICE_HEADER)
        assert r.status_code == 200
        d = r.get_json()
        assert "total_prelevements" in d
        assert "potable_rate" in d
        assert "sources" in d

    def test_expert_liste_tous_les_prelevements(self, http):
        r = http.get("/analyste/prelevements", headers=ALICE_HEADER)
        assert r.status_code == 200
        assert "items" in r.get_json()

    def test_exploit_voit_les_metriques_systeme(self, http):
        r = http.get("/exploitation/metrics", headers=BOB_HEADER)
        assert r.status_code == 200
        assert "routes" in r.get_json()

    def test_exploit_voit_le_journal_acces(self, http):
        r = http.get("/exploitation/audit", headers=BOB_HEADER)
        assert r.status_code == 200
        assert "items" in r.get_json()

    def test_analyste_ne_peut_pas_acceder_exploitation(self, http):
        assert http.get("/exploitation/metrics", headers=ALICE_HEADER).status_code == 403


class TestAdminGestionClients:
    """Parcours administrateur : création client, génération et usage de la clé."""

    def test_admin_cree_un_client(self, http):
        r = http.post("/admin/clients",
                      json={"id_client": "FONC-NEW",
                            "denomination": "Nouveau Client",
                            "adresse": "2 rue Nouvelle 69000 Lyon"},
                      headers=BOB_HEADER)
        assert r.status_code == 201
        d = r.get_json()
        assert d["id_client"] == "FONC-NEW"
        assert d["actif"] is True
        assert "api_key" not in d

    def test_admin_genere_une_cle_one_shot(self, http):
        r = http.post("/admin/clients/FONC-NEW/apikey", headers=BOB_HEADER)
        assert r.status_code == 201
        d = r.get_json()
        assert "api_key" in d
        assert len(d["api_key"]) >= 20
        assert "warning" in d

    def test_client_avec_cle_peut_se_connecter(self, http):
        r = http.post("/admin/clients/FONC-NEW/apikey", headers=BOB_HEADER)
        key = r.get_json()["api_key"]
        r2 = http.get("/me", headers={"X-API-Key": key})
        assert r2.status_code == 200
        assert r2.get_json()["id_client"] == "FONC-NEW"

    def test_client_desactive_ne_peut_plus_se_connecter(self, http):
        r_key = http.post("/admin/clients/FONC-NEW/apikey", headers=BOB_HEADER)
        key = r_key.get_json()["api_key"]

        http.put("/admin/clients/FONC-NEW", json={"actif": False}, headers=BOB_HEADER)

        r = http.get("/me", headers={"X-API-Key": key})
        assert r.status_code == 401
