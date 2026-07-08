# Fiche incident — Waterflow 2

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
  "action": "ingest_ocr",
  "detail": "ocr_provider=claude_vision (fallback: ocr.space timeout)",
  "status_code": 200
}
```

---

## 2. Diagnostic

**Cause identifiée :** OCR.space est en maintenance non planifiée (vérifiable sur leur page de statut).

**Impact réel :** Aucune perte de données — le fallback Claude Vision est automatiquement activé dans `ocr_service.py` :

```python
# ocr_service.py
def extract_from_file(file_bytes, mime_type):
    if OCR_SPACE_API_KEY:
        try:
            result = _call_ocr_space(file_bytes, mime_type)
            return result
        except Exception as e:
            logger.warning(f"OCR.space request failed: {e}")
            logger.info("Falling back to Claude Vision API")
    
    return _call_claude_vision(file_bytes, mime_type)
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
pytest tests/test_fonctionnels.py -k "ocr" -v
```

---

## 4. Mise à jour du code et versionnement

### Amélioration apportée (post-incident)

Ajout d'un header de contexte dans la réponse API pour indiquer quel provider OCR a été utilisé :

```python
# Dans la réponse JSON de /ingest/ocr
{
  "prelevement_id": "...",
  "ocr_provider": "claude_vision",  # ou "ocr_space"
  "ocr_fallback": true,
  "extraction": { ... }
}
```

Cela permet à l'analyste de savoir si une extraction a été faite via le fallback (potentiellement moins précis sur certains formats).

### Commit associé
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
