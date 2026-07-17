---
type: rapport-professionnel
epreuve: E3
bloc: 2
competences: [C9, C10, C11, C12, C13]
---

> Brouillon généré à partir du code réel du dépôt. Structure organisée
> **par compétence** (C9 à C13), conforme à la consigne du REAC. **La
> voix reste à retravailler** avant dépôt, en particulier les encarts
> "Difficulté", pour sonner comme ton vécu et pas comme un résumé de
> commits.

# Rapport professionnel — E3 : Modèle en production

**Dépôt du projet (public)** : https://github.com/ali-bousrira/VigiEau

## Contexte

Le modèle de classification de la potabilité (XGBoost, entraîné sur le
jeu de données Waterflow d'origine) doit être exposé de façon fiable dans
l'application, tracé (quelle version a produit quelle prédiction), et
ré-entraînable/validable sans intervention manuelle — le versant
dev/ML du projet chef-d'œuvre, dont le versant gestion de projet est
couvert par [[rapport_e4]] (même code, même dépôt, deux angles de
compétences distincts).

---

## C9 — Développer une API exposant un modèle d'IA

Cette compétence évalue la partie API (auth, tests, documentation), pas
le modèle lui-même — voir C11 pour le monitorage du modèle.

- **Endpoint** : `POST /predict` (`routes.py`) — accepte des mesures
  brutes ou un `prelevement_id` existant, retourne la prédiction sans
  rien persister (endpoint de test/consultation, distinct du pipeline
  d'ingestion qui, lui, persiste).
- **Authentification** : `@require_client_key` ou `@require_expert()`
  selon le contexte d'appel — mêmes décorateurs que le reste de l'API,
  pas de mécanisme d'auth séparé pour cette route.
- **Tests** : `tests/test_unitaires.py` (validation des features, scaling,
  prédiction) et `tests/test_api.py` (auth, codes retour) — modèle et
  scaler mockés pour ne dépendre d'aucun artefact réel en CI.
- **OWASP** : le service applique les mêmes protections que le reste de
  l'API — aucune injection SQL possible (requêtes 100% paramétrées via
  l'ORM), et une revue de sécurité menée cette session sur l'ensemble du
  dépôt a corrigé une XSS stockée dans le rendu du journal d'audit
  (`templates/index.html`) qui aurait pu affecter un expert consultant
  des données issues, indirectement, d'un appel à ce type d'endpoint —
  détail dans [[doc_technique_e5]].

---

## C10 — Intégrer l'API d'un modèle ou d'un service d'IA tiers

Ici on intègre une API tierce, pas celle qu'on développe soi-même (C9) —
c'est le service OCR (OCR.space + Claude Vision en repli), détaillé côté
veille/paramétrage dans [[doc_technique_e2]] (C6-C8). Cette section se
concentre sur ce que C10 demande spécifiquement : tests sur le service
intégré, et gestion du renouvellement d'authentification.

- **Tests spécifiques à l'intégration** : `tests/test_e2e.py` (10 tests,
  pipeline complet via le service tiers mocké) et 2 tests d'erreur dans
  `tests/test_api.py` — aucun appel réseau réel en CI, cohérent avec le
  reste du projet.

**Limite honnête sur le renouvellement d'authentification** : les clés
`OCR_SPACE_API_KEY`/`ANTHROPIC_API_KEY` sont des clés statiques en
variable d'environnement, sans mécanisme de rotation automatisée dans le
code — un renouvellement se ferait aujourd'hui manuellement (régénérer la
clé chez le fournisseur, mettre à jour le secret de déploiement,
redémarrer). C'est une limite assumée plutôt qu'un mécanisme à inventer
pour ce rapport : la configuration par variable d'environnement rend au
moins la rotation opérationnellement simple, même sans automatisation
applicative.

---

## C11 — Monitorer un modèle d'IA (MLOps)

Monitorage du *modèle*, pas de l'application (ça, c'est C20 — voir
[[doc_technique_e5]], attention à ne pas confondre les deux comme le
REAC le signale lui-même).

