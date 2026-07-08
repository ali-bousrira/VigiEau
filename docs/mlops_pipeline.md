# Chaîne CI/CD du modèle (MLOps) — Waterflow 2

Documente la compétence RNCP **C13** : automatisation de la chaîne
validation → entraînement → évaluation → packaging → (dé)ploiement du
modèle XGBoost, distincte de la CI applicative (`.github/workflows/ci.yml`).

## Origine

Le pipeline d'entraînement n'existait auparavant que sous forme de
notebooks manuels (`water_xgboost.ipynb` pour l'entraînement,
`water_mlflow_server.ipynb` pour le logging MLflow, `water_potability_eda.ipynb`
pour le nettoyage). Il a été porté dans `scripts/train_model.py`, un script
autonome et automatisable, appelé par
`.github/workflows/model-ci.yml`.

## Étapes de la chaîne

```
┌──────────────┐   ┌───────────┐   ┌────────────┐   ┌───────────┐   ┌─────────┐   ┌──────────────┐
│ Validation   │ → │ Nettoyage │ → │ Split +    │ → │ SMOTE +   │ → │ Gate    │ → │ Packaging +  │
│ des données  │   │           │   │ scaling    │   │ training  │   │ qualité │   │ registre     │
│ (pytest)     │   │           │   │            │   │ + CV      │   │         │   │ MLflow       │
└──────────────┘   └───────────┘   └────────────┘   └───────────┘   └─────────┘   └──────────────┘
```

1. **Validation des données** — `pytest tests/test_unitaires.py::TestDataset`
   (colonnes attendues, cible binaire, pas de doublon exact, pH dans
   [0, 14], colonnes avec NA connues). Réutilisé tel quel, pas dupliqué.
2. **Nettoyage** — `scripts/train_model.py::clean_data()` : dédoublonnage,
   imputation par médiane groupée par classe (`ph`, `Sulfate`,
   `Trihalomethanes`), winsorisation 1 %/99 % sur les 9 features. Reproduit
   fidèlement `water_potability_eda.ipynb`.
3. **Split + scaling** — 80/20 stratifié (`random_state=42`), `RobustScaler`
   fit sur train uniquement.
4. **Resampling + entraînement** — `SMOTE` sur le train scalé, puis
   `XGBClassifier` (hyperparamètres fixes, identiques à
   `model_artifacts/metadata.json`), plus une cross-validation `StratifiedKFold(5)`
   (ROC-AUC) informative.
5. **Gate qualité** — le modèle n'est sauvegardé/enregistré que si
   `ROC-AUC ≥ 0.82` **et** `F1 ≥ 0.65` sur la validation (seuils choisis
   avec une marge sous la performance de référence — Accuracy ≈ 0.79,
   F1 ≈ 0.73, ROC-AUC ≈ 0.87 — pour absorber la variance normale d'un
   ré-entraînement sans masquer une vraie régression). Sinon le script sort
   en erreur (`sys.exit(1)`), le job CI échoue, rien n'est enregistré.
6. **Packaging** — artefacts sauvegardés dans `model_artifacts/`
   (`xgboost_model.json`, `robust_scaler.pkl`, `metadata.json`,
   `evals_result.json`, `cv_scores.npy`) et publiés comme artefact
   GitHub Actions (`actions/upload-artifact`, 30 jours de rétention).
7. **Registre MLflow** — `mlflow.xgboost.log_model(..., registered_model_name="WaterQualityXGBoost")`,
   le nom déjà attendu par `predict_service.py`.

## Déclenchement

`.github/workflows/model-ci.yml` se déclenche sur `workflow_dispatch`
(manuel) ou sur push touchant `water_potability.csv`, `scripts/train_model.py`
ou `requirements.txt` — volontairement séparé de `ci.yml` (déclencheur et
finalité différents).

## Limite connue et piste d'amélioration

`mlflow_water.db`, `mlflow_artifacts/` et `model_artifacts/` sont gitignorés
("régénérés localement") : un runner GitHub Actions repart donc d'un
**registre MLflow vide à chaque exécution**, sans historique inter-runs. La
chaîne ne peut donc pas comparer un nouveau modèle à un "champion"
précédent — le gate porte sur un **seuil de qualité absolu**, pas sur une
comparaison relative. Le déploiement en production (mise à jour du modèle
réellement chargé par l'app) reste une étape manuelle, au même titre que le
job `deploy` de `ci.yml` qui nécessite déjà des secrets (`DEPLOY_HOST`,
`DEPLOY_USER`, `DEPLOY_SSH_KEY`) non disponibles dans cet environnement.

Amélioration possible si un serveur MLflow partagé/persistant est mis en
place : comparer automatiquement le nouveau modèle à l'alias `champion` du
registre avant de le promouvoir, et faire pointer `predict_service.py` sur
cet alias plutôt que sur un numéro de version figé.

## Tests

`tests/test_train_model.py` — données synthétiques, hyperparamètres réduits
(pas d'entraînement complet dans la suite pytest), MLflow mocké. Couvre le
nettoyage, le split, le resampling, l'entraînement/évaluation, le gate de
seuil, l'enregistrement MLflow et un run de bout en bout du pipeline
(succès et échec de gate).
