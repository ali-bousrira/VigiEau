# Plan de travail — Certification RNCP 37827 (VigiEau)

> Établi le 2026-07-08. Croise la matrice de conformité Notion *"Conformité
> RNCP 37827 — Waterflow 2"* (21 compétences, lue le 2026-07-08, dernière
> mise à jour du contenu le 2026-07-04) avec l'état réel du dépôt et
> `RAPPORT_CONFORMITE.md`.

## 1. Où on en est

| Statut | Nombre | Compétences |
|---|---|---|
| ✅ Couvert | 18 | C2–C12, C15–C21 |
| 🟠 À renforcer | 3 | **C1**, **C13**, **C14** |
| 🔴 À ajouter | 0 | — |

Aucune compétence n'est totalement absente : le travail restant consiste à
**combler 3 lacunes réelles** et à **consolider des preuves** pour les 18
compétences déjà couvertes (souvent un simple ajout de documentation, pas de
code). S'y ajoutent les **livrables de certification** (Phase 4 du guide :
rapports + doc technique) qui n'existent pas encore, et une poignée de
points issus de `RAPPORT_CONFORMITE.md` sans lien direct avec une
compétence mais qui pèsent sur la qualité globale du dépôt.

Rappel des blocs (page Notion racine) :

| Bloc | Épreuves | Compétences | Livrable |
|---|---|---|---|
| Bloc 1 — Données | E1 | C1–C5 | Rapport professionnel |
| Bloc 2 — Modèles & services IA | E2 + E3 | C6–C13 | Rapports professionnels |
| Bloc 3 — Application IA | E4 + E5 | C14–C21 | Rapport pro + doc technique |

---

## 2. Les 3 lacunes réelles — travail de fond

### 2.1 C1 — Extraction de données multi-sources (🟠, Bloc 1 / E1)

**Manque constaté :** aucune source web/API ouverte/big data — seulement
OCR (fiches labo) et saisie API. `grep` sur le dépôt ne montre aucun script
de scraping (`scripts/` ne contient que `init_db.py`).

**Proposition :** utiliser l'API ouverte française **Hub'Eau**
(data.eau.gouv.fr — API publique, pas de clé requise, cohérente avec le
domaine métier "qualité de l'eau"), ex. l'API *qualité des eaux de surface*
ou *qualité des eaux distribuées*. Évite le scraping HTML (fragile, zone
grise juridique) tout en répondant à l'exigence "web/API ouverte".

- Nouveau script `scripts/ingest_hubeau.py` : appelle l'API (via `requests`,
  déjà en dépendance), homogénéise les champs vers le format `Mesure`
  existant (`to_feature_dict()` dans `db.py`), journalise les lignes
  rejetées/incomplètes.
- Nettoyage : gestion des valeurs manquantes/aberrantes avant insertion,
  cohérent avec ce que `C3` documente déjà pour l'OCR.
- Stockage : soit un nouveau `IngestionSource.HUBEAU` (enum dans `db.py`),
  soit rattachement à un "client système" dédié si le modèle de données
  l'exige — à trancher en amont (impact MCD/MPD, donc `docs/mcd.md`).
- RGPD : données publiques et agrégées, pas de données à caractère
  personnel — un paragraphe dans `docs/rgpd.md` suffit à le justifier.
