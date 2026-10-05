<?php
/**
 * Point d'entrée objet du plugin.
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

require_once __DIR__ . '/class-keoni-bridge-admin.php';
require_once __DIR__ . '/class-keoni-bridge-repository.php';
require_once __DIR__ . '/class-keoni-bridge-rest.php';
require_once __DIR__ . '/class-keoni-bridge-shortcode.php';
require_once __DIR__ . '/class-keoni-bridge-hooks.php';

class Keoni_Bridge {
    private static ?Keoni_Bridge $instance = null;

    private Keoni_Bridge_Admin $admin;
    private Keoni_Bridge_Rest $rest;
    private Keoni_Bridge_Shortcode $shortcode;
    private Keoni_Bridge_Hooks $hooks;

    public static function instance(): Keoni_Bridge {
        if ( null === self::$instance ) {
            self::$instance = new self();
        }

        return self::$instance;
    }

    private function __construct() {
        add_action( 'init', [ $this, 'boot' ] );
    }

    public function boot(): void {
        Keoni_Bridge_Install::maybe_upgrade();

        $this->admin     = new Keoni_Bridge_Admin();
        $this->rest      = new Keoni_Bridge_Rest();
        $this->shortcode = new Keoni_Bridge_Shortcode();
        $this->hooks     = new Keoni_Bridge_Hooks();
    }

    public static function get_api_key_hash(): string {
        return (string) get_option( 'keoni_bridge_api_key', '' );
    }

    public static function verify_api_key( string $provided ): bool {
        $hash = self::get_api_key_hash();

        if ( empty( $hash ) ) {
            return false;
        }

        return wp_check_password( $provided, $hash );
    }

    public static function get_settings(): array {
        $defaults = [
            'webhook_url'          => '',
            'matching_url'         => '',
            'matching_api_key'     => '',
            'webhook_secret'       => '',
            'cv_roles'             => [ 'administrator' ],
            'jsjobs_dual_role_ids' => [],
        ];

        return wp_parse_args( get_option( 'keoni_bridge_settings', [] ), $defaults );
    }

    // Comptes "candidat" (profil jobseeker côté js-jobs) autorisés en plus à
    // gérer des offres (ajout/édition), malgré le contrôle habituel
    // isemployer() de js-jobs -- cas des RH qui gèrent la plateforme en
    // interne avec un seul compte plutôt que de jongler entre deux profils.
    // Liste nominative (pas un rôle WordPress) : un rôle WP comme
    // "Subscriber" est souvent partagé avec de vrais candidats externes,
    // l'activer en ferait des employeurs de fait.
    public static function user_can_manage_jobs_as_employer( int $user_id ): bool {
        if ( $user_id <= 0 ) {
            return false;
        }

        $allowed_ids = array_map( 'intval', (array) self::get_settings()['jsjobs_dual_role_ids'] );

        return in_array( $user_id, $allowed_ids, true );
    }
}
