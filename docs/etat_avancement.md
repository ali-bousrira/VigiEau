---
type: rapport-etat
date: 2026-07-09
---

> Rapport d'état, pas un livrable de certification en soi — photographie
> du dépôt à cette date. Sources : `git log`, suite `pytest`, et la
> matrice Notion "Conformité RNCP 37827 — Waterflow 2" telle que
> synchronisée pour la dernière fois par ce dépôt (connexion Notion
> indisponible dans cette session au moment de la rédaction — aucune
> compétence n'a été retravaillée depuis la dernière synchronisation,
> donc l'état ci-dessous reste à jour). Voir [[plan_certification_rncp]]
> pour le plan qui a produit cet état, [[architecture]] pour le détail
> technique.

# État d'avancement — VigiEau / RNCP 37827

## Résumé exécutif

Les **21 compétences** du référentiel RNCP 37827 (Développeur en
Intelligence Artificielle) couvertes par VigiEau (exercice pédagogique
Waterflow 2) sont **✅ toutes couvertes**. Les 3 lacunes identifiées lors du dernier audit croisé
(C1, C13, C14) ont été comblées et vérifiées en conditions réelles
(appels API réels, entraînement réel, navigation clavier réelle dans un
navigateur headless) — pas seulement relues sur le papier.

Sur les **5 livrables de certification** attendus (rapports professionnels
E1/E3/E4, documentation technique E2/E5), **1 est rédigé** (E2).

La suite de tests compte **198 tests passants, 0 échec**. Les 9 échecs
autrefois signalés comme "préexistants" dans `tests/test_e2e.py` ont été
diagnostiqués et corrigés (voir §5) : c'étaient en réalité 3 bugs distincts
empilés dans le fichier de test lui-même, pas dans l'application.

---

## 1. Matrice de conformité RNCP — état par bloc

| Bloc | Épreuve(s) | Compétences | Statut |
|---|---|---|---|
| Bloc 1 — Données | E1 | C1–C5 | ✅ 5/5 |
| Bloc 2 — Modèles & services IA | E2 + E3 | C6–C13 | ✅ 8/8 |
| Bloc 3 — Application IA | E4 + E5 | C14–C21 | ✅ 9/9 |

**Total : 21/21 ✅.** Détail des 3 compétences fermées cette session (les
18 autres étaient déjà couvertes lors du premier audit) :

| Code | Compétence | Preuve |
|---|---|---|
| C1 | Extraction de données multi-sources | `scripts/ingest_hubeau.py` — import automatisé depuis l'API ouverte Hub'Eau, 7/9 features mappées, testé sur un vrai appel réseau (11 prélèvements réels récupérés) |
| C13 | Chaîne CI/CD du modèle (MLOps) | `scripts/train_model.py` + `.github/workflows/model-ci.yml` — validation → entraînement → gate qualité (ROC-AUC/F1) → packaging → registre MLflow, exécuté en réel (ROC-AUC 0.874) |
| C14 | Accessibilité (RGAA) dans les specs | Audit réel de `templates/index.html`, critères RGAA sur les 10 user stories, correctifs vérifiés au clavier via Playwright |

---

## 2. Travaux réalisés (chronologie de cette session)

| Commit | Contenu |
|---|---|
| `09ae136` | Filtre résultat (potable/non potable) sur la vue analyste + correction d'une régression de chargement du modèle |
| `13478d3` | **C1** — Import Hub'Eau, `docs/` retiré du `.gitignore` (bloquait le versionnement de toute la documentation depuis des semaines) |
| `50ca3f5` | **C13** — Pipeline d'entraînement scripté + CI modèle |
| `1ae7b57` | **C14** — Accessibilité RGAA (user stories, wireframes, correctifs UI) |
| `f8fade8` | Refonte de `docs/architecture.md` pour Obsidian (diagrammes Mermaid) |
| `54891db` | Vue "Audit" dans l'interface exploit |
| `a7bd70d` | Dropdown client dans le filtre Prélèvements |
| `7faefd9` | Badges CI, note SQLite/PostgreSQL, arborescence à jour dans le README |
| `f9acbb1` | Documentation technique E2 (service OCR) |

Tous les commits sont locaux, **aucun push** (consigne explicite).

### Bugs réels trouvés et corrigés en cours de route

Ce ne sont pas des exercices théoriques — chacun a cassé quelque chose de
concret avant d'être corrigé :

- Chargement paresseux du modèle incompatible avec le pattern de mock des
  tests (25 tests cassés, corrigés).
- `imbalanced-learn` utilisé par le notebook d'entraînement mais absent de
  `requirements.txt` — le pipeline ne pouvait pas tourner.
- MLflow rejette les noms de métriques avec accents/parenthèses
  (`"Rappel (Recall)"`) — plantage silencieux à l'enregistrement, corrigé
  par un mapping de noms techniques.
- `showTab()` recalculait la classe CSS de tous les boutons d'onglet à
  chaque clic, ce qui aurait ré-affiché l'onglet "Audit" (réservé au rôle
  `exploit`) aux analystes dès le premier changement d'onglet.
