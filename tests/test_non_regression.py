"""
tests/test_non_regression.py — Tests de non-régression VigiEau

Garantit que les contrats d'API ne régressent pas entre les versions :
  - Chemins de routes stables
  - Structures de réponse (champs, types) stables
  - Codes HTTP stables
  - Noms et nombre de features du modèle stables
  - Règles d'authentification stables

Env vars et tokens initialisés par conftest.py.
"""

import pytest
import numpy as np
from unittest.mock import MagicMock

_mock_model  = MagicMock()
_mock_model.predict.return_value       = np.array([1])
_mock_model.predict_proba.return_value = np.array([[0.13, 0.87]])
_mock_scaler = MagicMock()
_mock_scaler.transform.side_effect = lambda x: x

ALICE_HEADER = {"Authorization": "Bearer token-alice"}
BOB_HEADER   = {"Authorization": "Bearer token-bob"}

MESURES_VALIDES = {
    "ph": 7.0, "Hardness": 200.0, "Solids": 20000.0,
    "Chloramines": 7.5, "Sulfate": 350.0, "Conductivity": 400.0,
    "Organic_carbon": 14.0, "Trihalomethanes": 66.0, "Turbidity": 3.5,
}

FEATURES = [
    "ph", "Hardness", "Solids", "Chloramines", "Sulfate",
    "Conductivity", "Organic_carbon", "Trihalomethanes", "Turbidity",
]


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
def client_header(http):
    r = http.post("/admin/clients",
                  json={"id_client": "NR-001",
                        "denomination": "Client NR",
                        "adresse": "1 rue NR 75000 Paris"},
                  headers=BOB_HEADER)
    assert r.status_code == 201
    r2 = http.post(f"/admin/clients/{r.get_json()['id']}/apikey",
                   headers=BOB_HEADER)
    return {"X-API-Key": r2.get_json()["api_key"]}


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestContratsRoutes:
    """Les chemins de routes ne doivent jamais changer."""

    def test_health_route_stable(self, http):
        assert http.get("/health").status_code == 200

    def test_me_route_stable(self, http, client_header):
        assert http.get("/me", headers=client_header).status_code == 200

    def test_me_prelevements_route_stable(self, http, client_header):
        assert http.get("/me/prelevements", headers=client_header).status_code == 200

    def test_me_resultats_route_stable(self, http, client_header):
        assert http.get("/me/resultats", headers=client_header).status_code == 200

    def test_ingest_manual_route_stable(self, http, client_header):
        assert http.post("/ingest/manual", json=MESURES_VALIDES,
                         headers=client_header).status_code == 201

    def test_admin_clients_get_route_stable(self, http):
        assert http.get("/admin/clients", headers=BOB_HEADER).status_code == 200

    def test_admin_clients_post_route_stable(self, http):
        r = http.post("/admin/clients",
                      json={"id_client": "NR-ROUTE",
                            "denomination": "Route NR",
                            "adresse": "1 rue Route 75000 Paris"},
                      headers=BOB_HEADER)
        assert r.status_code in (201, 409)   # 409 si déjà existant (idempotence)

    def test_analyste_dashboard_route_stable(self, http):
        assert http.get("/analyste/dashboard", headers=ALICE_HEADER).status_code == 200

    def test_analyste_prelevements_route_stable(self, http):
        assert http.get("/analyste/prelevements", headers=ALICE_HEADER).status_code == 200

    def test_exploitation_metrics_route_stable(self, http):
        assert http.get("/exploitation/metrics", headers=BOB_HEADER).status_code == 200

    def test_exploitation_audit_route_stable(self, http):
        assert http.get("/exploitation/audit", headers=BOB_HEADER).status_code == 200


