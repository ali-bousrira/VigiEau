# Wireframes — Parcours experts (VigiEau)

Descriptions textuelles structurées des parcours experts dans l'interface
web (`templates/index.html`), une seule application pour les deux rôles
Bearer (`analyste`, `exploit` — `exploit` est un sur-rôle qui voit aussi
tout ce que voit `analyste`). Complète les user stories (`docs/user_stories.md`)
avec la séquence d'écrans et les points d'attention clavier/RGAA.

---

## 1. Parcours Analyste qualité

```
┌──────────────────────────────────────────────────────────────────┐
│ Connexion (rôle="expert")                                        │
│  [Token Bearer___________]  (label lié, Entrée = connexion)      │
│  [Se connecter]                                                   │
└───────────────────────────────┬────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│ En-tête : 💧 VigiEau (h1) · badge rôle · statut API               │
│ Onglets (role="tablist") :  [📊 Dashboard*][🧪 Prélèvements]      │
│                              [🏛 Clients][📈 Par client][🔌 API]   │
│  * onglet actif → aria-selected="true"                            │
└───────────────────────────────┬────────────────────────────────────┘
                                 ▼
┌─────────────── Onglet Dashboard (role="tabpanel") ─────────────────┐
│ KPI : Prélèvements | Potables | Non potables | Taux potabilité     │
│ (chaque carte : libellé texte + valeur — jamais couleur seule)     │
│ Moyennes physico-chimiques (tableau)                                │
│ 15 derniers prélèvements (table, badge résultat = couleur + texte) │
└──────────────────────────────────────────────────────────────────┘
                                 │ Tab → onglet suivant
                                 ▼
┌─────────────── Onglet Prélèvements ─────────────────────────────────┐
│ Barre de filtres (labels liés) :                                    │
│   [Client___] [Source ▾] [Résultat ▾] [Date début] [Date fin]       │
│   [Filtrer] [Réinitialiser]                                          │
│ Zone résultats (aria-live="polite" — chargement/erreur annoncés)    │
│ Liste paginée, clic ou Entrée sur une ligne → détail (modal)         │
└──────────────────────────────────────────────────────────────────┘
                                 ▼
┌─────────────── Onglet Par client ───────────────────────────────────┐
│ [Recherche client____]                                               │
│ Liste clients (role="button" tabindex="0" par ligne — Entrée/Espace  │
│   sélectionne, corrige le piège clavier détecté à l'audit)           │
│ → Panneau détail : KPI client, barre potable/non potable, historique │
└──────────────────────────────────────────────────────────────────┘
```

**Points RGAA clés** : navigation par onglets entièrement au clavier
(Tab pour atteindre la barre, flèches non requises car boutons standards) ;
chaque changement d'onglet charge son contenu dans une zone identifiée par
`role="tabpanel"` ; aucune information (résultat, statut client) n'est
portée par la seule couleur.

---

## 2. Parcours Responsable d'exploitation

```
┌──────────────────────────────────────────────────────────────────┐
│ Connexion (même écran, rôle="exploit")                            │
└───────────────────────────────┬────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│ Mêmes onglets que l'analyste (sur-rôle) + accès direct aux routes  │
│ /exploitation/* via l'onglet API Explorer (pas de vue dédiée —      │
│ dette technique documentée, voir RAPPORT_CONFORMITE.md)             │
└───────────────────────────────┬────────────────────────────────────┘
```

**Écart entre ce wireframe et l'implémentation réelle** (noté a posteriori,
sans retoucher le schéma ci-dessus qui reflète l'intention avant
codage) : `/exploitation/audit` a finalement reçu son propre onglet
"Audit" dédié (rôle `exploit`), pas seulement l'accordéon API Explorer
décrit ici — voir capture dans `docs/doc_technique_e5.md` C20.
`/exploitation/metrics`, lui, reste conforme à ce wireframe (pas de vue
dédiée, accès via l'onglet API générique).

```
                                 ▼
┌─────────────── Onglet API (role="tabpanel") ─────────────────────────┐
│ Liste des endpoints (accordéon) :                                     │
│   [▾ GET /exploitation/metrics            ]  ← role="button"          │
│                                                tabindex="0", Entrée/   │
│                                                Espace pour déplier     │
│     Paramètres de requête (labels liés à chaque champ)                 │
│     [▶ Envoyer]  → réponse dans une zone aria-live="polite"            │
│   [▾ GET /exploitation/audit               ]                           │
└──────────────────────────────────────────────────────────────────┘
```

**Points RGAA clés** : les cartes d'endpoint étaient des `<div onclick>`
sans piste clavier avant correctif ; elles portent maintenant
`role="button"`, `tabindex="0"` et un gestionnaire clavier Entrée/Espace
identique au clic souris.

---

## 3. Parcours Administration des comptes clients

*(accessible aux deux rôles experts — `POST /admin/clients` n'est pas un
rôle séparé, c'est une action ouverte à tout expert authentifié)*

```
┌─────────────── Onglet Clients (role="tabpanel") ─────────────────────┐
│ Liste des comptes existants (aria-live="polite")                      │
│   Commune de Nice        [actif ✓ texte] [Nouvelle clé]               │
│   Syndicat des Eaux…     [inactif  texte] [Nouvelle clé]              │
├────────────────────────────────────────────────────────────────────┤
│ Formulaire "Nouveau client" (labels liés) :                           │
│   [Identifiant métier___] [Dénomination___] [Adresse___]              │
│   [Créer le client]                                                    │
│   → résultat annoncé via aria-live (role="status")                    │
└────────────────────────────────────────────────────────────────────┘
                                 │ clic "Nouvelle clé"
                                 ▼
┌─────────────── Modal de confirmation ─────────────────────────────────┐
│ Titre + sous-titre (h3)                                                │
│ Corps : nouvelle clé API affichée une seule fois                       │
│ [Fermer]                                                                │
└────────────────────────────────────────────────────────────────────┘
```

**Points RGAA clés** : formulaire entièrement labellisé (`for`/`id`) ;
dette technique documentée et non traitée dans cette étape — la modale n'a
pas de piège de focus ni de fermeture au clavier via `Échap` (voir
`docs/user_stories.md`, US-05), et `genKey()` retombe sur un `window.alert()`
natif sur le chemin d'erreur (nativement annoncé par les lecteurs d'écran,
mais visuellement incohérent avec le reste de l'interface) — à corriger
dans une prochaine itération.

---

## Dette technique accessibilité non traitée dans cette étape

Documentée ici pour traçabilité (voir aussi le rapport d'audit qui a
précédé ces wireframes) :

- Contraste des textes `text-slate-600`/`text-slate-500` sur fond sombre —
  à vérifier avec un outil de contraste dédié, pas mesurable depuis le HTML seul.
- Indicateur de focus clavier limité à un changement de couleur de bordure
  (`focus:border-blue-500`), sans anneau de focus (`focus:ring`) — plus
  difficile à repérer que l'indicateur par défaut du navigateur qu'il remplace.
- Hiérarchie de titres `<h2>`/`<h3>` incohérente entre onglets (certains
  titres de section visuellement identiques utilisent tantôt un `<h2>`,
  tantôt un `<span>` stylé).
- Modale (`#modal`) sans piège de focus, sans focus initial à l'ouverture,
  sans fermeture au clavier via `Échap`.
