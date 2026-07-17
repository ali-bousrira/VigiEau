---
type: rapport-professionnel
epreuve: E4
bloc: 3
competences: [C14, C15, C16, C17, C18, C19]
---

> Brouillon généré à partir du code réel du dépôt. Structure imposée
> (contexte, démarche, choix techniques, résultats, difficultés
> rencontrées) — **la voix reste à retravailler** avant dépôt, en
> particulier §5.

# Rapport professionnel — E4 : Application

## 1. Contexte

Trois profils très différents doivent utiliser la même plateforme sans se
marcher dessus : un client final qui dépose des mesures et consulte ses
propres résultats, un analyste qualité qui a une vue globale, un
responsable d'exploitation qui supervise l'infrastructure — tous via une
**seule interface web**, cohérente avec l'API unique décrite dans
[[architecture]]. L'enjeu du Bloc 3 (volet application) est de livrer une
application réellement utilisable — accessible, conteneurisée, testée en
continu — pas seulement une API qui répond correctement aux tests.

## 2. Démarche

### 2.1 Spécification avant code

Les parcours ont été formalisés avant/à côté de l'implémentation : 10
user stories avec critères d'acceptation ([[user_stories]]), et des
wireframes textuels des 3 parcours experts ([[wireframes]]) décrivant
l'enchaînement des écrans et les points d'attention clavier. Cette session,
chaque user story a reçu un critère d'accessibilité RGAA explicite, ancré
sur un élément réel de l'interface plutôt que générique.

### 2.2 Interface unique, un seul fichier

`templates/index.html` est une SPA en JavaScript natif (pas de framework)
servie directement par Flask — cohérent avec le choix "API unique" du
projet plutôt que deux services séparés à déployer et versionner
ensemble. Le rôle de l'utilisateur connecté (`client`/`analyste`/`exploit`)
détermine dynamiquement les onglets visibles et les actions permises.

### 2.3 Audit d'accessibilité réel

Plutôt que d'écrire des critères RGAA "sur le papier", j'ai fait auditer
le HTML réellement servi : résultat, aucun `<label>` n'était lié à son
input sauf un, deux éléments cliquables (`<div onclick>`) étaient
totalement inutilisables au clavier, aucune zone `aria-live` n'existait
pour les messages dynamiques, et la navigation par onglets n'avait aucun
rôle ARIA. Correctifs appliqués et **vérifiés en conditions réelles** :
navigateur headless piloté au clavier (Tab + Entrée déplie effectivement
une carte de l'explorateur d'API), pas seulement relecture du diff.

### 2.4 Conteneurisation et CI/CD applicative

`Dockerfile` (image `python:3.11-slim`, utilisateur non-root, healthcheck
sur `/health`) + `docker-compose.yml` (volume persistant, restart policy).
`.github/workflows/ci.yml` : lint (`ruff`) → `pytest tests/` avec
couverture → build et publication de l'image (GHCR) → déploiement SSH
(conditionné à des secrets non disponibles dans cet environnement de
développement, donc non exécuté ici).

## 3. Choix techniques

- **JS natif plutôt qu'un framework front** : une seule page, pas de
  besoin de gestion d'état complexe ni de build step supplémentaire à
  maintenir en plus de l'API Flask.
- **Rôles ARIA additifs, aucun changement visuel** : tous les correctifs
  d'accessibilité (`role`, `aria-live`, `aria-selected`, `tabindex`) ont
  été ajoutés sans toucher au CSS existant — réduit le risque de
  régression visuelle sur une interface déjà en place.
- **Utilisateur Linux non-root dans le conteneur** : bonne pratique de
  sécurité de base, coût de mise en œuvre minimal.
- **CI applicative séparée de la CI modèle** (voir [[rapport_e3]]) :
  déclencheurs et finalités différents.

## 4. Résultats

- 10 critères d'acceptation RGAA ajoutés (un par user story), tous
  vérifiables sur un élément réel de l'interface.
- Correctifs d'accessibilité vérifiés par navigation clavier réelle
  (Playwright, pas une relecture statique) : aucune régression visuelle,
  captures d'écran comparées avant/après.
