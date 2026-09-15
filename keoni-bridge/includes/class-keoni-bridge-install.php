<?php
/**
 * Gestion des activations/mises à jour du plugin.
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Keoni_Bridge_Install {
    private const OPTION_VERSION  = 'keoni_bridge_version';
    private const OPTION_API_KEY  = 'keoni_bridge_api_key';
    private const OPTION_SETTINGS = 'keoni_bridge_settings';

    public static function activate(): void {
        self::maybe_create_tables();
        self::maybe_seed_api_key();
        update_option( self::OPTION_VERSION, KEONI_BRIDGE_VERSION );
    }

    public static function deactivate(): void {
        // Rien pour le moment (les tables restent en place).
    }

    /**
     * Applique les migrations de schéma sur un site déjà actif, à chaque
     * chargement admin tant que la version stockée n'a pas rattrapé
     * KEONI_BRIDGE_VERSION -- contrairement à activate(), qui ne tourne
     * qu'une fois à l'activation du plugin et ne se redéclenche jamais sur
     * un site déjà en production après un simple déploiement de code.
     *
     * 0.1.0 -> 0.2.0 : wp_cv_matching_results n'avait aucune clé UNIQUE sur
     * (job_id, cv_id), donc store_matching() (qui utilise $wpdb->replace())
     * se comportait comme un simple INSERT à chaque "Lancer IA" -- chaque
     * relance accumulait de nouvelles lignes au lieu de remplacer les
     * anciennes pour le même candidat. get_matching_results() compensait en
     * lecture avec un MAX() indépendant par colonne (score, strengths,
     * extra...), ce qui pouvait afficher un score et un détail (extra)
     * venant de DEUX lignes différentes après une relance aux résultats
     * différents. deduplicate_matching_results() nettoie l'historique
     * AVANT que maybe_create_tables() n'essaie d'ajouter la contrainte
     * UNIQUE (dbDelta échouerait sur des données déjà en doublon).
     *
     * 0.2.0 -> 0.3.0 : nouvelle table keoni_job_scoring_settings (profil de
     * scoring par offre) -- simple ajout de table, dbDelta la crée sans
     * migration de données particulière.
     */
    public static function maybe_upgrade(): void {
        $installed_version = get_option( self::OPTION_VERSION, '' );

        if ( $installed_version === KEONI_BRIDGE_VERSION ) {
            return;
        }

        if ( version_compare( (string) $installed_version, '0.2.0', '<' ) ) {
            self::deduplicate_matching_results();
        }

        self::maybe_create_tables();
        update_option( self::OPTION_VERSION, KEONI_BRIDGE_VERSION );
    }

    /**
     * Ne garde que la ligne la plus récente (updated_at, puis id en cas
     * d'égalité) par (job_id, cv_id) dans wp_cv_matching_results, pour que
     * l'ajout de la contrainte UNIQUE par maybe_create_tables() ne
     * rencontre plus aucun doublon.
     */
    private static function deduplicate_matching_results(): void {
        global $wpdb;

        $table = $wpdb->prefix . 'cv_matching_results';

        if ( $wpdb->get_var( $wpdb->prepare( 'SHOW TABLES LIKE %s', $table ) ) !== $table ) {
            return;
        }

        $wpdb->query(
            "DELETE t1 FROM {$table} t1
             INNER JOIN {$table} t2
               ON t1.job_id = t2.job_id
              AND t1.cv_id = t2.cv_id
              AND ( t1.updated_at < t2.updated_at
                    OR ( t1.updated_at = t2.updated_at AND t1.id < t2.id ) )"
        );
    }

    private static function maybe_create_tables(): void {
        global $wpdb;

        require_once ABSPATH . 'wp-admin/includes/upgrade.php';

        $charset_collate  = $wpdb->get_charset_collate();
        $cv_table         = $wpdb->prefix . 'cv_database';
        $match_table      = $wpdb->prefix . 'cv_matching_results';
        $scoring_settings = $wpdb->prefix . 'keoni_job_scoring_settings';

        $sql = [];

        $sql[] = "CREATE TABLE {$cv_table} (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            candidate_email VARCHAR(190) NOT NULL,
            application_title VARCHAR(190) DEFAULT '' NOT NULL,
            file_name VARCHAR(255) DEFAULT '' NOT NULL,
            file_path VARCHAR(255) DEFAULT '' NOT NULL,
            text_content LONGTEXT,
            metadata LONGTEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY candidate_email (candidate_email),
            PRIMARY KEY  (id)
        ) {$charset_collate};";

        $sql[] = "CREATE TABLE {$match_table} (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            job_id BIGINT UNSIGNED NOT NULL,
            cv_id BIGINT UNSIGNED NOT NULL,
            score DECIMAL(5,2) NOT NULL DEFAULT 0,
            strengths TEXT,
            weaknesses TEXT,
            keywords LONGTEXT,
            extra LONGTEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY job_cv (job_id, cv_id),
            KEY cv_id (cv_id)
        ) {$charset_collate};";

        // Profil de scoring choisi par le recruteur pour une offre (voir
        // app/scoring.py::SCORING_PROFILES côté matching-api -- liste de
        // valeurs valides dupliquée dans Keoni_Bridge_Hooks::SCORING_PROFILES,
        // à garder synchronisée). Table dédiée plutôt qu'une colonne sur la
        // table js_job_jobs de js-jobs (plugin tiers, schéma hors de notre
        // contrôle) : même logique que cv_database/cv_matching_results,
        // déjà des tables propres à keoni-bridge.
        $sql[] = "CREATE TABLE {$scoring_settings} (
            job_id BIGINT UNSIGNED NOT NULL,
            scoring_profile VARCHAR(32) NOT NULL DEFAULT '',
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (job_id)
        ) {$charset_collate};";

        foreach ( $sql as $statement ) {
            dbDelta( $statement );
        }
    }

    private static function maybe_seed_api_key(): void {
        $api_key = get_option( self::OPTION_API_KEY );

        if ( ! empty( $api_key ) ) {
            return;
        }

        $bytes  = wp_generate_password( 64, true, true );
        $hashed = wp_hash_password( $bytes );

        update_option( self::OPTION_API_KEY, $hashed );
        update_option( self::OPTION_SETTINGS, [
            'webhook_url'  => '',
            'matching_url' => '',
            'webhook_secret' => '',
        ] );
    }
}
