"""
tests/test_api.py — Tests d'intégration VigiEau

Architecture testée :
  - Clients     : X-API-Key → /me, /ingest/*, /me/prelevements, /me/resultats
  - Admin       : Bearer (tout expert) → /admin/clients/*
  - Analyste    : Bearer (analyste|exploit) → /analyste/*
  - Exploitation: Bearer (exploit seul) → /exploitation/*

Modèle ML et scaler mockés — base SQLite en mémoire.
Tokens et env vars initialisés par tests/conftest.py.
"""

import os
import secrets
import pytest
from unittest.mock import MagicMock
import numpy as np

# ── Mocks ML ────────────────────────────────────────────────────────────────
_mock_model  = MagicMock()
_mock_model.predict.return_value        = np.array([1])
_mock_model.predict_proba.return_value  = np.array([[0.13, 0.87]])

_mock_scaler = MagicMock()
_mock_scaler.transform.side_effect = lambda x: x

import predict_service
from api.app        import create_app
from api.models.db  import init_db, SessionLocal, Client

predict_service._model         = _mock_model
predict_service._scaler        = _mock_scaler
predict_service._model_version = "mock"

# ── Constantes ───────────────────────────────────────────────────────────────
ALICE_HEADER  = {"Authorization": "Bearer token-alice"}   # analyste
BOB_HEADER    = {"Authorization": "Bearer token-bob"}     # exploit
WRONG_BEARER  = {"Authorization": "Bearer mauvais-token"}

VALID_MESURES = {
    "ph": 7.2, "Hardness": 198.0, "Solids": 18630.0,
    "Chloramines": 7.1, "Sulfate": 333.0, "Conductivity": 432.0,
    "Organic_carbon": 14.2, "Trihalomethanes": 62.8, "Turbidity": 4.0,
}


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def app():
    application = create_app()
    application.config["TESTING"] = True
    init_db()
    return application

@pytest.fixture(scope="session")
def http(app):
    return app.test_client()

@pytest.fixture(scope="session")
def client_key(http):
    """Crée un client via l'API admin et retourne sa clé brute."""
    r = http.post("/admin/clients",
                  json={"id_client": "TEST-001",
                        "denomination": "Commune de Test",
                        "adresse": "1 rue de la Mairie 75000 Paris",
                        "rgpd_consent": True},
                  headers=BOB_HEADER)
    assert r.status_code == 201, r.get_json()
    client_id = r.get_json()["id"]

    r2 = http.post(f"/admin/clients/{client_id}/apikey", headers=BOB_HEADER)
    assert r2.status_code == 201
    return r2.get_json()["api_key"]

@pytest.fixture(scope="session")
def client_header(client_key):
    return {"X-API-Key": client_key}


# ════════════════════════════════════════════════════════════════════════════
# /health — public
# ════════════════════════════════════════════════════════════════════════════

class TestHealth:
    def test_ok_sans_auth(self, http):
        r = http.get("/health")
        assert r.status_code == 200
        assert r.get_json()["status"] == "ok"


# ════════════════════════════════════════════════════════════════════════════
# ADMIN /admin/clients — accessible à TOUS les experts
# ════════════════════════════════════════════════════════════════════════════