- Nouvel onglet "Audit" dans l'interface exploit, consommant un endpoint
  déjà fonctionnel côté API mais jusque-là sans vue dédiée.
- Dropdown client dans le filtre Prélèvements (remplace un champ texte
  libre exigeant l'identifiant exact).
- CI applicative vérifiée en direct sur un vrai runner GitHub Actions
  (pas seulement en local) : jobs "Tests & Lint" et "Build Docker image"
  verts, image poussée sur GHCR — au prix de 3 corrections successives,
  voir §5.

## 5. Difficultés rencontrées

Un correctif d'accessibilité en a révélé un autre, sans lien apparent au
départ. En ajoutant l'onglet "Audit" réservé au rôle `exploit`, j'ai
découvert que `showTab()` — la fonction qui recalcule le style des
boutons d'onglet à chaque clic — écrasait la classe `hidden` que je
venais de poser dessus. Un analyste aurait vu apparaître l'onglet Audit
dès son premier changement d'onglet, malgré la restriction de rôle censée
le cacher. Je ne l'ai vu qu'en testant le scénario "connexion analyste"
après coup, pas en relisant le code — une fonctionnalité toute neuve et
un correctif déjà en place peuvent interagir de façons qu'aucun des deux
ne laissait deviner isolément.

Sur la CI, je me suis longtemps contenté d'un aveu prudent : "je ne l'ai
jamais vue tourner pour de vrai." En creusant pourquoi, j'ai trouvé pire
que "pas encore vérifié" : `ci.yml` contenait une erreur de syntaxe YAML
toute bête (`DATABASE_URL: sqlite:///:memory:`, ligne 35 — le `:` final
juste avant le saut de ligne rend la valeur ambiguë tant qu'elle n'est
pas entre guillemets). Les 3 exécutions réelles sur GitHub Actions
avaient toutes échoué au moment même du parsing, avant qu'un seul job ne
démarre — le lint (`ruff check . --select E,F,W`) n'avait donc jamais
tourné non plus. Une fois la syntaxe corrigée, il a remonté 16 erreurs
réelles dans le code applicatif (imports inutilisés, comparaisons
`== True`, une variable ambiguë) — mineures, mais bien réelles, et qui
seraient passées inaperçues tant que rien ne les vérifiait vraiment.

Corriger le YAML n'a fait que révéler la couche suivante. Une fois le
job "Tests & Lint" vert pour de vrai, le job "Build Docker image" a
échoué à son tour — deux fois, sur deux causes différentes, chacune
invisible tant que la précédente bloquait tout : d'abord `Cache export
is not supported for the docker driver` (le driver Docker par défaut ne
supporte pas `cache-to`, il manquait un `docker/setup-buildx-action`
avant le build), puis, une fois le build réussi, un refus de push vers
GHCR (`denied: installation not allowed to Create organization
package`) — le workflow ne déclarait aucune permission `packages:
write` explicite. Trois bugs réels, trouvés un par un parce que chacun
masquait le suivant, corrigés un par un, chaque correctif repoussé et
revérifié en direct sur la page Actions avant de passer au suivant.
Aujourd'hui les jobs "Tests & Lint" et "Build Docker image" sont verts
pour de vrai — je les ai vus tourner, pas seulement lus. Seul le job de
déploiement échoue encore, et c'est attendu : il cible un serveur de
production qui n'existe pas dans cet environnement scolaire (secrets
`DEPLOY_HOST`/`DEPLOY_USER`/`DEPLOY_SSH_KEY` non configurés), une
limite déjà assumée plus haut, pas une régression cachée. "Je pense que
ça marche" n'était même pas le bon niveau de doute au départ : ça ne
marchait pas du tout, sur trois couches différentes, et je ne le savais
pas parce que je n'avais jamais regardé la page Actions du dépôt.

La bascule SQLite → PostgreSQL, elle, reste un chantier ouvert plutôt
qu'un problème résolu. `DATABASE_URL` accepte déjà une URL PostgreSQL
côté code, mais `docker-compose.yml` ne déclare aucun service PostgreSQL
— j'ai choisi de documenter clairement cette limite plutôt que d'ajouter
un service que je n'aurais pas eu le temps de tester correctement, juste
pour cocher une case.
