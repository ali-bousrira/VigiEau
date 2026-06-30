"""
tests/conftest.py — Configuration pytest commune à tous les tests Waterflow 2.

Responsabilités :
  1. Ajoute la racine du projet au sys.path (nécessaire pour `from api.* import ...`).
  2. Initialise les variables d'environnement de test UNE SEULE FOIS,
     avant que tout module de test ne soit importé — garantit que auth.py
     charge les bons tokens experts dès le premier import.

Tokens experts disponibles dans les tests :
  alice / token-alice  → rôle analyste
  bob   / token-bob    → rôle exploit (super-rôle, accès à tout)
"""

import sys
import os

# ── 1. Chemin Python ──────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 2. Variables d'environnement ─────────────────────────────────────────────
os.environ.setdefault("DATABASE_URL",      "sqlite:///:memory:")
os.environ.setdefault("MLFLOW_URI",        "mock")
os.environ.setdefault("SCALER_PATH",       "mock")
os.environ.setdefault("OCR_SPACE_API_KEY", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "")

# EXPERT_TOKENS est forcé (pas setdefault) pour garantir la cohérence
# entre tous les fichiers de test d'une même session pytest.
os.environ["EXPERT_TOKENS"] = "alice:token-alice:analyste,bob:token-bob:exploit"
