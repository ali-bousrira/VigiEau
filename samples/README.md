# Samples — Fiches laboratoire anonymisées

Ce dossier contient des exemples de fiches de prélèvement à utiliser
pour tester le pipeline OCR de la plateforme Waterflow 2.

## Fichiers disponibles

| Fichier | Type | Usage |
|---|---|---|
| `fiche_labo_anonymisee.txt` | Texte brut | Soumission directe à `POST /ingest/ocr` ou `POST /ingest/ocr-and-predict` |
| `exemple_extraction_ocr.json` | JSON | Résultat OCR attendu après traitement de la fiche ci-dessus |

## Comment tester

```bash
# Soumettre la fiche et obtenir la prédiction en une seule requête
curl -X POST http://localhost:8080/ingest/ocr-and-predict \
  -H "X-API-Key: <votre_cle_api>" \
  -F "file=@samples/fiche_labo_anonymisee.txt;type=text/plain"
```

> **Note :** Pour un test plus réaliste, remplacez le fichier `.txt` par
> une image (`.jpg`, `.png`) ou un PDF scan de rapport de laboratoire.
> OCR.space et Claude Vision supportent ces formats nativement.

## Format des fiches supportées

L'API OCR accepte les types MIME suivants :

- `image/jpeg`, `image/png`, `image/webp`, `image/gif`
- `application/pdf`

Taille maximale : **20 Mo** par fichier.
