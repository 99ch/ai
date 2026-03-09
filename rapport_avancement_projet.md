# Rapport d’avancement complet — Projet Keoni / JS Jobs / Matching IA

Date: 16 février 2026

## 1) Contexte et objectif
Le projet vise à connecter JS Jobs (WordPress) avec un pipeline IA (n8n + 192.168.1.31) pour:
- lancer le matching IA depuis les jobs,
- stocker les résultats,
- afficher des candidats recommandés avec score,
- améliorer la pertinence des matchs (titre, mots-clés, contraintes métier),
- fiabiliser l’expérience frontend/admin.

---

## 2) Travaux réalisés (global)

### A. Intégration WordPress ↔ n8n ↔ 192.168.1.31
- Activation/fix des boutons IA et des permissions de déclenchement.
- Vérification/ajustement webhook et clés API entre WordPress, n8n et 192.168.1.31.
- Stabilisation des endpoints REST du plugin Keoni Bridge.
- Gestion des erreurs de payload côté stockage des résultats.

### B. Amélioration UI/UX des résultats IA
- Refonte de l’affichage des candidats IA en cartes type “CV” (style proche JS Jobs natif).
- Ajout du score IA visible par carte.
- Ajout du bouton `View Resume`.
- Ajout de pagination “Load more”.
- Ajout d’un état/loader de progression pendant l’exécution du matching.
- Ajout de polling de statut IA.
- Ajout d’un bouton “reset résultats IA” + endpoint backend associé.
- Harmonisation visuelle (boutons dark blue, structure des cartes, méta-données).

### C. Fiabilisation des données et repository
- Déduplication des résultats de matching par `cv_id`.
- Ajout de méthodes repository pour récupérer les CV par emails et par IDs.
- Ajout de méthode de statut de matching.
- Ajout de suppression des résultats de matching.

### D. Matching API (moteur de scoring)
- Renforcement de la normalisation des titres (accents, ponctuation, tokens).
- Ajout de logique de filtrage par proximité de titre.
- Pondération keywords/titre/localisation + contraintes métier (contrat/catégorie/expérience/salaire/qualification).
- Ajout de logs de diagnostic (`[matching]`) pour comprendre la distribution des titres et les matchs.
- Correction d’erreurs bloquantes:
  - `UnboundLocalError` (`title_tokens` shadowing),
  - `SyntaxError` (caractère `!` résiduel),
  - robustesse de récupération du titre CV via plusieurs champs (`application_title`, `title`, `job_title`, metadata).
- Ajout d’un classement final déterministe et cohérent avec l’affichage.
- Ajout d’un `score_breakdown` dans `extra` pour expliquer le score par composantes.

### E. n8n workflow
- Correction du workflow JSON (erreurs structurelles, doublons `jsCode`).
- Sécurisation du nœud “Store Results” pour toujours envoyer `results` sous forme de tableau.
- Ajustement du pipeline pour mieux conserver les champs de titre CV.
- Réduction des risques de timeout:
  - réduction des opérations coûteuses,
  - limitation du volume CV traité,
  - augmentation de timeout runner.

### F. JS Jobs frontend/listing
- Retrait de certains filtres restrictifs de listing jobs (status/dates et uid selon vues ciblées) pour debug/exposition complète des jobs.
- Analyse des causes de non-affichage jobs: contraintes SQL natives de JS Jobs (`status`, dates de publication, uid).

### G. Correctifs warnings PHP
- Correction des warnings `Undefined array key` sur `comp_name`, `comp_show_url`, `comp_city` dans `viewjob.php` via vérifications `!empty(...)`.

---

## 3) Fichiers principaux impactés

### Plugin Keoni Bridge
- `keoni-bridge/includes/class-keoni-bridge-repository.php`
- `keoni-bridge/includes/class-keoni-bridge-shortcode.php`
- `keoni-bridge/includes/class-keoni-bridge-hooks.php`
- `keoni-bridge/includes/class-keoni-bridge-rest.php`
- `keoni-bridge/assets/js/keoni-matching.js`
- `keoni-bridge/assets/css/keoni-matching.css`