class TestAdminClients:

    def test_creer_client_analyste(self, http):
        r = http.post("/admin/clients",
                      json={"id_client": "COMM-ALICE",
                            "denomination": "Commune Alice",
                            "adresse": "1 rue Alice 69000 Lyon"},
                      headers=ALICE_HEADER)
        assert r.status_code == 201
        d = r.get_json()
        assert d["id_client"] == "COMM-ALICE"
        assert "api_key" not in d

    def test_creer_client_exploit(self, http):
        r = http.post("/admin/clients",
                      json={"id_client": "COMM-BOB",
                            "denomination": "Commune Bob",
                            "adresse": "2 rue Bob 13000 Marseille"},
                      headers=BOB_HEADER)
        assert r.status_code == 201

    def test_creer_client_sans_auth(self, http):
        r = http.post("/admin/clients",
                      json={"id_client": "COMM-X", "denomination": "X", "adresse": "X"})
        assert r.status_code == 401

    def test_creer_client_mauvais_token(self, http):
        r = http.post("/admin/clients",
                      json={"id_client": "COMM-X", "denomination": "X", "adresse": "X"},
                      headers=WRONG_BEARER)
        assert r.status_code == 401

    def test_client_api_key_absent_dans_creation(self, http):
        r = http.post("/admin/clients",
                      json={"id_client": "COMM-NOKEY",
                            "denomination": "Sans clé",
                            "adresse": "3 rue C 75001 Paris"},
                      headers=ALICE_HEADER)
        assert "api_key" not in r.get_json()

    def test_champs_requis_id_client(self, http):
        r = http.post("/admin/clients",
                      json={"denomination": "X", "adresse": "Y"},
                      headers=BOB_HEADER)
        assert r.status_code == 400
        assert "id_client" in r.get_json()["error"]

    def test_champs_requis_denomination(self, http):
        r = http.post("/admin/clients",
                      json={"id_client": "X", "adresse": "Y"},
                      headers=BOB_HEADER)
        assert r.status_code == 400

    def test_champs_requis_adresse(self, http):
        r = http.post("/admin/clients",
                      json={"id_client": "COMM-NOADR", "denomination": "Sans adresse"},
                      headers=BOB_HEADER)
        assert r.status_code == 400
        assert "adresse" in r.get_json()["error"]

    def test_duplicate_id_client(self, http):
        r = http.post("/admin/clients",
                      json={"id_client": "COMM-ALICE",
                            "denomination": "Doublon",
                            "adresse": "X"},
                      headers=BOB_HEADER)
        assert r.status_code == 409

    def test_lister_clients_analyste(self, http):
        r = http.get("/admin/clients", headers=ALICE_HEADER)
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_lister_clients_exploit(self, http):
        r = http.get("/admin/clients", headers=BOB_HEADER)
        assert r.status_code == 200

    def test_modifier_client(self, http):
        r = http.put("/admin/clients/COMM-ALICE",
                     json={"denomination": "Commune Alice Modifiée"},
                     headers=ALICE_HEADER)
        assert r.status_code == 200
        assert r.get_json()["denomination"] == "Commune Alice Modifiée"

    def test_adresse_vide_refusee(self, http):
        r = http.put("/admin/clients/COMM-ALICE",
                     json={"adresse": ""},
                     headers=BOB_HEADER)
        assert r.status_code == 400

    def test_generer_cle_analyste(self, http):
        r = http.post("/admin/clients/COMM-ALICE/apikey", headers=ALICE_HEADER)
        assert r.status_code == 201
        d = r.get_json()
        assert "api_key" in d
        assert "warning" in d
        assert len(d["api_key"]) > 20

    def test_generer_cle_exploit(self, http):
        r = http.post("/admin/clients/COMM-BOB/apikey", headers=BOB_HEADER)
        assert r.status_code == 201
        assert "api_key" in r.get_json()

    def test_client_introuvable(self, http):
        r = http.get("/admin/clients/INEXISTANT", headers=BOB_HEADER)
        assert r.status_code == 404


# ════════════════════════════════════════════════════════════════════════════
# CLIENTS — /me et /ingest/*
# ════════════════════════════════════════════════════════════════════════════

class TestClientAuth:

    def test_me_avec_cle_valide(self, http, client_header):
        r = http.get("/me", headers=client_header)
        assert r.status_code == 200
        d = r.get_json()
        assert d["id_client"] == "TEST-001"
        assert d["denomination"] == "Commune de Test"
        assert d["adresse"] == "1 rue de la Mairie 75000 Paris"
        assert "api_key" not in d

    def test_me_sans_cle(self, http):
        assert http.get("/me").status_code == 401

    def test_me_cle_invalide(self, http):
        assert http.get("/me", headers={"X-API-Key": "totalement-fausse"}).status_code == 401

    def test_client_ne_peut_pas_utiliser_bearer(self, http):
        assert http.get("/me", headers=ALICE_HEADER).status_code == 401

    def test_client_ne_peut_pas_acceder_admin(self, http, client_header):
        r = http.post("/admin/clients",
                      json={"id_client": "HACK", "denomination": "Hack", "adresse": "X"},
                      headers=client_header)
        assert r.status_code == 401

    def test_client_ne_peut_pas_acceder_analyste(self, http, client_header):
        assert http.get("/analyste/dashboard", headers=client_header).status_code == 401

    def test_client_ne_peut_pas_acceder_exploitation(self, http, client_header):
        assert http.get("/exploitation/metrics", headers=client_header).status_code == 401


