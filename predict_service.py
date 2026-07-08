"""
api/services/predict_service.py — Service de prédiction XGBoost

Chargement paresseux : le modèle est chargé à la première prédiction,
pas à l'import. Stratégie :
  1. MLflow Model Registry (MLFLOW_URI=models:/…)
  2. Fichier local XGBoost JSON (MLFLOW_URI=chemin/vers/model.json)
  3. Fallback automatique sur model_artifacts/xgboost_model.json
"""

import os
import logging

import joblib
import numpy as np
import mlflow.xgboost
import xgboost as xgb

logger = logging.getLogger(__name__)

MLFLOW_MODEL_URI = os.getenv("MLFLOW_URI",   "models:/WaterQualityXGBoost/1")
SCALER_PATH      = os.getenv("SCALER_PATH",  "model_artifacts/robust_scaler.pkl")

_ROOT = os.path.dirname(os.path.abspath(__file__))
_LOCAL_MODEL_FALLBACK = os.path.join(_ROOT, "model_artifacts", "xgboost_model.json")

FEATURES = [
    "ph", "Hardness", "Solids", "Chloramines", "Sulfate",
    "Conductivity", "Organic_carbon", "Trihalomethanes", "Turbidity",
]

_model  = None
_scaler = None
_model_version = None


def _load():
    global _model, _scaler, _model_version

    # Scaler
    scaler_path = SCALER_PATH if os.path.isabs(SCALER_PATH) else os.path.join(os.getcwd(), SCALER_PATH)
    _scaler = joblib.load(scaler_path)
    logger.info("Scaler chargé : %s", scaler_path)

    # Model — essaie MLflow en premier, puis fichier local
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "sqlite:///mlflow_water.db"))

    if not MLFLOW_MODEL_URI.startswith("models:/"):
        # URI pointe directement vers un fichier local
        _load_local(MLFLOW_MODEL_URI)
        return

    try:
        _model = mlflow.xgboost.load_model(MLFLOW_MODEL_URI)
        _model_version = MLFLOW_MODEL_URI
        logger.info("Modèle chargé depuis MLflow : %s", MLFLOW_MODEL_URI)
    except Exception as e:
        logger.warning("MLflow indisponible (%s) — fallback sur fichier local.", e)
        fallback = os.path.normpath(_LOCAL_MODEL_FALLBACK)
        if not os.path.exists(fallback):
            raise RuntimeError(
                f"Modèle MLflow introuvable et aucun fichier local ({fallback}). "
                "Entraînez le modèle ou enregistrez-le dans MLflow."
            ) from e
        _load_local(fallback)


def _load_local(path: str):
    global _model, _model_version
    booster = xgb.Booster()
    booster.load_model(path)
    _model = booster
    _model_version = f"local:{os.path.basename(path)}"
    logger.info("Modèle XGBoost chargé depuis fichier : %s", path)


def run_prediction(mesures: dict) -> dict:
    """
    Applique le scaler et le modèle sur un dict de mesures.

    Paramètres
    ----------
    mesures : dict avec les 9 features (valeurs float ou None)

    Retourne
    --------
    dict { potable, label, probability, model_version }

    Lève ValueError si des features critiques sont nulles.
    """
    global _model, _scaler
    if _model is None:
        _load()

    missing = [f for f in FEATURES if mesures.get(f) is None]
    if missing:
        raise ValueError(f"Features manquantes ou nulles : {missing}")

    try:
        values = np.array([[float(mesures[f]) for f in FEATURES]])
    except (TypeError, ValueError) as e:
        raise ValueError(f"Valeur non numérique dans les mesures : {e}") from e

    values_scaled = _scaler.transform(values)

    if isinstance(_model, xgb.Booster):
        dmatrix = xgb.DMatrix(values_scaled)
        probability = float(_model.predict(dmatrix)[0])
        prediction  = int(probability >= 0.5)
    else:
        prediction  = int(_model.predict(values_scaled)[0])
        probability = float(_model.predict_proba(values_scaled)[0][1])

    return {
        "potable":       prediction,
        "label":         "Potable" if prediction == 1 else "Non potable",
        "probability":   round(probability, 4),
        "model_version": _model_version,
    }
