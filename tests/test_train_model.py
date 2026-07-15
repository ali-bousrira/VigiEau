"""
tests/test_train_model.py — Tests de scripts/train_model.py (C13, chaîne CI/CD modèle).

Utilise des données synthétiques et des hyperparamètres réduits — pas
d'entraînement complet (500 arbres / 5-fold CV) dans la suite pytest, pour
rester rapide. Le pipeline réel tourne dans .github/workflows/model-ci.yml.
"""

import os
import sys
import argparse
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import train_model as tm


def _synthetic_df(n=60, seed=0):
    rng = np.random.default_rng(seed)
    data = {f: rng.normal(loc=50, scale=10, size=n) for f in tm.FEATURES}
    df = pd.DataFrame(data)
    df["Potability"] = [i % 2 for i in range(n)]
    return df


class TestCleanData:

    def test_dedoublonne(self):
        df  = _synthetic_df(20)
        df2 = pd.concat([df, df.iloc[[0]]], ignore_index=True)
        cleaned = tm.clean_data(df2)
        assert len(cleaned) == len(df2) - 1

    def test_impute_valeurs_manquantes(self):
        df = _synthetic_df(30)
        df.loc[0, "ph"] = np.nan
        df.loc[1, "Sulfate"] = np.nan
        df.loc[2, "Trihalomethanes"] = np.nan
        cleaned = tm.clean_data(df)
        assert cleaned["ph"].isna().sum() == 0
        assert cleaned["Sulfate"].isna().sum() == 0
        assert cleaned["Trihalomethanes"].isna().sum() == 0

    def test_winsorize_reduit_les_extremes(self):
        df = _synthetic_df(100)
        df.loc[0, "Turbidity"] = 1e6
        cleaned = tm.clean_data(df)
        assert cleaned["Turbidity"].max() < 1e6


class TestSplitScale:

    def test_shapes_et_ratio(self):
        df = _synthetic_df(100)
        X_train_sc, X_val_sc, y_train, y_val, scaler = tm.split_scale(df, test_size=0.2)
        assert len(X_train_sc) + len(X_val_sc) == 100
        assert len(X_val_sc) == 20
        assert isinstance(scaler, tm.RobustScaler)


class TestResample:

    def test_equilibre_les_classes(self):
        pytest.importorskip("imblearn")
        rng = np.random.default_rng(1)
        X = rng.normal(size=(150, len(tm.FEATURES)))
        y = pd.Series([0] * 120 + [1] * 30)
        X_res, y_res = tm.resample(X, y)
        counts = y_res.value_counts()
        assert counts[0] == counts[1]


class TestTrainEvaluate:

    def test_train_puis_evaluate(self):
        pytest.importorskip("imblearn")
        rng = np.random.default_rng(2)
        X_train = rng.normal(size=(200, len(tm.FEATURES)))
        y_train = pd.Series([0] * 140 + [1] * 60)
        X_val   = rng.normal(size=(40, len(tm.FEATURES)))
        y_val   = pd.Series([0] * 28 + [1] * 12)

        X_res, y_res = tm.resample(X_train, y_train)
        params = {**tm.XGB_PARAMS, "n_estimators": 5}
        model, evals_result = tm.train(X_res, y_res, X_val, y_val, params)

        assert "validation_0" in evals_result
        assert "validation_1" in evals_result

        metrics, y_pred, y_pred_prob = tm.evaluate(model, X_val, y_val)
        assert set(metrics) == {
            "Accuracy", "F1-Score", "Précision", "Rappel (Recall)",
            "ROC-AUC", "Avg Precision (PR-AUC)",
        }
        assert all(0.0 <= v <= 1.0 for v in metrics.values())


class TestMeetsThreshold:

    def test_passe_si_au_dessus_des_deux_seuils(self):
        assert tm.meets_threshold({"ROC-AUC": 0.9, "F1-Score": 0.8}, 0.85, 0.65)

    def test_echoue_si_roc_auc_insuffisant(self):
        assert not tm.meets_threshold({"ROC-AUC": 0.5, "F1-Score": 0.8}, 0.85, 0.65)

    def test_echoue_si_f1_insuffisant(self):
        assert not tm.meets_threshold({"ROC-AUC": 0.9, "F1-Score": 0.1}, 0.85, 0.65)


class TestLogToMlflow:

    def test_enregistre_le_modele(self):
        model = MagicMock()
        with patch("mlflow.set_tracking_uri") as m_uri, \
             patch("mlflow.set_experiment") as _m_exp, \
             patch("mlflow.start_run") as m_run, \
             patch("mlflow.log_params"), \
             patch("mlflow.log_metrics"), \
             patch("mlflow.xgboost.log_model") as m_log_model:
            m_run.return_value.__enter__.return_value.info.run_id = "abc123"
            run_id = tm.log_to_mlflow(
                model, tm.XGB_PARAMS, {"ROC-AUC": 0.9, "F1-Score": 0.8}, None,
                np.zeros((3, len(tm.FEATURES))), tracking_uri="sqlite:///:memory:")

        assert run_id == "abc123"
        m_uri.assert_called_once_with("sqlite:///:memory:")
        m_log_model.assert_called_once()
        _, kwargs = m_log_model.call_args
        assert kwargs["registered_model_name"] == tm.REGISTERED_MODEL


class TestRunPipeline:

    def _write_csv(self, tmp_path, n=150):
        rng = np.random.default_rng(3)
        data = {f: rng.normal(loc=50, scale=10, size=n) for f in tm.FEATURES}
        df = pd.DataFrame(data)
        df["Potability"] = [0] * int(n * 0.7) + [1] * (n - int(n * 0.7))
        path = tmp_path / "synthetic.csv"
        df.to_csv(path, index=False)
        return str(path)

    def test_gate_bas_reussit_sans_mlflow(self, tmp_path):
        pytest.importorskip("imblearn")
        csv_path = self._write_csv(tmp_path)
        args = argparse.Namespace(
            data=csv_path, min_roc_auc=0.0, min_f1=0.0, n_estimators=5,
            skip_cv=True, no_mlflow=True, tracking_uri="sqlite:///:memory:",
        )
        with patch.object(tm, "ARTIFACT_DIR", str(tmp_path / "artifacts")):
            exit_code = tm.run_pipeline(args)
        assert exit_code == 0
        assert os.path.exists(tmp_path / "artifacts" / "metadata.json")

    def test_gate_haut_echoue(self, tmp_path):
        pytest.importorskip("imblearn")
        csv_path = self._write_csv(tmp_path)
        args = argparse.Namespace(
            data=csv_path, min_roc_auc=0.999, min_f1=0.999, n_estimators=5,
            skip_cv=True, no_mlflow=True, tracking_uri="sqlite:///:memory:",
        )
        with patch.object(tm, "ARTIFACT_DIR", str(tmp_path / "artifacts_fail")):
            exit_code = tm.run_pipeline(args)
        assert exit_code == 1
        assert not os.path.exists(tmp_path / "artifacts_fail" / "metadata.json")
