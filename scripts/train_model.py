"""
scripts/train_model.py — Entraîne, valide et enregistre le modèle XGBoost.

Reproduit fidèlement le pipeline de water_xgboost.ipynb (nettoyage,
RobustScaler, SMOTE, XGBoost, cross-validation) sous une forme scriptée et
automatisable en CI (voir .github/workflows/model-ci.yml).

Chaîne : validation des données (tests/test_unitaires.py::TestDataset,
exécutée en amont par la CI) → nettoyage → split → entraînement →
cross-validation → évaluation → seuil de qualité (gate) → sauvegarde des
artefacts → enregistrement MLflow.

Limite connue : mlflow_water.db / model_artifacts/ sont gitignorés
("régénérés localement") — un run CI repart d'un registre MLflow vide à
chaque exécution, donc pas d'historique inter-runs pour comparer un
nouveau modèle à un "champion" précédent. Le gate porte sur un seuil de
qualité absolu (--min-roc-auc / --min-f1), pas sur une comparaison
relative. Voir docs/mlops_pipeline.md.

Usage :
    python scripts/train_model.py
    python scripts/train_model.py --min-roc-auc 0.82 --min-f1 0.65
    python scripts/train_model.py --skip-cv --tracking-uri sqlite:///scratch_mlflow.db
"""

import sys
import os
import json
import argparse
import logging

import numpy as np
import pandas as pd
import joblib
from scipy.stats.mstats import winsorize
from sklearn.preprocessing import RobustScaler
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.metrics import (
    accuracy_score, f1_score, precision_score, recall_score,
    roc_auc_score, average_precision_score,
)
from imblearn.over_sampling import SMOTE
import xgboost as xgb
import mlflow
import mlflow.xgboost

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")   # évite un crash sur console Windows cp1252
except (AttributeError, ValueError):
    pass

logger = logging.getLogger(__name__)

SEED = 42

FEATURES = [
    "ph", "Hardness", "Solids", "Chloramines", "Sulfate",
    "Conductivity", "Organic_carbon", "Trihalomethanes", "Turbidity",
]

XGB_PARAMS = dict(
    n_estimators=500, max_depth=6, learning_rate=0.05,
    subsample=0.8, colsample_bytree=0.8, min_child_weight=3,
    gamma=0.1, reg_alpha=0.1, reg_lambda=1.0,
    eval_metric="logloss", random_state=SEED, n_jobs=-1,
)

ARTIFACT_DIR         = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "model_artifacts")
DEFAULT_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "sqlite:///mlflow_water.db")
EXPERIMENT_NAME      = "experiment_water_quality"
REGISTERED_MODEL     = "WaterQualityXGBoost"

MISSING_VALUE_COLS = ["ph", "Sulfate", "Trihalomethanes"]

# Les noms de métriques affichés (evaluate()) contiennent accents/parenthèses,
# interdits par MLflow (alphanumériques, _, -, ., espace, / uniquement).
MLFLOW_METRIC_NAMES = {
    "Accuracy":                "accuracy",
    "F1-Score":                "f1_score",
    "Précision":               "precision",
    "Rappel (Recall)":         "recall",
    "ROC-AUC":                 "roc_auc",
    "Avg Precision (PR-AUC)":  "pr_auc",
}


def load_raw(path="water_potability.csv") -> pd.DataFrame:
    return pd.read_csv(path)


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """Dédoublonnage, imputation médiane groupée par classe, winsorisation 1%/99%."""
    df = df.drop_duplicates().copy()

    for col in MISSING_VALUE_COLS:
        if col not in df.columns or not df[col].isna().any():
            continue
        medians = df.groupby("Potability")[col].transform("median")
        df[col] = df[col].fillna(medians).fillna(df[col].median())

    df[FEATURES] = df[FEATURES].apply(
        lambda col: pd.Series(winsorize(col, limits=[0.01, 0.01]), index=col.index)
    )
    return df


def split_scale(df: pd.DataFrame, test_size=0.2, seed=SEED):
    X = df[FEATURES]
    y = df["Potability"]
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=test_size, stratify=y, random_state=seed)

    scaler = RobustScaler()
    X_train_sc = scaler.fit_transform(X_train)
    X_val_sc   = scaler.transform(X_val)
    return X_train_sc, X_val_sc, y_train.reset_index(drop=True), y_val.reset_index(drop=True), scaler


def resample(X_train_sc, y_train, seed=SEED):
    smote = SMOTE(random_state=seed)
    return smote.fit_resample(X_train_sc, y_train)


def train(X_res, y_res, X_val_sc, y_val, params=XGB_PARAMS):
    model = xgb.XGBClassifier(**params)
    model.fit(X_res, y_res, eval_set=[(X_res, y_res), (X_val_sc, y_val)], verbose=False)
    return model, model.evals_result()


def cross_validate(X_res, y_res, params=XGB_PARAMS, n_splits=5, seed=SEED):
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    return cross_val_score(xgb.XGBClassifier(**params), X_res, y_res,
                            cv=cv, scoring="roc_auc", n_jobs=-1)


def evaluate(model, X_val_sc, y_val) -> dict:
    y_pred      = model.predict(X_val_sc)
    y_pred_prob = model.predict_proba(X_val_sc)[:, 1]
    return {
        "Accuracy":               float(accuracy_score(y_val, y_pred)),
        "F1-Score":                float(f1_score(y_val, y_pred)),
        "Précision":               float(precision_score(y_val, y_pred)),
        "Rappel (Recall)":         float(recall_score(y_val, y_pred)),
        "ROC-AUC":                 float(roc_auc_score(y_val, y_pred_prob)),
        "Avg Precision (PR-AUC)":  float(average_precision_score(y_val, y_pred_prob)),
    }, y_pred, y_pred_prob