class TestContratsReponses:
    """Les structures de réponse (champs, types) ne doivent jamais changer."""

    def test_health_champs_stables(self, http):
        d = http.get("/health").get_json()
        assert "status" in d
        assert "model"  in d
        assert "ts"     in d

    def test_ingest_manual_champs_stables(self, http, client_header):
        d = http.post("/ingest/manual", json=MESURES_VALIDES,
                      headers=client_header).get_json()
        assert "prelevement_id" in d
        assert "prediction"     in d

    def test_prediction_champs_stables(self, http, client_header):
        pred = http.post("/ingest/manual", json=MESURES_VALIDES,
                         headers=client_header).get_json()["prediction"]
        assert "potable"     in pred
        assert "label"       in pred
        assert "probability" in pred

    def test_prediction_types_stables(self, http, client_header):
        pred = http.post("/ingest/manual", json=MESURES_VALIDES,
                         headers=client_header).get_json()["prediction"]
        assert isinstance(pred["potable"],     int)
        assert isinstance(pred["label"],       str)
        assert isinstance(pred["probability"], float)

    def test_prediction_valeurs_possibles_stables(self, http, client_header):
        pred = http.post("/ingest/manual", json=MESURES_VALIDES,
                         headers=client_header).get_json()["prediction"]
        assert pred["potable"] in (0, 1)
        assert pred["label"]   in ("Potable", "Non potable")
        assert 0.0 <= pred["probability"] <= 1.0

    def test_prelevements_pagination_champs_stables(self, http, client_header):
        d = http.get("/me/prelevements", headers=client_header).get_json()
        for champ in ("items", "total", "page", "per_page", "pages"):
            assert champ in d, f"Champ de pagination '{champ}' disparu"

    def test_client_creation_champs_stables(self, http):
        r = http.post("/admin/clients",
                      json={"id_client": "NR-CHAMP",
                            "denomination": "Champ NR",
                            "adresse": "1 rue C 75000 Paris"},
                      headers=BOB_HEADER)
        if r.status_code == 201:
            d = r.get_json()
            for champ in ("id", "id_client", "denomination", "adresse", "actif"):
                assert champ in d, f"Champ '{champ}' disparu de la réponse de création"
            assert "api_key" not in d

    def test_dashboard_champs_stables(self, http):
        d = http.get("/analyste/dashboard", headers=ALICE_HEADER).get_json()
        for champ in ("total_prelevements", "potable_rate", "sources", "moyennes"):
            assert champ in d, f"Champ dashboard '{champ}' disparu"

    def test_erreur_toujours_champ_error(self, http, client_header):
        """Toute réponse d'erreur doit contenir un champ 'error' de type str."""
        payload_incomplet = {k: v for k, v in MESURES_VALIDES.items() if k != "ph"}
        r = http.post("/ingest/manual", json=payload_incomplet, headers=client_header)
        assert r.status_code == 400
        d = r.get_json()
        assert "error" in d
        assert isinstance(d["error"], str)


class TestContratsAuth:
    """Les règles d'authentification ne doivent jamais régresser."""

    def test_routes_client_rejettent_sans_cle(self, http):
        for route in ("/me", "/me/prelevements", "/me/resultats"):
            assert http.get(route).status_code == 401, \
                f"{route} devrait renvoyer 401 sans clé"

    def test_routes_expert_rejettent_sans_token(self, http):
        for route in ("/admin/clients", "/analyste/dashboard",
                      "/analyste/prelevements", "/exploitation/metrics"):
            assert http.get(route).status_code == 401, \
                f"{route} devrait renvoyer 401 sans token"

    def test_analyste_bloque_sur_exploitation(self, http):
        assert http.get("/exploitation/metrics",
                        headers=ALICE_HEADER).status_code == 403

    def test_cle_client_bloquee_sur_routes_expert(self, http, client_header):
        for route in ("/analyste/dashboard", "/exploitation/metrics"):
            assert http.get(route, headers=client_header).status_code == 401, \
                f"Clé client ne doit pas accéder à {route}"

    def test_token_invalide_retourne_401(self, http):
        bad = {"Authorization": "Bearer token-totalement-faux"}
        assert http.get("/admin/clients", headers=bad).status_code == 401


class TestContratsFeatures:
    """Le nombre et les noms des features du modèle ne doivent jamais changer."""

    def test_nombre_features_constant(self):
        assert len(FEATURES) == 9

    def test_noms_features_constants(self):
        assert set(FEATURES) == {
            "ph", "Hardness", "Solids", "Chloramines", "Sulfate",
            "Conductivity", "Organic_carbon", "Trihalomethanes", "Turbidity",
        }

    def test_ordre_features_constant(self):
        assert FEATURES[0] == "ph"
        assert FEATURES[-1] == "Turbidity"

    @pytest.mark.parametrize("feature", [
        "ph", "Hardness", "Solids", "Chloramines", "Sulfate",
        "Conductivity", "Organic_carbon", "Trihalomethanes", "Turbidity",
    ])
    def test_feature_manquante_retourne_400(self, http, client_header, feature):
        payload = {k: v for k, v in MESURES_VALIDES.items() if k != feature}
        r = http.post("/ingest/manual", json=payload, headers=client_header)
        assert r.status_code == 400, \
            f"Feature '{feature}' manquante non rejetée (attendu 400)"
