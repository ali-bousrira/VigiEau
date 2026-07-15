---
type: documentation-technique
epreuve: E5
competences: [C20, C21]
---

> Brouillon technique généré à partir du code du dépôt (`auth.py`,
> `routes.py`, `db.py`, `docs/incident.md`) — factuel et vérifiable. Voir
> [[rgpd]] pour le détail des mesures de protection des données et
> [[architecture]] pour la vue d'ensemble technique.

# Documentation technique — Monitorage et incident (E5)

## 1. Objectif

Donner à l'équipe d'exploitation une visibilité sur la santé de la
plateforme (volume, latence, erreurs) et une traçabilité complète des
accès aux données (exigence RGPD), sans dépendre d'un outil externe
(Prometheus/Grafana envisagés mais non intégrés — voir §5).

## 2. Architecture du monitorage

Deux mécanismes indépendants, tous deux déclenchés depuis `auth.py` et
alimentés par chaque requête :

```mermaid
flowchart LR
    R["Requête HTTP"] --> D{"Décorateurs de routes.py"}
    D -->|"@require_client_key /\n@require_expert(...)"| A["_write_audit()"]
    D -->|"@timed"| M["record_metric()"]
    A --> AL[("audit_logs")]
    M --> RM[("request_metrics")]
    AL --> EA["GET /exploitation/audit"]
    RM --> EM["GET /exploitation/metrics"]
    EA --> UI["Onglet Audit\n(templates/index.html, role=exploit)"]
```

### 2.1 Métriques de performance (`request_metrics`)

- **Écriture** : décorateur `@timed` (`auth.py:370-388`), placé après les
  décorateurs d'authentification sur chaque route. Mesure la durée réelle
  (`time.perf_counter()`) et appelle `record_metric()` (`auth.py:238-264`)
  quel que soit le code retour (succès ou erreur).
- **Modèle** (`db.py:245-257`, table `request_metrics`) : `route`,
  `method`, `status_code`, `duration_ms`, `actor_type`, `actor_hint`
  (hint de clé API ou login expert — jamais la clé/le token en clair).
- **Exposition** : `GET /exploitation/metrics` (`routes.py:927-976`, rôle
  `exploit` uniquement) — agrège les `limit` dernières requêtes (défaut
  5000, borné entre 100 et 50000) par route : nombre, taux d'erreur,
  p50/p95/moyenne de latence en millisecondes ; plus des KPIs globaux
  (clients actifs, total prélèvements/prédictions, taux de potabilité).

### 2.2 Journal d'accès RGPD (`audit_logs`)

- **Écriture** : `log_audit()`/`_write_audit()` (`auth.py:187-235`),
  appelée explicitement dans chaque route sensible (ex.
  `client_ingest_ocr`, `analyste_read_dashboard`, `exploitation_metrics`).
  Non bloquant : une erreur d'écriture d'audit est journalisée et absorbée
  (`except Exception`), elle ne fait jamais échouer la requête métier.
- **Modèle** (`db.py:222-243`, table `audit_logs`) : `timestamp`,
  `actor_type` (`client`/`expert`), `actor_id`, `actor_role`, `ip_address`
  (pseudonymisée — voir [[rgpd]]), `action`, `resource_id`, `status_code`,
  `detail`. Immuable par convention applicative : aucune route
  DELETE/UPDATE n'existe sur cette table.
- **Exposition** : `GET /exploitation/audit` (`routes.py:979` et
  suivantes, rôle `exploit` strict — un `analyste` reçoit 403), paginée,
  filtrable par `actor_type`, `actor_id`, `action` (recherche partielle).
- **Interface** : onglet "Audit" dédié dans `templates/index.html`, ajouté
  cette session (commit `54891db`) — visible uniquement pour le rôle
  `exploit`, vérifié en conditions réelles (navigateur headless) : les
  entrées réelles s'affichent avec IP pseudonymisée (ex. `127.0.0.xxx`).

## 3. Fiche incident

`docs/incident.md` documente un scénario simulé (OCR.space indisponible),
conformément à la consigne du cahier des charges ("provoque ou simule un
incident technique réaliste"). Structure : détection (logs, métriques,
audit_logs) → diagnostic → correction/vérification → mise à jour du code
→ leçons tirées, avec un scénario secondaire (clé API invalide).

**Point de vigilance trouvé en vérifiant ce document contre le code
actuel** — 3 détails illustratifs ont dérivé de l'implémentation réelle
depuis sa rédaction :

| Détail cité dans `docs/incident.md` | Réalité actuelle du code |
|---|---|
| Fonction `extract_from_file(file_bytes, mime_type)` | `extract_from_document(file_bytes, mime)` (`ocr_service.py:194`) |
| Réponse enrichie de `ocr_provider`/`ocr_fallback` (§4, "amélioration post-incident") | Jamais implémenté — la réponse réelle est `{prelevement_id, ocr, prediction, prediction_possible}` |
| Action d'audit `"ingest_ocr"` | `"client_ingest_ocr"` / `"client_ingest_ocr_predict"` (`routes.py:503,558`) |
| Commande de non-régression `pytest tests/test_fonctionnels.py -k "ocr"` | Ne matche plus aucun test — ce fichier a été entièrement réécrit depuis (commit `5eae1ab`) |

Le scénario et la méthodologie restent valides ; ces détails d'illustration
mériteraient une correction séparée de `docs/incident.md` pour rester
alignés avec le code — non faite ici pour ne pas modifier un livrable déjà
considéré terminé sans validation explicite.

## 4. Tests

Aucun test dédié au monitorage lui-même (`record_metric`/`log_audit` sont
exercés indirectement par tous les tests d'intégration, qui passent par
des routes décorées `@timed`). `tests/test_api.py` et
`tests/test_non_regression.py` couvrent `/exploitation/metrics` et
`/exploitation/audit` (contrôle d'accès rôle `exploit`, structure de
réponse). `tests/test_accessibility.py` couvre l'onglet Audit (présence
`aria-live`, visibilité conditionnelle au rôle).

## 5. Limites connues

- Pas d'alerting automatique (seuils de latence/erreur) — consultation
  manuelle de `/exploitation/metrics` ou de l'onglet Audit uniquement.
- Prometheus/Grafana non intégrés : `/exploitation/metrics` retourne un
  JSON agrégé maison, pas un format `/metrics` scrapable nativement.
- `request_metrics` n'a pas de purge automatique (mentionnée comme piste
  dans `docs/roadmap.md`, non implémentée) — croissance illimitée de la
  table en usage prolongé.
- Le monitorage mesure la durée du traitement Flask ; il n'inclut pas la
  latence réseau côté client ni les appels sortants individuels
  (OCR.space, Claude, MLflow) en tant que métriques séparées — seule la
  durée totale de la route est mesurée.