- `docs/` était dans `.gitignore` — toute la documentation existait
  seulement en local depuis la création du dépôt.

---

## 3. Livrables de certification

| # | Document | Statut |
|---|---|---|
| E2 | `docs/doc_technique_e2.md` | ✅ rédigé |
| E5 | `docs/doc_technique_e5.md` | ⏳ à rédiger (prochain) |
| E1 | `docs/rapport_e1.md` | ⏳ à rédiger |
| E3 | `docs/rapport_e3.md` | ⏳ à rédiger |
| E4 | `docs/rapport_e4.md` | ⏳ à rédiger |

Chaque document est un **brouillon technique** généré à partir du code
réel — la voix (surtout "difficultés rencontrées") est à retravailler
avant dépôt pour sonner comme un vécu personnel devant le jury. Détail du
plan et des sources par document : [[plan_certification_rncp]].

---

## 4. Documentation du vault

| Note | Contenu |
|---|---|
| [[architecture]] | Vue d'ensemble technique, diagrammes Mermaid, pattern racine/`api/` |
| [[mcd]] | Modélisation des données (MCD/MPD, Merise) |
| [[rgpd]] | Note RGPD complète |
| [[user_stories]] | 10 user stories + critères RGAA |
| [[wireframes]] | Parcours experts (analyste, exploit, admin) + dette technique documentée |
| [[mlops_pipeline]] | Chaîne CI/CD du modèle en détail |
| [[incident]] | Fiche incident traitée |
| [[roadmap]] | Suivi des correctifs (P1–P4) |
| [[plan_certification_rncp]] | Plan de travail vs. matrice de conformité |
| `docs/doc_technique_e2.md` | Documentation technique E2 (service OCR) |

---

## 5. État technique et limites connues

- **Tests** : 198 passants, 0 échec. Les 9 échecs de `tests/test_e2e.py`
  étaient **3 bugs distincts empilés** dans le fichier de test, masqués
  les uns par les autres :
  1. `EXPERT_TOKENS` — `auth.py` ne lit cette variable qu'une seule fois,
     au premier import. `test_api.py` (collecté avant `test_e2e.py` par
     ordre alphabétique) l'important en premier, le
     `os.environ["EXPERT_TOKENS"] = "admin:token-admin-e2e:exploit"` de
     `test_e2e.py` n'avait aucun effet en suite complète → 401 "Token
     expert invalide" dès la fixture de setup.
  2. Le mock OCR patchait `api.services.ocr_service.extract_from_document`
     (le module de re-export), alors que `routes.py` avait déjà fait
     `from api.services.ocr_service import extract_from_document` — son
     propre nom local, jamais atteint par ce patch → l'extraction OCR
     réelle s'exécutait et échouait (503, aucune clé configurée). Invisible
     tant que le bug 1 bloquait avant d'y arriver.
  3. Le fixture `app` patchait `mlflow.xgboost.load_model`/`joblib.load`
     *pendant l'import*, mais `predict_service.py` charge le modèle
     paresseusement (au premier appel, pas à l'import) depuis la
     refonte C13 — même classe de bug déjà corrigée dans les 3 autres
     fichiers de test cette session, mais explicitement laissée de côté
     ici faute de pouvoir la vérifier tant que le bug 1 masquait tout.
  Correction : `token-bob` (rôle exploit déjà partagé via `conftest.py`)
  au lieu d'un token local ; patch déplacé sur `routes.extract_from_document`
  ; assignation directe de `predict_service._model`/`_scaler`, comme dans
  les autres fichiers de test.
- **Base de données** : SQLite en développement comme en production
  Docker ; `DATABASE_URL` accepte PostgreSQL mais aucun service dédié
  n'est déclaré dans `docker-compose.yml` (voir README, section Limites).
- **Registre MLflow en CI** : reparti à vide à chaque exécution
  (`mlflow_water.db` gitignoré) — le gate qualité du modèle est un seuil
  absolu, pas une comparaison au "champion" précédent (voir
  [[mlops_pipeline]]).
- **Historique Git** : nettement amélioré depuis le début de cette
  session (commits atomiques, messages descriptifs) par rapport à
  l'historique initial du dépôt (`ajout tout`, `add test`, etc. — visible
  en fin de `git log`).

---

## 6. Prochaine étape proposée

Rédiger les 4 documents de certification restants (E5 → E1 → E3 → E4, un
à la fois, avec relecture entre chaque), conformément à
[[plan_certification_rncp]] §"Ordre et rythme".