class TestClientIngestion:

    def test_ingest_manual_valide(self, http, client_header):
        r = http.post("/ingest/manual", json=VALID_MESURES, headers=client_header)
        assert r.status_code == 201
        d = r.get_json()
        assert "prelevement_id" in d
        assert d["prediction"]["potable"] in (0, 1)
        assert "probability" in d["prediction"]

    def test_ingest_manual_feature_manquante(self, http, client_header):
        bad = {k: v for k, v in VALID_MESURES.items() if k != "ph"}
        assert http.post("/ingest/manual", json=bad, headers=client_header).status_code == 400

    def test_ingest_manual_valeur_non_numerique(self, http, client_header):
        bad = {**VALID_MESURES, "ph": "pas-un-nombre"}
        assert http.post("/ingest/manual", json=bad, headers=client_header).status_code == 400

    def test_ingest_manual_sans_cle(self, http):
        assert http.post("/ingest/manual", json=VALID_MESURES).status_code == 401

    def test_ingest_ocr_sans_fichier(self, http, client_header):
        assert http.post("/ingest/ocr", headers=client_header).status_code == 400

    def test_ingest_ocr_type_invalide(self, http, client_header):
        from io import BytesIO
        r = http.post("/ingest/ocr",
                      data={"file": (BytesIO(b"data"), "test.exe", "application/x-executable")},
                      content_type="multipart/form-data",
                      headers=client_header)
        assert r.status_code == 400


class TestPredictAutonome:

    def test_predict_mesures_brutes(self, http, client_header):
        r = http.post("/predict", json=VALID_MESURES, headers=client_header)
        assert r.status_code == 200
        d = r.get_json()
        assert d["potable"] in (0, 1)
        assert d["label"] in ("Potable", "Non potable")
        assert 0.0 <= d["probability"] <= 1.0
        assert "model_version" in d
        assert "mesures" in d

    def test_predict_par_prelevement_id(self, http, client_header):
        r_ingest = http.post("/ingest/manual", json=VALID_MESURES, headers=client_header)
        prev_id  = r_ingest.get_json()["prelevement_id"]

        r = http.post("/predict", json={"prelevement_id": prev_id}, headers=client_header)
        assert r.status_code == 200
        assert r.get_json()["potable"] in (0, 1)

    def test_predict_id_inexistant(self, http, client_header):
        r = http.post("/predict",
                      json={"prelevement_id": "00000000-0000-0000-0000-000000000000"},
                      headers=client_header)
        assert r.status_code == 404

    def test_predict_id_autre_client_refuse(self, http):
        db = SessionLocal()
        from api.models.db import Client as C
        import secrets as s
        c2 = C(id_client="PRED-OTHER", denomination="Autre", adresse="X", actif=True)
        c2.set_api_key(s.token_urlsafe(16))
        db.add(c2); db.commit(); db.close()

        r = http.post("/predict",
                      json={"prelevement_id": "00000000-0000-0000-0000-000000000000"},
                      headers={"X-API-Key": s.token_urlsafe(16)})
        assert r.status_code == 401

    def test_predict_feature_manquante(self, http, client_header):
        bad = {k: v for k, v in VALID_MESURES.items() if k != "ph"}
        assert http.post("/predict", json=bad, headers=client_header).status_code == 400

    def test_predict_sans_cle(self, http):
        assert http.post("/predict", json=VALID_MESURES).status_code == 401

    def test_predict_ne_cree_pas_de_prelevement(self, http, client_header):
        r_before = http.get("/me/prelevements", headers=client_header).get_json()["total"]
        http.post("/predict", json=VALID_MESURES, headers=client_header)
        r_after  = http.get("/me/prelevements", headers=client_header).get_json()["total"]
        assert r_after == r_before


