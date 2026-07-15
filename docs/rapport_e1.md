---
type: rapport-professionnel
epreuve: E1
bloc: 1
competences: [C1, C2, C3, C4, C5]
---

> Brouillon généré à partir du code réel du dépôt à l'appui de chaque
> affirmation. La structure suit la consigne (contexte, démarche, choix
> techniques, résultats, difficultés rencontrées) mais **la voix doit
> rester la tienne** avant dépôt — relis et reformule ce qui ne sonne pas
> comme ton propre vécu, en particulier §5.

# Rapport professionnel — E1 : Collecte, stockage et mise à disposition des données

## 1. Contexte

VigiEau centralise le suivi de la qualité de l'eau pour des collectivités
territoriales : chaque prélèvement (mesures physico-chimiques d'un point
d'eau) doit pouvoir être déposé, stocké de façon conforme au RGPD, et
restitué à la fois au client qui l'a soumis et aux experts qui supervisent
la plateforme. Trois profils utilisateurs se partagent ces données avec
des périmètres stricts : le client final (ses propres prélèvements
uniquement), l'analyste qualité (vue globale) et le responsable
d'exploitation (supervision + gestion des comptes) — voir [[user_stories]].

L'enjeu du Bloc 1 est de démontrer une chaîne complète : extraction depuis
plusieurs sources hétérogènes → nettoyage/homogénéisation → modélisation
conforme (Merise) → mise à disposition via une API documentée.

## 2. Démarche

### 2.1 Trois sources de collecte

| Source | Mécanisme | Fichier |
|---|---|---|
| Saisie API directe | `POST /ingest/manual` — JSON des 9 mesures | `routes.py` |
| Fiche laboratoire (OCR) | `POST /ingest/ocr(-and-predict)` — image/PDF → extraction structurée | `ocr_service.py` (détail : [[doc_technique_e2]]) |
| API ouverte Hub'Eau | `scripts/ingest_hubeau.py` — import automatisé, hors requête HTTP | contrôle sanitaire officiel de l'eau potable |

La troisième source a été ajoutée cette phase du projet pour couvrir
l'exigence de collecte **multi-sources** (web/API ouverte, pas seulement
saisie manuelle ou OCR). J'ai choisi une API publique plutôt que du
scraping HTML : moins fragile face aux changements de mise en page du
site source, pas de zone grise juridique, et surtout un vrai jeu de
données officiel plutôt qu'une extraction bricolée.

### 2.2 Nettoyage et homogénéisation

Chaque source alimente le **même schéma cible** (`Prelevement` + `Mesure`,
9 features physico-chimiques), quelle que soit son origine :

- OCR : normalisation des nombres (virgule → point), champs manquants ou
  douteux marqués en `warnings` plutôt que devinés (`ocr_service.py::_normalise`).
- Hub'Eau : les résultats bruts de l'API sont groupés par `code_prelevement`
  (un prélèvement physique = plusieurs lignes, une par paramètre mesuré),
  puis pivotés vers les 9 features attendues. Sur les 9, seules 7 ont un
  équivalent identifié dans le contrôle sanitaire français
  (`scripts/ingest_hubeau.py::PARAM_MAP`) — voir §5.
