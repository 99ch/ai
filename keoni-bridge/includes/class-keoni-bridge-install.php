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
     * Le déploiement réel se fait par remplacement du zip depuis wp-admin
     * (pas d'activation/désactivation explicite), qui ne déclenche jamais
     * register_activation_hook -- sans ce garde-fou, une nouvelle table
     * ajoutée ici ne serait donc jamais créée en prod. dbDelta() est
     * idempotent (ALTER plutôt que CREATE si la table existe déjà), donc
     * rejouer maybe_create_tables() à chaque changement de version ne
     * touche que ce qui a réellement changé.
     */
    public static function maybe_upgrade(): void {
        if ( get_option( self::OPTION_VERSION ) === KEONI_BRIDGE_VERSION ) {
            return;
        }

        self::maybe_create_tables();
        update_option( self::OPTION_VERSION, KEONI_BRIDGE_VERSION );
    }

    private static function maybe_create_tables(): void {
        global $wpdb;

        require_once ABSPATH . 'wp-admin/includes/upgrade.php';

        $charset_collate = $wpdb->get_charset_collate();
        $cv_table         = $wpdb->prefix . 'cv_database';
        $match_table      = $wpdb->prefix . 'cv_matching_results';
        $match_fast_table = $wpdb->prefix . 'cv_matching_results_fast';

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
            KEY job_id (job_id),
            KEY cv_id (cv_id)
        ) {$charset_collate};";

        // Résultats de la branche rapide ("Lancer IA" -> /score-fast) --
        // table séparée de {$match_table} (branche autonome, remplie en
        // fond par matching-api) pour ne jamais mélanger les deux jeux de
        // résultats. UNIQUE KEY (job_id, cv_id), contrairement à
        // {$match_table} : nécessaire pour que $wpdb->replace() fasse un
        // vrai upsert (un candidat rescoré remplace sa ligne au lieu d'en
        // accumuler une nouvelle à chaque clic sur "Lancer IA").
        $sql[] = "CREATE TABLE {$match_fast_table} (
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
            KEY job_id (job_id),
            KEY cv_id (cv_id)
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
