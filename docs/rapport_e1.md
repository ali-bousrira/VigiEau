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

### 2.1 Cinq sources de collecte

Le référentiel (REAC) exige précisément 5 types de source distincts
(API web, scraping, fichier, base de données, système big data) — pas
juste "plusieurs sources hétérogènes" au sens large. La fiche labo (OCR)
et Hub'Eau couvraient déjà API web et fichier ; j'ai ajouté les 3
manquantes :

| Source | Type REAC | Mécanisme | Fichier |
|---|---|---|---|
| Fiche laboratoire (OCR) | Fichier | `POST /ingest/ocr(-and-predict)` — image/PDF → extraction structurée | `ocr_service.py` (détail : [[doc_technique_e2]]) |
| API ouverte Hub'Eau | API web | `scripts/ingest_hubeau.py` — import automatisé, hors requête HTTP | contrôle sanitaire officiel de l'eau potable |
| Comparaison Wikipédia des normes | Scraping | `scripts/ingest_scraping.py` — table HTML réelle, valeurs limites par organisme (OMS, UE, Inde...) | `en.wikipedia.org/wiki/Drinking_water_quality_standards` |
| Ancien système départemental | Base de données | `scripts/ingest_legacy_db.py` — SQLite, schéma et format de date propres à ce système | `legacy_system.db` (généré par `scripts/seed_legacy_db.py`) |
| Jeu Kaggle via DuckDB/Parquet | Big data | `scripts/ingest_bigdata_duckdb.py` — CSV converti en Parquet, requêté via DuckDB | `water_potability.csv` (déjà utilisé pour l'entraînement) |

Sur la saisie API directe (`POST /ingest/manual`) : elle reste dans
l'application (c'est le canal principal utilisé par un client réel), mais
je ne la compte plus parmi les 5 sources d'*extraction* du REAC — recevoir
un dépôt poussé par un client n'est pas la même chose qu'aller chercher
la donnée à sa source, même si le code et le schéma cible sont partagés.

Pour le scraping, j'avais d'abord écarté cette piste (préférant une API
publique, moins fragile face aux changements de mise en page) — mais le
REAC demande explicitement les 5 types, scraping inclus, donc je l'ai
ajouté malgré cette réserve initiale plutôt que de la contourner.

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
- Scraping : les valeurs limites réglementaires ne sont pas des mesures de
  terrain — nature différente, assumée dans le champ `lieu` ("Valeurs
  limites — [organisme]") plutôt que masquée. Les classifications floues
  ("0–75 mg/L = soft") sont explicitement ignorées plutôt que converties
  en un nombre inventé (`scripts/ingest_scraping.py::_extract_number`).
- Base légataire : noms de colonnes et format de date (`DD/MM/YYYY`)
  propres à cet ancien système, harmonisés vers le schéma cible et l'ISO
  8601 (`scripts/ingest_legacy_db.py`) — la seule des 5 sources qui
  couvre les 9 features sans exception.
- Big data : les colonnes du CSV Kaggle correspondent déjà aux 9 features
  attendues — l'harmonisation porte ici sur le *format* (CSV → Parquet →
  requêtage DuckDB) plutôt que sur les noms de colonnes, contrairement aux
  deux sources précédentes.
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
- Suite de tests : 226 tests passants, dont une suite par source
  d'extraction (`tests/test_ingest_hubeau.py`, `test_ingest_scraping.py`,
  `test_ingest_legacy_db.py`, `test_ingest_bigdata_duckdb.py`) couvrant
  mapping, conversion d'unité/format et idempotence (un second import ne
  duplique rien) — même patron de test répété sur les 4 sources
  automatisées.

## 5. Difficultés rencontrées

Le mapping Hub'Eau, je savais dès le départ qu'il ne serait pas parfait —
le jeu de données Kaggle qui a servi à entraîner le modèle et le contrôle
sanitaire français ne mesurent tout simplement pas les mêmes paramètres.
Ce que je n'avais pas anticipé, c'est à quel point certains écarts
seraient tranchés : `Chloramines` s'approxime tant bien que mal par le
chlore total mesuré (un proxy, pas une équivalence chimique — je le
note explicitement pour ne pas laisser croire à une correspondance
propre), mais `Solids` (matières dissoutes totales) n'a purement et
simplement aucun équivalent suivi en France. Cette feature reste `None`
pour toute donnée Hub'Eau, point final — ce qui limite mécaniquement les
prédictions automatiques sur cette source. J'aurais pu me contenter de le
déduire en lisant la documentation Hub'Eau, mais j'ai préféré vérifier
par un vrai appel réseau : je ne voulais pas affirmer une correspondance
que je n'avais pas réellement observée.

Le scraping m'a fait rater une feature d'une façon que je n'avais pas
vue venir : je cherchais la ligne "pH" dans la table Wikipédia par une
simple sous-chaîne, sans penser que "ph" apparaît aussi tel quel à
l'intérieur de "sul**ph**ate" — la valeur de sulfate écrasait
silencieusement la vraie valeur de pH pour les organismes qui avaient les
deux. Aucun message d'erreur, juste une donnée fausse. Je ne l'ai vu
qu'en écrivant un test qui vérifie explicitement les deux valeurs côte à
côte, pas en relisant le code — corrigé en cherchant "ph" en frontière de
mot plutôt qu'en sous-chaîne. Fiche complète (branche, test, correction) :
voir [[doc_technique_e5]] et `docs/incident.md`.

Le blocage le plus bête, avec le recul, c'est que `docs/` était resté
dans `.gitignore` depuis la création du dépôt. Toute la documentation —
MCD, RGPD, user stories — existait donc uniquement en local, jamais
partagée, alors que CLAUDE.md exige explicitement sa présence dans
`docs/`. Personne ne l'avait remarqué parce que "ça marchait" en local :
c'est en croisant le dépôt réel avec les exigences de certification que
le problème m'a sauté aux yeux. Correction triviale une fois vue, mais
un bon rappel que ce qui tourne sur ma machine ne veut rien dire tant que
ce n'est pas partagé.

Étendre le schéma m'a aussi pris au dépourvu à un endroit où je ne
l'attendais pas : ajouter `IngestionSource.OPENDATA` à l'énumération
existante (`MANUAL`/`OCR`/`API`) avait l'air trivial. Sauf que SQLite
grave la contrainte `CHECK` d'une colonne `Enum` au moment de la création
de la table — une base déjà initialisée avec l'ancienne énumération
refuse silencieusement la nouvelle valeur tant qu'elle n'est pas
recréée. Rien de grave une fois compris, mais un piège à surveiller à
chaque nouvelle évolution de ce genre d'énumération.
