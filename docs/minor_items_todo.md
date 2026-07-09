# Reste à faire — points mineurs

> Brouillon de suivi, pas un livrable de certification. Issu de
> `RAPPORT_CONFORMITE.md` et [[plan_certification_rncp]] §5. Coché au fur
> et à mesure, supprimable une fois terminé.

- [x] **Vue "Audit" dans l'UI exploit** — nouvel onglet visible uniquement
  pour `role="exploit"` (vérifié : masqué pour analyste), filtre
  `actor_type`/`actor_id`/`action`, table paginée. Vérifié en réel avec
  Playwright (connexion exploit → 3 entrées réelles affichées, IP
  pseudonymisée visible ; connexion analyste → bouton absent).
- [x] **Dropdown client dans l'UI Prélèvements** — `f-client` est devenu
  un `<select>` alimenté par `GET /admin/clients` (trié par dénomination,
  chargé une fois par session). Vérifié en réel avec Playwright : options
  correctement peuplées et triées, sélection + filtre fonctionnels.
- [ ] **Badge CI/CD dans `README.md`** — badge de statut GitHub Actions
  pointant vers `.github/workflows/ci.yml` (remote `helio-aubrun/waterflow`).
- [ ] **Note SQLite/PostgreSQL dans `README.md`** — expliciter dans
  "Limites connues" que `DATABASE_URL` accepte PostgreSQL mais que
  `docker-compose.yml` n'inclut pas de service dédié, avec les étapes pour
  basculer.
- [ ] **Rafraîchir l'arborescence dans `README.md`** — le bloc
  "Architecture" liste encore `ci.yml` à la racine (déplacé depuis) et
  omet `scripts/ingest_hubeau.py`, `scripts/train_model.py`,
  `.github/workflows/model-ci.yml`, `docs/`. Mise à jour mécanique, pas de
  réécriture de prose.

Déjà fait (vérifié, pas dans ce lot) : `samples/README.md` existe déjà
(roadmap P3).