- **Registre MLflow** : `predict_service.py` charge le modèle en priorité
  depuis le Model Registry (`MLFLOW_URI=models:/WaterQualityXGBoost/1`),
  avec repli automatique sur un fichier XGBoost local
  (`model_artifacts/xgboost_model.json`) si le registre est indisponible
  — chargement **paresseux** (au premier appel, pas à l'import).
- **Traçabilité par prédiction** : chaque réponse de `/predict` inclut
  `model_version`, ce qui trace précisément quelle version du modèle a
  produit quelle prédiction stockée — sans ce champ, impossible de savoir
  a posteriori quel modèle est responsable d'un résultat donné.
- **Limite connue** : pas de dashboard dédié au monitorage de modèle
  (type Dash/Streamlit) au-delà de l'UI MLflow elle-même — suffisant pour
  ce projet, documenté comme limite plutôt que comme fonctionnalité.

---

## C12 — Programmer les tests automatisés d'un modèle d'IA

- `tests/test_train_model.py` : pipeline d'entraînement sur données
  synthétiques, hyperparamètres réduits, MLflow mocké.
- `tests/test_unitaires.py` : validation des features, scaling, prédiction.

**Couverture de tests, mesurée honnêtement** : la commande CI
(`pytest --cov=api`) rapporte 97 %, mais ce chiffre mesure uniquement les
fichiers de ré-export `api/` (quelques lignes chacun, voir
[[architecture]] pour le détail de ce découpage racine/`api/`), pas la
logique réelle. En pointant la couverture sur les fichiers qui contiennent
vraiment le code (`db.py`, `routes.py`, `auth.py`, `predict_service.py`,
`ocr_service.py`), le chiffre réel est **77 %** — `db.py` (97 %) et
`routes.py` (85 %) sont bien couverts, mais `ocr_service.py` ne l'est qu'à
**21 %** : les fonctions qui font de vrais appels réseau
(`_ocr_space`, `_claude_vision_extract`) ne sont volontairement pas
exercées par la suite (aucun appel réseau réel en CI, voir C10). Ce
chiffre de 77 % est plus honnête que le 97 % actuellement affiché par la
CI — corriger le flag `--cov` est une amélioration identifiée pendant la
rédaction de ce rapport, pas encore appliquée.

---

## C13 — Développer la CI d'un modèle d'IA

`.github/workflows/model-ci.yml`, séparé de la CI applicative
(déclencheur différent : push sur `water_potability.csv`,
`scripts/train_model.py` ou `requirements.txt`, ou déclenchement manuel).
Étapes : validation des données (réutilise
`tests/test_unitaires.py::TestDataset`, pas de duplication) →
entraînement → gate qualité → publication des artefacts comme artefact
GitHub Actions. L'entraînement du modèle ne déclenche pas automatiquement
un déploiement de celui-ci — un choix assumé, pas un oubli.

**Pipeline exécuté en conditions réelles** (pas seulement en test) :
Accuracy 0.7912, F1 0.7329, ROC-AUC 0.8744 — cohérent avec la référence
historique du modèle actuellement déployé (ROC-AUC ≈ 0.8765). Gate
configuré à ROC-AUC ≥ 0.82 et F1 ≥ 0.65.

**Vu tourner en vert pour de vrai** : `model-ci.yml` s'est déclenché tout
seul (modification de `requirements.txt`) lors du push qui a aussi
corrigé la CI applicative cassée — première exécution réelle sur un
runner GitHub Actions depuis la création du workflow, et elle a réussi du
premier coup.

**Difficulté — le pipeline ne tournait pas tel quel.** `imbalanced-learn`
(SMOTE), utilisé par le notebook d'entraînement d'origine, n'avait jamais
été ajouté à `requirements.txt`. Sans cette dépendance, aucune
automatisation n'était possible — je l'ai découvert à l'exécution, pas à
la lecture.

**Difficulté — MLflow a rejeté mes métriques en silence.** Les noms que
j'affichais en console (`"Rappel (Recall)"`, `"Avg Precision (PR-AUC)"`)
contiennent des accents et des parenthèses, et `mlflow.log_metrics()`
n'accepte que l'alphanumérique, `_`, `-`, `.`, l'espace et `/` — une
exception à l'enregistrement, invisible dans les tests unitaires puisqu'ils
mockent MLflow. Corrigé avec une table de correspondance vers des noms
techniques sûrs (`MLFLOW_METRIC_NAMES`).

**Difficulté — choisir le seuil du gate qualité a été le moment où j'ai
le plus douté.** Mon premier réflexe (ROC-AUC ≥ 0.85) est passé de
justesse sur un run réel — 0.8744 obtenu, une marge de 0.024 à peine,
largement dans la zone où une variance d'entraînement parfaitement
normale aurait pu faire échouer un run parfaitement sain. Je l'ai baissé
à 0.82 après avoir vu un vrai résultat, pas en devinant une marge de
sécurité a priori.

**Difficulté — le même piège de mock qu'ailleurs dans le projet.** Les
fixtures qui patchaient `mlflow.xgboost.load_model`/`joblib.load`
**pendant l'import** du module ont cessé de fonctionner dès que le
chargement du modèle est devenu paresseux. J'ai dû injecter directement
`predict_service._model`/`_scaler` après import plutôt que de dépendre
du moment du chargement.