def meets_threshold(metrics: dict, min_roc_auc: float, min_f1: float) -> bool:
    return metrics["ROC-AUC"] >= min_roc_auc and metrics["F1-Score"] >= min_f1


def save_artifacts(model, scaler, metrics, evals_result, cv_scores, params,
                    n_train_raw, n_train_smote, n_val, out_dir=None):
    out_dir = out_dir if out_dir is not None else ARTIFACT_DIR
    os.makedirs(out_dir, exist_ok=True)

    model.save_model(os.path.join(out_dir, "xgboost_model.json"))
    joblib.dump(scaler, os.path.join(out_dir, "robust_scaler.pkl"))

    metadata = {
        "features":      FEATURES,
        "params":        {k: str(v) for k, v in params.items()},
        "metrics":       {k: round(float(v), 6) for k, v in metrics.items()},
        "cv_mean":       round(float(cv_scores.mean()), 6) if cv_scores is not None else None,
        "cv_std":        round(float(cv_scores.std()), 6) if cv_scores is not None else None,
        "n_train_raw":   n_train_raw,
        "n_train_smote": n_train_smote,
        "n_val":         n_val,
    }
    with open(os.path.join(out_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    with open(os.path.join(out_dir, "evals_result.json"), "w", encoding="utf-8") as f:
        json.dump(evals_result, f)

    if cv_scores is not None:
        np.save(os.path.join(out_dir, "cv_scores.npy"), cv_scores)

    return metadata


def log_to_mlflow(model, params, metrics, cv_scores, X_val_sc,
                   tracking_uri=DEFAULT_TRACKING_URI,
                   experiment_name=EXPERIMENT_NAME,
                   registered_model_name=REGISTERED_MODEL):
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)

    with mlflow.start_run() as run:
        mlflow.log_params({k: str(v) for k, v in params.items()})
        mlflow.log_metrics({
            MLFLOW_METRIC_NAMES.get(k, k): float(v)
            for k, v in metrics.items() if isinstance(v, (int, float))
        })
        if cv_scores is not None:
            mlflow.log_metrics({
                "cv_roc_auc_mean": float(cv_scores.mean()),
                "cv_roc_auc_std":  float(cv_scores.std()),
            })
        input_example = pd.DataFrame(X_val_sc[:3], columns=FEATURES)
        mlflow.xgboost.log_model(
            model, artifact_path="xgboost_model",
            registered_model_name=registered_model_name,
            input_example=input_example,
        )
        return run.info.run_id


def run_pipeline(args) -> int:
    """Exécute le pipeline complet. Retourne le code de sortie (0 = succès)."""
    print("  Chargement + nettoyage du jeu de données...")
    df_raw   = load_raw(args.data)
    df_clean = clean_data(df_raw)

    print("  Split train/val + scaling...")
    X_train_sc, X_val_sc, y_train, y_val, scaler = split_scale(df_clean)

    print("  SMOTE...")
    X_res, y_res = resample(X_train_sc, y_train)

    print(f"  Entraînement XGBoost ({args.n_estimators} arbres)...")
    params = {**XGB_PARAMS, "n_estimators": args.n_estimators}
    model, evals_result = train(X_res, y_res, X_val_sc, y_val, params)

    cv_scores = None
    if not args.skip_cv:
        print("  Cross-validation (5 folds)...")
        cv_scores = cross_validate(X_res, y_res, params)

    print("  Évaluation...")
    metrics, _, _ = evaluate(model, X_val_sc, y_val)
    for name, value in metrics.items():
        print(f"    {name:<24} {value:.4f}")

    if not meets_threshold(metrics, args.min_roc_auc, args.min_f1):
        print(f"  ✗  Seuil non atteint (ROC-AUC >= {args.min_roc_auc}, "
              f"F1 >= {args.min_f1}) — modèle NON enregistré.")
        return 1

    print("  ✓  Seuil de qualité atteint.")
    save_artifacts(model, scaler, metrics, evals_result, cv_scores, params,
                    n_train_raw=len(X_train_sc), n_train_smote=len(X_res), n_val=len(X_val_sc))
    print(f"  ✓  Artefacts sauvegardés dans {ARTIFACT_DIR}")

    if not args.no_mlflow:
        run_id = log_to_mlflow(model, params, metrics, cv_scores, X_val_sc,
                                tracking_uri=args.tracking_uri)
        print(f"  ✓  Modèle enregistré dans MLflow ({args.tracking_uri}) — run {run_id}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Entraîne, évalue et enregistre le modèle Waterflow (MLOps)")
    parser.add_argument("--data", default="water_potability.csv")
    parser.add_argument("--min-roc-auc", type=float, default=0.82)
    parser.add_argument("--min-f1", type=float, default=0.65)
    parser.add_argument("--n-estimators", type=int, default=XGB_PARAMS["n_estimators"])
    parser.add_argument("--skip-cv", action="store_true")
    parser.add_argument("--no-mlflow", action="store_true", help="Ne pas logger dans MLflow")
    parser.add_argument("--tracking-uri", default=DEFAULT_TRACKING_URI)
    args = parser.parse_args()

    print("═" * 60)
    print("  Waterflow 2 — Entraînement du modèle")
    print("═" * 60)

    exit_code = run_pipeline(args)

    print("═" * 60)
    print("  Terminé." if exit_code == 0 else "  Échec du gate qualité.")
    print("═" * 60)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
