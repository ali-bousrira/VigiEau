# Modèle de données — Waterflow 2

## MCD (Modèle Conceptuel de Données)

```
┌──────────────────────────────┐
│           CLIENTS            │
├──────────────────────────────┤
│ id (UUID, PK)                │
│ id_client (unique)           │
│ denomination                 │
│ adresse                      │
│ api_key_hash (SHA-256)       │
│ api_key_hint (4 chars)       │
│ actif (bool)                 │
│ rgpd_consent (bool)          │
│ rgpd_consent_at (datetime)   │
│ anonymised_at (datetime)     │
│ created_at (datetime)        │
└──────────────┬───────────────┘
               │ 1
               │ possède
               │ N
┌──────────────▼───────────────┐
│         PRELEVEMENTS         │
├──────────────────────────────┤
│ id (UUID, PK)                │
│ client_id (FK → clients)     │
│ date_prelevement (datetime)  │
│ lieu (string)                │
│ source (MANUAL/OCR/API/      │
│         OPENDATA)             │
│ fichier_nom (string)         │
│ fichier_type (string)        │
│ ocr_raw_text (text)          │
│ ocr_warnings (JSON)          │
│ created_at (datetime)        │
└──────┬───────────────┬───────┘
       │ 1             │ 1
       │               │
       │ 1             │ 1
┌──────▼──────┐  ┌─────▼───────────┐
│   MESURES   │  │   PREDICTIONS   │
├─────────────┤  ├─────────────────┤
│ id (UUID)   │  │ id (UUID, PK)   │
│ prelev_id   │  │ prelev_id (FK)  │
│ ph          │  │ potable (0/1)   │
│ Hardness    │  │ probability     │
│ Solids      │  │ model_version   │
│ Chloramines │  │ created_at      │
│ Sulfate     │  └─────────────────┘
│ Conductivity│
│ Organic_    │
│  carbon     │
│ Trihalometh.│
│ Turbidity   │
└─────────────┘

┌──────────────────────────────┐
│          AUDIT_LOGS          │
├──────────────────────────────┤
│ id (UUID, PK)                │
│ timestamp (datetime)         │
│ actor_type (client / expert) │
│ actor_id (string)            │
│ actor_role (string)          │
│ ip_address (pseudonymisé)    │
│ action (string)              │
│ resource_id (string)         │
│ status_code (int)            │
│ detail (text)                │
└──────────────────────────────┘

┌──────────────────────────────┐
│        REQUEST_METRICS       │
├──────────────────────────────┤
│ id (UUID, PK)                │
│ timestamp (datetime)         │
│ route (string)               │
│ method (string)              │
│ status_code (int)            │
│ duration_ms (float)          │
│ actor_hint (string)          │
└──────────────────────────────┘
```

## MPD — Relations

| Table | Clé étrangère | Cardinalité |
|---|---|---|
| `prelevements` | `client_id → clients.id` | N:1 |
| `mesures` | `prelevement_id → prelevements.id` | 1:1 (cascade delete) |
| `predictions` | `prelevement_id → prelevements.id` | 1:1 (cascade delete) |
| `audit_logs` | aucune FK (journal immuable) | — |
| `request_metrics` | aucune FK | — |

## Notes RGPD sur le modèle

- `clients.api_key_hash` : jamais la clé en clair, uniquement le hash SHA-256
- `clients.api_key_hint` : 4 premiers caractères pour identification humaine
- `clients.anonymised_at` : si renseigné, le compte est effacé (droit à l'oubli)
- `audit_logs.ip_address` : dernier octet masqué (`192.168.1.xxx`)
- La table `audit_logs` est en lecture seule par convention applicative
