# Note RGPD — VigiEau

## Données considérées comme personnelles

| Donnée | Table | Justification |
|---|---|---|
| `id_client` | `clients` | Identifiant unique rattachable à une personne morale ou physique |
| `denomination` | `clients` | Nom de la structure (peut identifier une personne) |
| `adresse` | `clients` | Adresse postale de la collectivité |
| `api_key_hash` | `clients` | Identifiant d'authentification indirect |
| `ip_address` | `audit_logs` | Adresse IP (personnelle selon CNIL) — pseudonymisée |

Les mesures physico-chimiques (`mesures`) et les prédictions (`predictions`) ne sont **pas** des données personnelles en elles-mêmes ; elles le deviennent par association avec un `client_id`.

### Cas particulier : import Hub'Eau (source `opendata`)

`scripts/ingest_hubeau.py` importe les résultats publics du contrôle
sanitaire de l'eau distribuée (API Hub'Eau, data.eaufrance.fr). Ces données
sont déjà publiques, agrégées par commune, et ne comportent **aucune
donnée à caractère personnel** (pas de nom, pas d'adresse individuelle,
pas d'identifiant de personne physique). Elles sont rattachées à un client
système dédié (`OPENDATA-HUBEAU`, sans clé API) et non à un client réel —
aucun traitement RGPD supplémentaire n'est nécessaire pour cette source.

---

## Mesures de protection implémentées

### Hachage des clés API
- Les clés API ne sont **jamais stockées en clair**
- Stockage : SHA-256 du secret (`api_key_hash`) + 4 premiers caractères (`api_key_hint`)
- Comparaison : `hashlib.compare_digest()` (résistant aux attaques temporelles)
- En cas de compromission : régénération via `POST /admin/clients/<id>/apikey`, ancienne clé immédiatement invalide

### Pseudonymisation des adresses IP
- Le dernier octet est masqué : `192.168.1.42` → `192.168.1.xxx`
- Implémenté dans `auth.py` avant tout stockage dans `audit_logs`

### Séparation stricte des périmètres
- Un client authentifié par clé API ne peut accéder qu'à ses propres données
- Toutes les routes `/me/*` filtrent par `client_id` extrait de la clé
- Une clé invalide ou appartenant à un client désactivé retourne HTTP 401

### Minimisation des données
- Seuls l'ID technique, la dénomination et l'adresse sont stockés
- Pas d'email, pas de numéro de téléphone, pas de données biométriques

---

## Journaux d'accès (`audit_logs`)

### Finalité
Traçabilité des accès pour répondre à un audit de sécurité et détecter des usages anormaux.

### Données journalisées
- Timestamp, type d'acteur (client/expert), ID acteur, rôle
- IP pseudonymisée, action, ressource ciblée, code retour, détail

### Durée de conservation
- **12 mois glissants** — les entrées de plus de 12 mois peuvent être purgées
- Cette durée est conforme aux recommandations CNIL pour les journaux d'accès

### Immutabilité
- La table `audit_logs` est en **lecture seule par convention applicative**
- Aucune route DELETE ou UPDATE n'est exposée sur cette table
- Les logs sont écrits uniquement via la fonction interne `log_audit()`

---

## Droits des personnes

### Droit d'accès (Art. 15 RGPD)
- Route : `GET /me/rgpd`
- Retourne : profil complet, historique des accès, règles de conservation

### Droit à l'effacement (Art. 17 RGPD)
- Route : `DELETE /me/rgpd`
- Opération irréversible : `denomination`, `adresse` remplacés par `[ANONYMISÉ]`, `api_key_hash` effacé, `anonymised_at` renseigné
- Les prélèvements et prédictions sont conservés (données techniques dissociées de la personne)
- L'opération d'anonymisation est elle-même journalisée dans `audit_logs`

### Droit à la portabilité (Art. 20 RGPD)
- Les données personnelles sont accessibles via `GET /me/rgpd` au format JSON

---

## Durées de conservation des données

| Type de donnée | Durée | Justification |
|---|---|---|
| Prélèvements et mesures | Illimitée (données techniques) | Historique qualité eau |
| Prédictions | Illimitée | Traçabilité MLOps |
| Journaux d'accès (`audit_logs`) | 12 mois glissants | CNIL — logs de sécurité |
| Métriques (`request_metrics`) | 90 jours recommandés | Monitoring opérationnel |
| Données client après anonymisation | Conservées sans identifiant | Intégrité référentielle |

---

## Consentement

- Le champ `rgpd_consent` et `rgpd_consent_at` permettent de tracer l'accord explicite du client
- La création d'un compte client par un administrateur doit s'accompagner d'une communication des conditions d'utilisation au client final