- Dans tous les cas, un prélèvement est stocké **même si des mesures
  manquent** (`prediction_possible=false` plutôt qu'un rejet) : je
  privilégie la conservation de la donnée partielle à sa perte.

### 2.3 Modélisation et exposition

Le MCD/MPD ([[mcd]]) formalise 5 entités (`clients`, `prelevements`,
`mesures`, `predictions`, plus les tables techniques `audit_logs` et
`request_metrics`). L'API expose ces données via des routes REST
documentées en OpenAPI (`swagger.yaml`, accessible sur `/apidocs`), avec
un contrôle d'accès par clé API pour les clients et par token Bearer
(rôles `analyste`/`exploit`) pour les experts.

## 3. Choix techniques

- **SQLAlchemy 2.0** plutôt qu'un ORM plus lourd : le schéma est simple
  (5 entités métier), pas besoin de fonctionnalités avancées.
- **SQLite en développement, PostgreSQL visé en production** — bascule
  prévue via `DATABASE_URL` mais pas encore finalisée (voir §5 et
  `README.md`, section Limites connues).
- **Formalisme Merise (MCD/MPD)** pour la modélisation, conformément à
  l'exigence de certification, avant toute implémentation SQL.
- **Une seule `Mesure` par `Prelevement`** (`uselist=False` dans
  `db.py`), mais **plusieurs `Prediction` possibles par `Prelevement`**
  au niveau du schéma (pas de contrainte d'unicité) — en pratique,
  l'application n'en crée jamais qu'une seule par prélèvement (l'endpoint
  `POST /predict` autonome ne persiste rien). C'est une nuance que
  `docs/mcd.md` simplifie en "1:1" ; je le précise ici pour rester exact.
- **Pagination systématique** (`page`/`per_page`) sur toutes les routes de
  listing, pour rester exploitable à volume réel.
- **RGPD by design** : clé API hashée SHA-256 (jamais en clair), IP
  pseudonymisée dans les journaux, droit d'accès et d'effacement exposés
  via `/me/rgpd` — détail complet dans [[rgpd]].

## 4. Résultats

- API Data opérationnelle : dépôt (3 sources), consultation filtrée
  (`client_id`, `source`, `date`, et depuis cette session `potable`),
  détail par ID, export RGPD.
- `scripts/ingest_hubeau.py` testé en conditions réelles : 11 prélèvements
  réels récupérés sur un vrai appel à l'API Hub'Eau (commune de Paris),
  avec détection correcte des features manquantes par prélèvement.
- Documentation OpenAPI complète et accessible sur `/apidocs`.
- Suite de tests : 198 tests passants, dont une suite dédiée à
  l'ingestion Hub'Eau (`tests/test_ingest_hubeau.py`) couvrant le mapping,
  la conversion d'unité et l'idempotence (un second import ne duplique
  rien).

## 5. Difficultés rencontrées

**Le mapping Hub'Eau n'a pas de solution parfaite.** Le jeu de données
d'entraînement du modèle (Kaggle) et le contrôle sanitaire français ne
mesurent pas exactement les mêmes paramètres. J'ai dû faire des choix
assumés plutôt que d'attendre une correspondance exacte qui n'existe pas :
`Chloramines` est approximée par le chlore total mesuré (proxy, pas une
équivalence chimique), et `Solids` (matières dissoutes totales) n'a
simplement aucun équivalent dans les paramètres suivis en France — la
feature reste `None` pour toute donnée Hub'Eau, ce qui limite
mécaniquement les prédictions automatiques sur cette source (`Solids`
manque toujours). J'ai vérifié cette limite par un vrai appel réseau
plutôt que de la déduire de la documentation Hub'Eau, pour être sûr de ne
pas inventer une correspondance qui n'existe pas.

**Un blocage silencieux sur la documentation elle-même** : `docs/` était
resté dans `.gitignore` depuis la création du dépôt, ce qui fait que toute
la documentation (MCD, RGPD, user stories...) existait uniquement en
local, jamais partagée — alors même que CLAUDE.md exige explicitement sa
présence dans `docs/`. Ce n'est qu'en croisant le dépôt réel avec les
exigences de certification que le problème est apparu ; correction simple
une fois identifiée, mais un bon rappel que "ça marche chez moi" ne
suffit pas pour un livrable partagé.

**Étendre le schéma sans casser l'existant.** Ajouter `IngestionSource.OPENDATA`
à l'énumération existante (`MANUAL`/`OCR`/`API`) semblait trivial, mais
SQLite grave la contrainte `CHECK` d'une colonne `Enum` au moment de la
création de la table — une base déjà initialisée avec l'ancienne
énumération refuse silencieusement d'accepter la nouvelle valeur tant
qu'elle n'est pas recréée. Point à surveiller à chaque évolution de ce
type d'énumération.
