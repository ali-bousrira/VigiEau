# User Stories — Waterflow 2

## Profils utilisateurs

| Profil | Authentification | Périmètre |
|---|---|---|
| **Client final** | Clé API (`X-API-Key`) | Ses propres données uniquement |
| **Analyste qualité** | Bearer Token (rôle `analyste`) | Tous les prélèvements, dashboards |
| **Responsable d'exploitation** | Bearer Token (rôle `exploit`) | Métriques système, audit, gestion clients |

---

## Client final

### US-01 — Création de compte
> En tant que client final, je veux qu'un administrateur crée un compte avec mon ID, ma dénomination et mon adresse, afin de disposer d'une clé API pour accéder au service.

**Critères d'acceptation :**
- `POST /admin/clients` crée le client avec `id_client`, `denomination`, `adresse`
- La clé API est générée et retournée une seule fois (jamais stockée en clair)
- Le client reçoit sa clé et peut l'utiliser immédiatement

**Route :** `POST /admin/clients` (admin seulement)

---

### US-02 — Dépôt de prélèvement manuel
> En tant que client final, je veux soumettre un prélèvement via API avec mes mesures physico-chimiques, afin d'obtenir une prédiction de potabilité.

**Critères d'acceptation :**
- `POST /ingest/manual` avec les 9 mesures retourne une prédiction immédiate
- La prédiction inclut : `potable` (0/1), `probability`, `model_version`
- Le prélèvement est stocké avec `source = MANUAL`
- Toute requête invalide (champ manquant, type incorrect) retourne HTTP 422

**Route :** `POST /ingest/manual`

---

### US-03 — Consultation de ses prélèvements
> En tant que client final, je veux consulter la liste et le détail de mes prélèvements (uniquement les miens), afin de suivre mes analyses.

**Critères d'acceptation :**
- `GET /me/prelevements` retourne uniquement les prélèvements du client authentifié
- La liste est paginée (paramètres `page`, `per_page`)
- Filtrable par `date_debut` et `date_fin`
- `GET /me/prelevements/<id>` retourne le détail avec la prédiction associée
- Un client ne peut pas accéder aux données d'un autre client (HTTP 403)

**Routes :** `GET /me/prelevements`, `GET /me/prelevements/<id>`, `GET /me/resultats`

---

### US-04 — Dépôt de fiche laboratoire (OCR)
> En tant que client final, je veux soumettre une photo ou un PDF de fiche labo, afin que la plateforme en extraie automatiquement les données et crée un prélèvement structuré.

**Critères d'acceptation :**
- `POST /ingest/ocr` accepte JPEG, PNG, WEBP, GIF, PDF (max 20 Mo)
- Le service OCR extrait : date, lieu, ID client, mesures, observations
- Un prélèvement est créé avec `source = OCR` même si certaines mesures manquent
- La réponse indique `prediction_possible: true/false` selon la complétude des mesures
- `POST /ingest/ocr-and-predict` enchaîne OCR et prédiction en un appel

**Routes :** `POST /ingest/ocr`, `POST /ingest/ocr-and-predict`

---

### US-05 — Accès aux données personnelles (RGPD) [option]
> En tant que client final, je veux connaître les données personnelles associées à mon compte et les règles de conservation, afin de vérifier que la plateforme respecte le RGPD.

**Critères d'acceptation :**
- `GET /me/rgpd` retourne : profil, historique d'accès, règles de conservation
- `DELETE /me/rgpd` anonymise le compte de manière irréversible
- L'opération d'anonymisation est tracée dans `audit_logs`

**Routes :** `GET /me/rgpd`, `DELETE /me/rgpd`

---

## Analyste qualité

### US-06 — Dashboard global
> En tant qu'analyste qualité, je veux accéder à un dashboard regroupant tous les prélèvements, leur provenance, les prédictions et les métriques du modèle.

**Critères d'acceptation :**
- `GET /analyste/dashboard` retourne : taux de potabilité, moyennes chimiques, répartition par source (MANUAL/OCR/API), 15 derniers prélèvements
- `GET /analyste/prelevements` liste tous les prélèvements avec pagination
- Filtrage par `client_id`, `source`, `date_debut`, `date_fin`

**Routes :** `GET /analyste/dashboard`, `GET /analyste/prelevements`

---

### US-07 — Détail d'un prélèvement
> En tant qu'analyste qualité, je veux consulter le détail complet d'un prélèvement, y compris le texte OCR brut et les avertissements d'extraction.

**Critères d'acceptation :**
- `GET /analyste/prelevements/<id>` inclut `ocr_raw_text` et `ocr_warnings`
- La prédiction associée avec `model_version` MLflow est visible

**Route :** `GET /analyste/prelevements/<id>`

---

## Responsable d'exploitation

### US-08 — Métriques système
> En tant que responsable d'exploitation, je veux consulter les indicateurs de santé : nombre de requêtes, erreurs, temps de réponse, afin de surveiller la plateforme.

**Critères d'acceptation :**
- `GET /exploitation/metrics` retourne : volume par route, p50/p95/moyenne de latence, taux d'erreur par route
- Les métriques couvrent les 24 dernières heures

**Route :** `GET /exploitation/metrics`

---

### US-09 — Journal d'accès
> En tant que responsable d'exploitation, je veux consulter un journal des accès par clé API (date, endpoint, code retour), afin de garantir la traçabilité.

**Critères d'acceptation :**
- `GET /exploitation/audit` retourne les entrées `audit_logs` paginées
- Filtrable par `actor_type`, `action`, `date_debut`, `date_fin`
- Les IPs sont pseudonymisées (dernier octet masqué)

**Route :** `GET /exploitation/audit`

---

### US-10 — Gestion des clients
> En tant que responsable d'exploitation, je veux créer, désactiver et régénérer les clés API des clients.

**Critères d'acceptation :**
- `POST /admin/clients` crée un client
- `PUT /admin/clients/<id>` permet de désactiver (`actif: false`)
- `POST /admin/clients/<id>/apikey` régénère la clé (ancienne immédiatement invalide)
- La nouvelle clé est retournée une seule fois

**Routes :** `POST /admin/clients`, `PUT /admin/clients/<id>`, `POST /admin/clients/<id>/apikey`
