# Fiche incident — VigiEau

## Scénario : Service OCR.space indisponible

**Date simulée :** 2025-03-18  
**Sévérité :** Moyenne (dégradation partielle, fallback disponible)  
**Service impacté :** `POST /ingest/ocr`, `POST /ingest/ocr-and-predict`

---

## 1. Détection

### Symptômes observés
Un client soumet une fiche labo PDF via `POST /ingest/ocr-and-predict` et reçoit une réponse avec un délai anormalement long (>15 secondes) puis une réponse partielle ou une erreur 502.

### Détection via logs applicatifs
Les logs Flask montrent :

```
[2025-03-18 09:14:32] WARNING  ocr_service: OCR.space request failed: ConnectionTimeout after 10s
[2025-03-18 09:14:32] INFO     ocr_service: Falling back to Claude Vision API
[2025-03-18 09:14:45] INFO     ocr_service: Claude Vision extraction successful
```

### Détection via métriques (`/exploitation/metrics`)
```json
{
  "route": "POST /ingest/ocr-and-predict",
  "p95_ms": 18420,
  "avg_ms": 14200,
  "error_rate": 0.0
}
```
- Latence p95 anormalement élevée (>10 000 ms vs baseline ~3 000 ms)
- Taux d'erreur = 0 car le fallback Claude Vision prend le relais

### Détection via audit_logs
```json
{
  "action": "client_ingest_ocr_predict",
  "detail": "ocr_provider=claude_vision (fallback: ocr.space timeout)",
  "status_code": 201
}
```

---

## 2. Diagnostic

**Cause identifiée :** OCR.space est en maintenance non planifiée (vérifiable sur leur page de statut).

**Impact réel :** Aucune perte de données — le fallback Claude Vision est automatiquement activé dans `extract_from_document()` (`ocr_service.py:194-230`) :

```python
# ocr_service.py — extrait réel, simplifié
if OCR_SPACE_KEY:
    try:
        raw_text = _ocr_space(file_bytes, mime)          # extraction primaire
        if len(raw_text) < 20:
            raise ValueError("Texte trop court")
        return _normalise(_claude_structure(raw_text))    # Claude structure le texte OCR.space
    except Exception as exc:
        logger.warning("OCR.space échoué (%s) — fallback Claude Vision", exc)

return _normalise(_claude_vision_extract(file_bytes, mime))  # extraction directe par Claude
```

**Impact utilisateur :** Latence accrue (~15s au lieu de ~3s) pendant la durée de l'incident.

---

## 3. Correction et vérification

### Actions immédiates (sans redéploiement)

Le fallback étant automatique, aucune action corrective urgente n'est nécessaire.  
Surveillance renforcée via `/exploitation/metrics` toutes les 15 minutes.

### Vérification du retour à la normale

Dès qu'OCR.space est de nouveau disponible, les logs reviennent à :
```
[2025-03-18 11:02:10] INFO  ocr_service: OCR.space extraction successful
```
Et la latence p95 redescend sous 4 000 ms.

### Test de non-régression à rejouer
```bash
pytest tests/test_e2e.py -v
```
(pipeline complet OCR → prélèvement → prédiction, OCR mocké — 10 tests)

---

## 4. Mise à jour du code et versionnement

### Amélioration proposée (non implémentée à ce jour)

Idée retenue suite à l'incident, **pas encore réalisée dans le code** :
exposer dans la réponse quel provider OCR a effectivement traité le
document, pour que l'analyste sache si une extraction est passée par le
fallback (potentiellement moins précis sur certains formats) :

```python
# Proposition — pas dans la réponse actuelle de /ingest/ocr(-and-predict)
{
  "prelevement_id": "...",
  "ocr_provider": "claude_vision",  # ou "ocr_space"
  "ocr_fallback": true,
  "ocr": { ... }
}
```

