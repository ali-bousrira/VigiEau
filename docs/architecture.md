# Architecture technique — Waterflow 2

## Vue d'ensemble

Waterflow 2 est une plateforme MLOps centralisée exposée via **une seule API Flask** portant trois modules :

```
Client final / Agent terrain
        │
        │  X-API-Key
        ▼
┌─────────────────────────────────────────────────────┐
│                  API Flask (Gunicorn)                │
│                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────┐  │
│  │  Module      │  │  Module      │  │  Module   │  │
│  │  Data        │  │  Prédiction  │  │  OCR      │  │
│  │  (routes.py) │  │  (predict_   │  │  (ocr_    │  │
│  │              │  │   service)   │  │   service)│  │
│  └──────┬──────┘  └──────┬───────┘  └─────┬─────┘  │
│         │                │                 │         │
│         ▼                ▼                 ▼         │
│  ┌─────────────────────────────────────────────┐    │
│  │         SQLAlchemy ORM                      │    │
│  │  clients / prelevements / mesures /          │    │
│  │  predictions / audit_logs / request_metrics │    │
│  └───────────────────┬─────────────────────────┘    │
│                      │                              │
└──────────────────────┼──────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
     SQLite (dev)  PostgreSQL   MLflow Registry
                   (prod)       (XGBoost model)

Analyste / Exploit
        │
        │  Bearer Token
        ▼
  /analyste/*   /exploitation/*   /admin/*
        │
        ▼
  Interface web (templates/index.html)
```

## Composants

| Fichier | Rôle |
|---|---|
| `app.py` | Factory Flask, initialisation DB et routes |
| `main.py` | Point d'entrée Gunicorn |
| `auth.py` | Middleware auth double (clé API client + Bearer expert) |
| `db.py` | Modèles SQLAlchemy + `init_db()` |
| `routes.py` | Toutes les routes (Data, Prédiction, OCR, Admin, Analyste, Exploit) |
| `ocr_service.py` | OCR.space (primaire) + Claude Vision (fallback) |
| `predict_service.py` | Chargement XGBoost via MLflow + pipeline de prédiction |

## Flux d'un prélèvement OCR

```
Client → POST /ingest/ocr-and-predict (PDF/image)
           │
           ▼
     ocr_service.py
           │
     OCR.space API ──(échec)──▶ Claude Vision API
           │
           ▼
     JSON structuré : date, lieu, mesures, observations
           │
           ▼
     Création Prelevement + Mesures en DB
           │
           ▼
     predict_service.py
           │
     RobustScaler ──▶ XGBoost ──▶ potable (0/1) + probabilité
           │
           ▼
     Création Prediction en DB
           │
           ▼
     Réponse JSON au client
```

## Choix techniques

- **Flask** plutôt que FastAPI : cohérence avec Waterflow 1, écosystème maîtrisé
- **SQLite en dev / PostgreSQL en prod** : migration transparente via `DATABASE_URL`
- **OCR.space** comme service primaire après veille comparative (Azure, Google Vision, Tesseract) : meilleur rapport qualité/prix pour PDF en français
- **MLflow** pour la traçabilité du modèle : version enregistrée dans chaque prédiction stockée
- **SHA-256** pour les clés API : comparaison en temps constant (`hashlib.compare_digest`)