### JS Jobs
- `js-jobs/modules/job/tmpl/myjobs.php`
- `js-jobs/modules/job/tmpl/viewjob.php`
- `js-jobs/modules/job/model.php`

### Stack local / IA
- `local-stack/services/192.168.1.31/app/main.py`
- `local-stack/n8n-matching-workflow.json`
- `local-stack/docker-compose.yml`
- `js-job pipeline.json` (export workflow)

---

## 4) Détails des améliorations scoring (version actuelle)
Le score IA est maintenant basé sur:
- similarité sémantique du contenu CV/job,
- mots-clés en commun,
- proximité de titre,
- compatibilité type de contrat,
- compatibilité catégorie,
- adéquation expérience (logique progressive),
- compatibilité salariale,
- compatibilité localisation,
- bonus/malus structurels et qualification.

En plus:
- tri final déterministe,
- rang final recalculé après tri,
- détail explicatif de score (`score_breakdown`) disponible dans `extra`.

---

## 5) Problèmes rencontrés et résolutions

1. **Aucun résultat IA / résultats incohérents**
- Causes: mapping titres incomplet, filtres trop stricts, données CV incomplètes, code non rebuildé.
- Résolutions: fallback multi-champs titre, logs diagnostics, rebuild/recreate conteneur, ajustements scoring.

2. **Erreurs 500/400 API**
- Causes: variable shadowing, syntaxe invalide, `results` vide rejeté.
- Résolutions: patch Python + patch endpoint REST + payload n8n .

3. **Timeout n8n (300s)**
- Causes: traitements lourds et flux trop volumineux.
- Résolutions: optimisation workflow + `N8N_RUNNERS_TASK_TIMEOUT` augmenté.

4. **Warnings PHP en page job**
- Causes: accès direct à des clés de config absentes.
- Résolutions: garde-fous `!empty(...)`.

5. **Jobs absents frontend**
- Causes: filtres natifs JS Jobs (status/dates/uid).
- Résolutions: retrait temporaire de filtres côté code + analyse SQL.

---

## 6) État d’avancement

### Terminé
- Pipeline IA fonctionnel de bout en bout (déclenchement → scoring → stockage → rendu).
- UI des résultats IA modernisée et exploitable.
- Moteur de scoring nettement renforcé.
- Diagnostics et logs de compréhension en place.
- Correctifs majeurs de stabilité appliqués.

### En cours / à surveiller
- Synchronisation stricte des patches entre local et serveur (`/srv/keoni-local` et `/var/www/html`).
- Vérification continue des sources de vérité (table/instance DB réellement interrogée).
- Validation UX finale des vues jobs après suppression de filtres (impact métier à confirmer).

---

## 7) Recommandations suite projet

1. **Déploiement contrôlé**
- Appliquer les mêmes patches sur l’instance serveur active.
- Rebuild systématique des conteneurs après modif (`192.168.1.31`, `n8n` si env changée).

2. **Qualité des données**
- Unifier les champs titre/expérience entre JS Jobs, CV DB et matching payload.
- Éviter doublons et champs vides côté CV.

3. **Observabilité**
- Conserver les logs `[matching]` en niveau info.
- Ajouter un log de version applicative au startup.

4. **Gouvernance du ranking**
- Documenter officiellement les poids.
- Ajuster les poids sur un jeu de validation métier.

5. **Frontend jobs**
- Revoir la décision de retirer tous les filtres; idéalement réintroduire des filtres métier maîtrisés avec toggle admin.

---

## 8) Conclusion
Le projet a franchi un cap important: la chaîne IA est opérationnelle, les résultats sont lisibles, explicables, et globalement plus pertinents. Les principaux blocages techniques ont été corrigés. Les prochaines actions portent surtout sur la consolidation serveur, la qualité de données, et l’alignement final des règles métier de publication/ranking.