Aujourd'hui, la réponse réelle (`routes.py:506-509,561-567`) est
`{prelevement_id, ocr, prediction, prediction_possible}` — sans indication
du provider utilisé. À faire : `extract_from_document()` devrait retourner
le provider utilisé (ou le déduire d'un `warning` existant) pour que
`routes.py` puisse le propager dans la réponse.

### Commit à venir (si l'amélioration est réalisée)
```
git commit -m "feat: expose ocr_provider and ocr_fallback in ingest response"
```

---

## 5. Leçons tirées

| Point | Observation |
|---|---|
| Résilience | Le fallback automatique a évité toute interruption de service |
| Observabilité | La hausse de latence était visible dans `/exploitation/metrics` avant toute alerte client |
| Amélioration | Ajouter une alerte automatique si p95 > 10 000 ms sur les routes OCR |
| Documentation | Documenter le fallback dans le README pour les intégrateurs |

---

## Scénario réel : collision du registre Prometheus au deuxième démarrage (C21)

**Date réelle :** 2026-07-17
**Sévérité :** Bloquante (l'application ne peut plus s'initialiser une
seconde fois dans le même processus)
**Service impacté :** `create_app()` (`api/app.py`) — donc toute la
plateforme dès qu'une deuxième instance est créée sans redémarrer le
processus Python.

Contrairement au scénario OCR.space ci-dessus (simulé), celui-ci est un
**vrai bug**, rencontré en développant le monitorage Prometheus (C20),
corrigé sur sa propre branche avec un test de non-régression et fusionné
— traçable dans l'historique git (`fix/c21-prometheus-registry-collision`).

### 1. Détection

En lançant la suite complète `pytest tests/` après avoir ajouté
l'instrumentation Prometheus à `api/app.py`, 61 tests de
`tests/test_non_regression.py` échouent d'un coup :

```
ValueError: Duplicated timeseries in CollectorRegistry: {'vigieau_app_info'}
```

Pas une régression silencieuse : la suite complète refuse de tourner.

### 2. Diagnostic

`prometheus_flask_exporter.PrometheusMetrics(app, ...)` enregistre par
défaut ses métriques dans le registre global `prometheus_client.REGISTRY`
— un singleton au niveau du module Python, partagé par tout le processus.
`create_app()` est appelée une fois par fichier de test qui importe
l'application (`from api.app import create_app`) : au deuxième appel dans
le même processus pytest, les mêmes noms de métrique (`vigieau_app_info`,
`flask_http_request_total`...) tentent de se réenregistrer dans le même
registre déjà occupé, ce que `prometheus_client` refuse explicitement.

Reproduit isolément par `tests/test_app_factory.py::test_create_app_appelable_plusieurs_fois_sans_collision`.

### 3. Correction et vérification

Fix dans `api/app.py` : un `CollectorRegistry()` neuf passé explicitement
à chaque appel de `create_app()`, plutôt que de dépendre du registre
global implicite :

```python
from prometheus_client import CollectorRegistry
...
metrics = PrometheusMetrics(app, group_by="endpoint", registry=CollectorRegistry())
```

Vérification : `tests/test_app_factory.py` (2 tests, reproduisent 2 et 3
appels successifs à `create_app()`), plus la suite complète repassée au
vert (`pytest tests/` — 226 passed, contre 61 erreurs avant le fix).

### 4. Déploiement

- Branche dédiée : `fix/c21-prometheus-registry-collision`, créée depuis
  `feature/c20-monitoring-prometheus-grafana` (donc après le commit qui
  introduisait le bug).
- Test de non-régression ajouté et vérifié rouge avant le fix, vert après.
- Fusionnée dans `feature/c20-monitoring-prometheus-grafana` puis dans
  `main` avec un vrai commit de merge (`git log --graph --all`).
- Déployée via la même CI applicative que le reste du projet
  (`.github/workflows/ci.yml`), pas de pipeline séparé pour ce fix.

### 5. Leçons tirées

| Point | Observation |
|---|---|
| Détection | Un test qui échoue en bloc (61 erreurs identiques) est plus facile à diagnostiquer qu'une régression isolée — le message d'erreur pointait directement vers la cause |
| État global | Une bibliothèque tierce qui s'appuie sur un singleton implicite (le registre Prometheus par défaut) peut casser un pattern pourtant courant côté applicatif (factory function appelée plusieurs fois) |
| Test | Le bug n'était pas visible en testant `create_app()` une seule fois — seul un test qui reproduit explicitement l'appel multiple l'aurait révélé avant une vraie suite de tests multi-fichiers |

---

## Scénario secondaire : clé API OCR.space invalide

**Symptôme :** `POST /ingest/ocr` retourne HTTP 400 avec `"ocr_error": "OCR.space: invalid API key"`  
**Cause :** Clé expirée ou mal configurée dans `.env`  
**Correction :** Renouveler la clé sur ocr.space, mettre à jour `OCR_SPACE_API_KEY` dans `.env`, redémarrer le container  
**Vérification :** `curl -X POST /health` → vérifier que le service répond, puis soumettre un PDF de test
