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

Aujourd'hui, la réponse réelle (`routes.py:504-507,559-565`) est
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

## Scénario secondaire : clé API OCR.space invalide

**Symptôme :** `POST /ingest/ocr` retourne HTTP 400 avec `"ocr_error": "OCR.space: invalid API key"`  
**Cause :** Clé expirée ou mal configurée dans `.env`  
**Correction :** Renouveler la clé sur ocr.space, mettre à jour `OCR_SPACE_API_KEY` dans `.env`, redémarrer le container  
**Vérification :** `curl -X POST /health` → vérifier que le service répond, puis soumettre un PDF de test