- Tests : un test d'intégration mockant la réponse HTTP de Hub'Eau
  (`responses`/`unittest.mock`, pas d'appel réseau réel dans la CI).

**Effort estimé :** 0.5–1 jour. **Points d'attention RGPD à valider avant
codage** (comme le guide le demande en Phase 1) : confirmer qu'aucune
donnée personnelle ne transite, et que la volumétrie récupérée reste
raisonnable (pas de moissonnage massif).

### 2.2 C13 — Chaîne de livraison continue du modèle / MLOps (🟠, Bloc 2 / E3)

**Manque constaté :** `.github/workflows/ci.yml` est une CI **applicative**
(lint, `pytest tests/`, build Docker, déploiement SSH) — elle ne fait
**rien de spécifique au cycle de vie du modèle** : pas de ré-entraînement,
pas de validation de données avant entraînement, pas de seuil de
performance avant promotion dans le MLflow Model Registry. L'entraînement
vit uniquement dans `water_xgboost.ipynb` (notebook, non automatisable tel
quel).

**Proposition :**
- Extraire la logique d'entraînement du notebook vers un script
  `scripts/train_model.py` (chargement `water_potability_clean.csv` →
  validation du schéma/plages de valeurs → split → entraînement XGBoost →
  évaluation → `mlflow.xgboost.log_model` + `mlflow.register_model`).
- Étape de **validation des données** avant entraînement (colonnes
  attendues, pas de valeurs hors plage physico-chimique plausible) —
  réutilisable avec les tests déjà présents dans
  `tests/test_unitaires.py::TestDataset`.
- **Seuil de performance** (ex. AUC ou accuracy minimale sur le jeu de
  validation) : le script échoue (exit code ≠ 0) si le nouveau modèle est
  moins bon que le seuil — condition de promotion.
- Nouveau job CI (`.github/workflows/ci.yml` ou fichier dédié
  `model-ci.yml`), déclenché sur changement de
  `water_potability*.csv`/`scripts/train_model.py` (`paths:` filter) ou en
  `workflow_dispatch` manuel : validation → entraînement → évaluation →
  packaging (export `model_artifacts/xgboost_model.json` en artefact CI) →
  promotion conditionnelle dans le registry.
- Ce job reste séparé du job `test` existant (qui, lui, mocke le modèle) —
  pas de dépendance croisée.

**Effort estimé :** 1–1.5 jour (le plus gros morceau des 3 lacunes).

### 2.3 C14 — Analyse du besoin d'application : accessibilité + wireframes (🟠, Bloc 3 / E4)

**Manque constaté :** `docs/user_stories.md` (10 US, 3 profils) ne contient
**aucun** critère d'accessibilité — vérifié directement dans le fichier.

**Proposition :**
- Ajouter à **chaque** US un critère d'acceptation RGAA/WCAG explicite
  (ex. US-02 dépôt manuel : "le formulaire expose des `<label>` associés,
  les erreurs de validation sont annoncées via `aria-live`, contraste ≥
  4.5:1" ; US-06 dashboard : "les indicateurs chiffrés ont une alternative
  textuelle, pas d'information portée uniquement par la couleur" — pertinent
  vu que `templates/index.html` utilise beaucoup de badges colorés
  potable/non-potable).
- Choisir un référentiel unique (RGAA, puisque contexte français/service
  public de l'eau) et le nommer explicitement en tête de
  `docs/user_stories.md`.
- Produire des **wireframes** (texte structuré suffit, pas besoin d'outil
  graphique) des 3 parcours experts (analyste, exploit, admin) — nouveau
  fichier `docs/wireframes.md` ou section dans `docs/architecture.md`.

**Effort estimé :** 0.5 jour (documentaire, pas de code — sauf si l'audit
révèle de vrais manques d'accessibilité dans `templates/index.html`, auquel
cas prévoir un correctif ciblé : labels manquants, contraste, focus
clavier).

---

## 3. Compétences déjà ✅ — consolidation de preuves (léger, à faire en Phase 4)

Ces 18 compétences sont couvertes fonctionnellement ; l'"action à mener"
Notion associée est une **formalisation documentaire**, pas du code. À
traiter en lot pendant la rédaction des rapports (section 4) plutôt qu'en
tâches séparées :

| Code | Action à mener (Notion) | Fichier concerné |
|---|---|---|
| C2 | Documenter les requêtes SQL clés | `docs/` (nouvelle section ou fichier) |
| C6 | Formaliser le dispositif de veille (sources, cadence, outils) | `docs/` (nouveau) |
| C7 | Rédiger le benchmark OCR comme document autonome (existe seulement en commentaire dans `ocr_service.py:1-17`) | `docs/benchmark_ocr.md` |
| C8 | Documenter la configuration du service OCR.space | `docs/` ou README |
| C10 | Montrer l'intégration API Model → UI + accessibilité | dépend de la correction C14 |
| C11 | Exposer des métriques de monitoring modèle (dérive, alertes) | optionnel, déjà noté bonus dans `docs/roadmap.md` |
| C12 | Couvrir explicitement validation/préparation/entraînement/évaluation dans les tests | recoupe le script C13 |
| C15 | Vérifier que l'environnement d'exécution est spécifié (PaaS, versions) | `docs/architecture.md` |
| C16 | Montrer la conduite agile (board/issues, itérations) | GitHub Projects/Issues — hors dépôt |
| C17 | Attester accessibilité/sécurité/gestion des données | recoupe C14 |
| C18 | Montrer le déclenchement auto des tests au versionnement | déjà en place (`ci.yml`), juste à documenter |
| C19 | Documenter le paramétrage des environnements de test/livraison | `docs/architecture.md` ou README |
| C20 | Documenter le dispositif de monitorage applicatif | `docs/` (nouveau) ou compléter `docs/rgpd.md` |
| C21 | Finaliser `docs/incident.md` (méthodologie, résolution) | vérifier le contenu actuel |

---

## 4. Livrables de certification (Phase 4 du guide) — à rédiger

Aucun rapport n'existe encore dans `docs/` (seul `RAPPORT_CONFORMITE.md`,
qui est un audit interne, pas un livrable de certification). D'après le
guide, à traiter **un par un** :

1. Rapport professionnel **E1** (Bloc 1 — collecte/stockage/mise à
   disposition des données) — s'appuie sur C1–C5, à rédiger **après** la
   correction C1 pour avoir une preuve complète.
2. Rapport professionnel **E3** (Bloc 2 — modèle/services IA en
   production) — s'appuie sur C9–C13, à rédiger **après** la correction
   C13.
3. Rapport professionnel **E4** (Bloc 3 — application) — s'appuie sur
   C14–C19, à rédiger **après** la correction C14.
4. Documentation technique **E2** (service OCR) — peut être rédigée dès
   maintenant, C6–C8 sont déjà ✅.
5. Documentation technique **E5** (monitoring + incident) — peut être
   rédigée dès maintenant, C20–C21 sont déjà ✅.
6. Support de soutenance — en dernier, une fois les 5 documents ci-dessus
   stabilisés.

---

## 5. Points hors matrice mais à traiter (issus de `RAPPORT_CONFORMITE.md`)

Sans lien direct avec une compétence RNCP mais qui joueraient contre le
dossier à l'oral :

- Historique Git — messages descriptifs, un sujet par commit (en cours
  d'amélioration depuis cette session).
- Note README sur la limite SQLite / bascule PostgreSQL.
- Vue "Audit" absente de l'UI exploit (`GET /exploitation/audit` existe,
  pas exposé dans `templates/index.html`).
- Dropdown client dans l'UI Prélèvements (actuellement un champ texte
  libre) — confort, non bloquant.

