# VigiEau — Roadmap

## Priorité 1 — Bloquants CI ✅

- [x] Déplacer `ci.yml` → `.github/workflows/ci.yml` (GitHub Actions ne le détecte pas à la racine)
- [x] Déplacer `test_api.py` (racine) → `tests/test_api.py` (la CI tourne `pytest tests/`, ce fichier est ignoré)
- [x] Créer `tests/conftest.py` — initialise `sys.path` et `EXPERT_TOKENS` avant tout import (remplace le `conftest.py` racine non chargé par `pytest tests/`)
- [x] Réécrire `tests/test_fonctionnels.py` et `tests/test_non_regression.py` pour Waterflow 2 — les versions précédentes testaient `POST /predict` (Waterflow 1, inexistant) et faisaient planter la CI

## Priorité 2 — Bugs fonctionnels ✅

- [x] Corriger `tests/test_e2e.py` ligne 232 : le test postait sur `/ingest/ocr` et vérifiait `prediction_possible`, mais ce champ n'existe que sur `/ingest/ocr-and-predict` → endpoint corrigé
- [x] Corriger `auth.py` : `entry.split(":", 2)` pour tolérer les tokens contenant des `:` (ex. JWT) sans que l'entrée soit silencieusement rejetée
- [~] `record_metric()` et fuite DB : fausse alerte — `finally: db.close()` était déjà présent

## Priorité 3 — Exigences du cahier des charges manquantes ✅

- [x] Ajouter `POST /predict` autonome — accepte des mesures brutes ou un `prelevement_id` existant, retourne prédiction + `model_version`, ne crée rien en base
- [x] Créer `samples/` — fiche labo anonymisée (`.txt`), résultat OCR attendu (`.json`), README avec commande curl de démo

## Priorité 4 — Nettoyage / qualité ✅

- [x] Supprimer `index.html` à la racine (doublon mort — Flask utilise `templates/index.html`)
- [x] Clarifier la structure `app.py` / `api/app.py` : factory déplacée dans `api/app.py` (source canonique), `app.py` racine devient un re-export pour rétrocompatibilité

## Optionnel (bonus si le temps le permet)

- [x] Dashboard Prometheus + Grafana pour les métriques d'exploitation — réalisé (`docker-compose.yml`, `monitoring/`, voir `docs/doc_technique_e5.md` C20)
- [ ] Interface de filtrage avancé pour l'analyste (filtre par zone géographique)
- [ ] Replay de prédiction sur un prélèvement existant (comparer versions MLflow)
- [ ] Script de purge automatique des `audit_logs` et `request_metrics` > 12 mois / 90 jours (voir `GET /me/rgpd` pour les durées recommandées déjà documentées)
- [ ] CD automatique (déploiement sur push `main`) — le job `deploy` dans `ci.yml` est ébauché mais nécessite les secrets `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`
