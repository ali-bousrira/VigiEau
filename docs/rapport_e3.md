---
type: rapport-professionnel
epreuve: E3
bloc: 2
competences: [C9, C10, C11, C12, C13]
---

> Brouillon généré à partir du code réel du dépôt. Structure imposée
> (contexte, démarche, choix techniques, résultats, difficultés
> rencontrées) — **la voix reste à retravailler** avant dépôt, en
> particulier §5, pour sonner comme ton vécu et pas comme un résumé de
> commits.

# Rapport professionnel — E3 : Modèle en production

## 1. Contexte

Le modèle de classification de la potabilité (XGBoost, entraîné sur le
jeu de données Waterflow d'origine) doit être exposé de façon fiable dans
l'application, tracé (quelle version a produit quelle prédiction), et
ré-entraînable/validable sans intervention manuelle. Avant cette phase, le
pipeline d'entraînement n'existait que sous forme de notebooks manuels
(`water_xgboost.ipynb`, `water_mlflow_server.ipynb`) — aucune chaîne
automatisée ne le reproduisait. L'enjeu du Bloc 2 (volet modèle) est de
passer de "ça marche dans mon notebook" à un service de prédiction
production-ready et une chaîne MLOps qui valide avant de publier.

## 2. Démarche

### 2.1 Service de prédiction

`predict_service.py` expose `run_prediction(mesures)` : chargement
**paresseux** du modèle (au premier appel, pas à l'import du module) —
MLflow Model Registry en priorité (`MLFLOW_URI=models:/WaterQualityXGBoost/1`),
repli automatique sur un fichier XGBoost local
(`model_artifacts/xgboost_model.json`) si le registre est indisponible.
Pipeline : validation des 9 features (aucune ne doit être `None`) →
`RobustScaler` → `XGBoost` → `{potable, label, probability, model_version}`.
Le `model_version` est renvoyé dans chaque réponse API, ce qui trace
précisément quelle version du modèle a produit quelle prédiction stockée.

### 2.2 Chaîne d'entraînement automatisée

`scripts/train_model.py` reproduit fidèlement le pipeline des notebooks,
sous forme de fonctions pures et testables : nettoyage (dédoublonnage,
imputation médiane groupée par classe, winsorisation 1 %/99 %) → split
80/20 stratifié → `RobustScaler` → `SMOTE` → `XGBClassifier`
(hyperparamètres fixes) → cross-validation 5-fold → **gate qualité** →
sauvegarde des artefacts → enregistrement MLflow. Le gate est la pièce
centrale : le modèle n'est sauvegardé et enregistré **que si** il dépasse
un seuil de ROC-AUC et de F1 sur la validation — sinon le script sort en
échec et rien n'est publié. Détail complet du schéma : [[mlops_pipeline]].

### 2.3 CI/CD dédiée

`.github/workflows/model-ci.yml`, séparée de la CI applicative
(déclencheur différent : push sur `water_potability.csv`/`scripts/train_model.py`
ou déclenchement manuel) : validation des données (réutilise
`tests/test_unitaires.py::TestDataset`, pas de duplication) → entraînement
→ gate → publication des artefacts comme artefact GitHub Actions.

## 3. Choix techniques

- **Chargement paresseux plutôt qu'au démarrage** : évite qu'un import du
  module échoue si MLflow n'est pas encore disponible au moment du
  déploiement, et permet le repli sur fichier local sans changement de
  code.
- **Seuil de qualité absolu, pas de comparaison au modèle précédent** :
  `mlflow_water.db` étant gitignoré, chaque run CI repart d'un registre
  MLflow vide — comparer à un "champion" précédent n'aurait pas de sens
  dans cet état. Assumé et documenté plutôt que contourné artificiellement.
- **Hyperparamètres et graine aléatoire fixes**, identiques à
  `model_artifacts/metadata.json` : reproductibilité et comparabilité
  avec le modèle actuellement déployé, pas une réoptimisation.
- **CI modèle séparée de la CI applicative** : les deux n'ont ni le même
  déclencheur ni la même finalité ; les mélanger aurait rendu les deux
  moins lisibles.

## 4. Résultats

- Pipeline exécuté en conditions réelles (pas seulement en test) :
  Accuracy 0.7912, F1 0.7329, ROC-AUC 0.8744 — cohérent avec la référence
  historique du modèle actuellement déployé (ROC-AUC ≈ 0.8765).
- Gate configuré à ROC-AUC ≥ 0.82 et F1 ≥ 0.65 (marge sous la référence
  pour absorber la variance normale d'un ré-entraînement sans masquer une
  vraie régression — voir §5).
- `POST /predict` autonome : accepte des mesures brutes ou un
  `prelevement_id` existant, retourne la prédiction sans rien persister
  (endpoint de test/consultation, distinct du pipeline d'ingestion).
- Suite de tests : `tests/test_train_model.py` (pipeline d'entraînement
  sur données synthétiques, hyperparamètres réduits, MLflow mocké) et
  `tests/test_unitaires.py` (validation, scaling, prédiction) — 198 tests
  passants au total sur l'ensemble du dépôt.

## 5. Difficultés rencontrées

**Le pipeline ne tournait pas tel quel.** `imbalanced-learn` (SMOTE) est
utilisé par le notebook d'entraînement d'origine mais n'a jamais été
ajouté à `requirements.txt` — je ne l'ai découvert qu'en essayant
d'exécuter le pipeline pour de vrai, pas en le lisant. Sans cette
dépendance, aucune automatisation n'était possible.

**MLflow a rejeté silencieusement mes métriques la première fois.** Les
noms de métriques que j'affiche en console (`"Rappel (Recall)"`,
`"Avg Precision (PR-AUC)"`) contiennent des accents et des parenthèses ;
l'API `mlflow.log_metrics()` les refuse (seuls alphanumériques, `_`, `-`,
`.`, espace et `/` sont acceptés) et lève une exception à
l'enregistrement. Je ne l'ai vu qu'en lançant un entraînement réel de
bout en bout, pas avec les tests unitaires (qui mockent MLflow) — j'ai dû
ajouter une table de correspondance vers des noms techniques sûrs
(`MLFLOW_METRIC_NAMES`).

**Choisir le bon seuil de gate a demandé une vraie mesure, pas une
estimation.** Mon premier seuil (ROC-AUC ≥ 0.85) est passé de justesse
lors d'un run réel (0.8744 obtenu, une marge de 0.024 à peine) — largement
dans la zone où une variance normale d'entraînement (ordre d'exécution
des histogrammes XGBoost en parallèle, versions de bibliothèques) aurait
pu faire échouer un run parfaitement sain. Je l'ai baissé à 0.82 après
avoir observé un vrai résultat plutôt que de deviner une marge de
sécurité a priori.

**Le même piège de mock qu'ailleurs dans le projet.** Les fixtures de
tests qui patchaient `mlflow.xgboost.load_model`/`joblib.load` **pendant
l'import** du module ont cessé de fonctionner dès que le chargement du
modèle est devenu paresseux (le patch n'est plus actif au moment où le
chargement a réellement lieu) — j'ai dû adapter les tests pour injecter
directement `predict_service._model`/`_scaler` après import plutôt que de
dépendre du moment du chargement. Un rappel que changer une stratégie de
chargement a des effets de bord sur la façon dont on peut la tester.