---

## 6. Ordre de traitement proposé

1. **C14** (accessibilité + wireframes) — le moins coûteux, purement
   documentaire, débloque aussi C10/C17.
2. **C1** (source Hub'Eau) — bien cadré, effort modéré.
3. **C13** (CI/CD modèle) — le plus gros chantier technique, à traiter en
   mode Plan comme le prévoit le guide.
4. Vue Audit UI + dropdown client (petits compléments UI déjà identifiés
   la session précédente, non bloquants pour la certification mais rapides
   à faire pendant qu'on est dans `templates/index.html`).
5. Rédaction des 5 livrables de certification (section 4), dans l'ordre
   E2/E5 (déjà couverts) → E1 → E3 → E4 (après correctifs) → soutenance.
6. Mise à jour finale de la matrice Notion (statuts + colonne preuve) et
   du présent plan.

**Un point par session/prompt**, conformément aux règles du guide — ne pas
enchaîner plusieurs points sans validation intermédiaire.

---

## 7. Suivi de la matrice Notion

J'ai maintenant un accès en lecture/écriture à la matrice Notion *"Matrice
de conformité C1 → C21"*. Je peux mettre à jour le statut et la colonne
"Preuve Waterflow" directement dans Notion au fur et à mesure que chaque
point ci-dessus est traité, si tu le souhaites — à confirmer avant chaque
mise à jour (action visible par d'autres si le workspace est partagé).