class TestClientConsultation:

    def test_mes_prelevements(self, http, client_header):
        r = http.get("/me/prelevements", headers=client_header)
        assert r.status_code == 200
        d = r.get_json()
        assert "items" in d
        assert "total" in d
        assert "page" in d

    def test_mes_resultats(self, http, client_header):
        assert http.get("/me/resultats", headers=client_header).status_code == 200

    def test_detail_prelevement_autre_client_refuse(self, http):
        """Un client ne peut pas accéder aux prélèvements d'un autre."""
        db = SessionLocal()
        c2 = Client(id_client="TEST-002", denomination="Autre",
                    adresse="2 rue B", actif=True)
        raw = secrets.token_urlsafe(16)
        c2.set_api_key(raw)
        db.add(c2)
        db.commit()
        db.close()

        r = http.get("/me/prelevements",
                     headers={"X-API-Key": secrets.token_urlsafe(16)})
        assert r.status_code == 401

    def test_pagination(self, http, client_header):
        r = http.get("/me/prelevements?page=1&per_page=5", headers=client_header)
        assert r.status_code == 200
        assert r.get_json()["per_page"] == 5


# ════════════════════════════════════════════════════════════════════════════
# ANALYSTE — /analyste/*
# ════════════════════════════════════════════════════════════════════════════

class TestAnalyste:

    def test_dashboard(self, http):
        r = http.get("/analyste/dashboard", headers=ALICE_HEADER)
        assert r.status_code == 200
        d = r.get_json()
        assert "total_prelevements" in d
        assert "potable_rate" in d
        assert "moyennes" in d

    def test_dashboard_exploit_peut_aussi(self, http):
        assert http.get("/analyste/dashboard", headers=BOB_HEADER).status_code == 200

    def test_prelevements_tous(self, http):
        r = http.get("/analyste/prelevements", headers=ALICE_HEADER)
        assert r.status_code == 200
        assert "items" in r.get_json()

    def test_prelevements_client_interdit_sans_auth(self, http):
        assert http.get("/analyste/prelevements").status_code == 401

    def test_client_ne_peut_pas_voir_analyste(self, http, client_header):
        assert http.get("/analyste/prelevements", headers=client_header).status_code == 401

    def test_client_inconnu_404(self, http):
        r = http.get("/analyste/clients/INEXISTANT/prelevements",
                     headers=ALICE_HEADER)
        assert r.status_code == 404

    def test_filtre_potable_ne_retourne_que_les_potables(self, http):
        r = http.get("/analyste/prelevements?potable=1", headers=ALICE_HEADER)
        assert r.status_code == 200
        items = r.get_json()["items"]
        assert items
        assert all(it["prediction"]["potable"] == 1 for it in items)

    def test_filtre_potable_ne_retourne_que_les_non_potables(self, http):
        from api.models.db import Prelevement, Prediction
        db     = SessionLocal()
        client = db.query(Client).filter(Client.id_client == "TEST-001").first()
        prev   = Prelevement(client_id=client.id)
        db.add(prev); db.commit()
        db.add(Prediction(prelevement_id=prev.id, potable=0,
                           probability=0.05, model_version="test"))
        db.commit()
        prev_id = prev.id
        db.close()

        r = http.get("/analyste/prelevements?potable=0", headers=ALICE_HEADER)
        assert r.status_code == 200
        items = r.get_json()["items"]
        assert any(it["id"] == prev_id for it in items)
        assert all(it["prediction"]["potable"] == 0 for it in items)


# ════════════════════════════════════════════════════════════════════════════
# EXPLOITATION — /exploitation/*
# ════════════════════════════════════════════════════════════════════════════

