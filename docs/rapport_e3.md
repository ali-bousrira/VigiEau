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

Rien de tout ça ne s'est vu en lisant le code — seulement en essayant de
faire tourner le pipeline pour de vrai. La première surprise :
`imbalanced-learn` (SMOTE), utilisé par le notebook d'entraînement
d'origine, n'avait jamais été ajouté à `requirements.txt`. Sans cette
dépendance, aucune automatisation n'était possible — j'ai dû le
découvrir à l'exécution, pas à la lecture.

Une fois le pipeline lancé, MLflow a rejeté mes métriques en silence. Les
noms que j'affichais en console (`"Rappel (Recall)"`, `"Avg Precision
(PR-AUC)"`) contiennent des accents et des parenthèses, et
`mlflow.log_metrics()` n'accepte que l'alphanumérique, `_`, `-`, `.`,
l'espace et `/` — une exception à l'enregistrement, invisible dans les
tests unitaires puisqu'ils mockent MLflow. Il a fallu un entraînement
réel de bout en bout pour la voir, et une table de correspondance vers
des noms techniques sûrs (`MLFLOW_METRIC_NAMES`) pour la corriger.

Choisir le seuil du gate qualité a été le moment où j'ai le plus douté.
Mon premier réflexe (ROC-AUC ≥ 0.85) est passé de justesse sur un run
réel — 0.8744 obtenu, une marge de 0.024 à peine, largement dans la zone
où une variance d'entraînement parfaitement normale (ordre d'exécution
des histogrammes XGBoost en parallèle, versions de bibliothèques) aurait
pu faire échouer un run parfaitement sain. Je l'ai baissé à 0.82 après
avoir vu un vrai résultat, pas en devinant une marge de sécurité a
priori — deviner aurait été plus rapide, mais je n'aurais eu aucune
garantie que le chiffre choisi corresponde à quoi que ce soit de réel.

Et pour finir, le même piège de mock que j'avais déjà croisé ailleurs
dans le projet : les fixtures qui patchaient
`mlflow.xgboost.load_model`/`joblib.load` **pendant l'import** du module
ont cessé de fonctionner dès que le chargement du modèle est devenu
paresseux. Le patch n'était plus actif au moment où le chargement avait
réellement lieu. J'ai dû injecter directement
`predict_service._model`/`_scaler` après import plutôt que de dépendre
du moment du chargement — un rappel que changer une stratégie de
chargement a des effets de bord sur la façon dont on peut la tester, même
quand le changement lui-même semble anodin.