class TestExploitation:

    def test_metrics_exploit(self, http):
        r = http.get("/exploitation/metrics", headers=BOB_HEADER)
        assert r.status_code == 200
        d = r.get_json()
        assert "routes" in d
        assert "clients_total" in d

    def test_metrics_analyste_interdit(self, http):
        assert http.get("/exploitation/metrics", headers=ALICE_HEADER).status_code == 403

    def test_metrics_client_interdit(self, http, client_header):
        assert http.get("/exploitation/metrics", headers=client_header).status_code == 401

    def test_audit_exploit(self, http):
        r = http.get("/exploitation/audit", headers=BOB_HEADER)
        assert r.status_code == 200
        d = r.get_json()
        assert "items" in d
        assert "total" in d

    def test_audit_analyste_interdit(self, http):
        assert http.get("/exploitation/audit", headers=ALICE_HEADER).status_code == 403

    def test_audit_pagination(self, http):
        r = http.get("/exploitation/audit?page=1&per_page=10", headers=BOB_HEADER)
        assert r.status_code == 200
        assert r.get_json()["per_page"] == 10


# ════════════════════════════════════════════════════════════════════════════
# [Option] RGPD — /me/rgpd
# ════════════════════════════════════════════════════════════════════════════

class TestRGPD:

    def test_get_rgpd_structure(self, http, client_header):
        r = http.get("/me/rgpd", headers=client_header)
        assert r.status_code == 200
        d = r.get_json()
        assert "donnees_personnelles"  in d
        assert "donnees_stockees"      in d
        assert "historique_acces"      in d
        assert "regles_conservation"   in d
        assert "vos_droits"            in d

    def test_get_rgpd_donnees_personnelles(self, http, client_header):
        r = http.get("/me/rgpd", headers=client_header)
        dp = r.get_json()["donnees_personnelles"]
        assert dp["id_client"]    == "TEST-001"
        assert dp["denomination"] == "Commune de Test"
        assert dp["adresse"]      == "1 rue de la Mairie 75000 Paris"

    def test_get_rgpd_pas_de_cle_brute(self, http, client_header):
        text = http.get("/me/rgpd", headers=client_header).get_data(as_text=True)
        assert "api_key_hash" not in text

    def test_get_rgpd_ip_pseudonymisee(self, http, client_header):
        acces = http.get("/me/rgpd", headers=client_header).get_json()["historique_acces"]
        for a in acces:
            ip = a.get("ip", "")
            if ip and ip != "unknown":
                assert not ip.split(".")[-1].isdigit() or "xxx" in ip

    def test_get_rgpd_regles_conservation_completes(self, http, client_header):
        regl = http.get("/me/rgpd", headers=client_header).get_json()["regles_conservation"]
        assert "prelevements_et_mesures" in regl
        assert "journaux_acces"          in regl
        assert "metriques_performance"   in regl
        assert "cle_api"                 in regl

    def test_get_rgpd_droits_mentionnes(self, http, client_header):
        droits = http.get("/me/rgpd", headers=client_header).get_json()["vos_droits"]
        assert "acces"         in droits
        assert "rectification" in droits
        assert "effacement"    in droits
        assert "portabilite"   in droits

    def test_get_rgpd_sans_auth(self, http):
        assert http.get("/me/rgpd").status_code == 401

    def test_get_rgpd_expert_interdit(self, http):
        assert http.get("/me/rgpd", headers=ALICE_HEADER).status_code == 401

    def test_delete_rgpd_sans_confirmation(self, http, client_header):
        r = http.delete("/me/rgpd", json={}, headers=client_header)
        assert r.status_code == 400

    def test_delete_rgpd_confirme(self, http):
        r_create = http.post(
            "/admin/clients",
            json={"id_client": "TEMP-RGPD", "denomination": "Temp",
                  "adresse": "1 rue Temp 75000 Paris"},
            headers=BOB_HEADER,
        )
        assert r_create.status_code == 201
        client_id = r_create.get_json()["id"]

        r_key = http.post(f"/admin/clients/{client_id}/apikey", headers=BOB_HEADER)
        assert r_key.status_code == 201
        temp_header = {"X-API-Key": r_key.get_json()["api_key"]}

        r_del = http.delete("/me/rgpd", json={"confirmer": True}, headers=temp_header)
        assert r_del.status_code == 200
        d = r_del.get_json()
        assert "anonymisé" in d["message"].lower() or "anonymise" in d["message"].lower()
        assert "anonymise_le" in d

        assert http.get("/me", headers=temp_header).status_code == 401
