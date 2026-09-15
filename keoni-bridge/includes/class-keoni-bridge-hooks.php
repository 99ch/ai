<?php
/**
 * Hooks WordPress (publication d'offres, CRON, etc.).
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Keoni_Bridge_Hooks {
    private string $option_last_scan = 'keoni_bridge_last_job_scan';

    // Doit rester synchronisé avec app/scoring.py::SCORING_PROFILES côté
    // matching-api -- ce sont les seuls noms de profil que _weights()
    // reconnaît, un nom inconnu y retombe silencieusement sur le défaut.
    private const SCORING_PROFILES = [ 'equilibre', 'priorite_experience', 'priorite_mots_cles' ];

    public function __construct() {
        add_action( 'publish_post', [ $this, 'handle_publish' ], 10, 2 );
        add_action( 'keoni_bridge_trigger_matching', [ $this, 'trigger_webhook' ], 10, 2 );
        add_action( 'keoni_bridge_scan_jobs', [ $this, 'scan_js_jobs' ] );
        add_filter( 'cron_schedules', [ $this, 'register_cron_interval' ] );

        add_action( 'wp_ajax_keoni_bridge_run_matching', [ $this, 'ajax_run_matching' ] );
        add_action( 'wp_ajax_keoni_bridge_matching_status', [ $this, 'ajax_matching_status' ] );
        add_action( 'wp_ajax_keoni_bridge_reset_matching', [ $this, 'ajax_reset_matching' ] );
        add_action( 'wp_ajax_keoni_bridge_save_scoring_profile', [ $this, 'ajax_save_scoring_profile' ] );

        if ( ! wp_next_scheduled( 'keoni_bridge_scan_jobs' ) ) {
            wp_schedule_event( time() + 60, 'five_minutes', 'keoni_bridge_scan_jobs' );
        }
    }

    public function handle_publish( int $post_id, WP_Post $post ): void {
        if ( 'job_listing' !== $post->post_type && 'post' !== $post->post_type ) {
            return;
        }

        if ( 'publish' !== $post->post_status ) {
            return;
        }

        wp_schedule_single_event( time() + 5, 'keoni_bridge_trigger_matching', [ $post_id, get_current_user_id() ] );
    }

    public function trigger_webhook( int $post_id, int $user_id = 0 ): bool {
        $settings   = Keoni_Bridge::get_settings();
        $webhookUrl = $settings['webhook_url'] ?? '';
        $secret     = $settings['webhook_secret'] ?? '';

        if ( empty( $webhookUrl ) || empty( $secret ) ) {
            return false;
        }

        $body = [
            'job_post_id' => $post_id,
            'site'        => home_url(),
            'trigger_uid' => $user_id,
        ];

        $response = wp_remote_post( $webhookUrl, [
            'timeout' => 15,
            'headers' => [
                'Content-Type' => 'application/json',
                'X-API-Key'    => sanitize_text_field( $secret ),
            ],
            'body'    => wp_json_encode( $body ),
        ] );

        if ( is_wp_error( $response ) ) {
            error_log( sprintf( '[Keoni Bridge] Webhook error for job %d: %s', $post_id, $response->get_error_message() ) );
            return false;
        }

        $status_code = (int) wp_remote_retrieve_response_code( $response );

        if ( $status_code < 200 || $status_code >= 300 ) {
            error_log( sprintf( '[Keoni Bridge] Webhook HTTP %d for job %d.', $status_code, $post_id ) );
            return false;
        }

        return true;
    }

    public function ajax_run_matching(): void {
        check_ajax_referer( 'keoni_bridge_run_matching', 'nonce' );

        $job_id = isset( $_POST['job_id'] ) ? absint( wp_unslash( $_POST['job_id'] ) ) : 0;

        if ( $job_id <= 0 ) {
            wp_send_json_error( [ 'message' => __( 'Job invalide.', 'keoni-bridge' ) ], 400 );
        }

        if ( ! $this->user_can_manage_job_matching( $job_id ) ) {
            wp_send_json_error( [ 'message' => __( 'Accès refusé.', 'keoni-bridge' ) ], 403 );
        }

        if ( ! $this->trigger_webhook( $job_id, get_current_user_id() ) ) {
            wp_send_json_error( [ 'message' => __( 'Impossible de contacter le webhook IA.', 'keoni-bridge' ) ], 500 );
        }

        wp_send_json_success( [
            'message'    => __( 'Matching IA lancé pour cette offre.', 'keoni-bridge' ),
            'started_at' => current_time( 'timestamp', true ),
        ] );
    }

    public function ajax_matching_status(): void {
        check_ajax_referer( 'keoni_bridge_matching_status', 'nonce' );

        $job_id     = isset( $_POST['job_id'] ) ? absint( wp_unslash( $_POST['job_id'] ) ) : 0;
        $started_at = isset( $_POST['started_at'] ) ? absint( wp_unslash( $_POST['started_at'] ) ) : 0;

        if ( $job_id <= 0 ) {
            wp_send_json_error( [ 'message' => __( 'Job invalide.', 'keoni-bridge' ) ], 400 );
        }

        if ( ! $this->user_can_manage_job_matching( $job_id ) ) {
            wp_send_json_error( [ 'message' => __( 'Accès refusé.', 'keoni-bridge' ) ], 403 );
        }

        $status      = Keoni_Bridge_Repository::get_matching_status( $job_id );
        $last_updated = $status['last_updated'] ?? '';
        $total        = (int) ( $status['total'] ?? 0 );
        $last_ts      = $last_updated ? strtotime( $last_updated ) : 0;
        $complete     = $total > 0 && $last_ts > 0;

        if ( $complete && $started_at > 0 ) {
            $complete = $last_ts >= $started_at;
        }

        wp_send_json_success( [
            'complete'     => $complete,
            'total'        => $total,
            'last_updated' => $last_updated,
        ] );
    }

    public function ajax_reset_matching(): void {
        check_ajax_referer( 'keoni_bridge_reset_matching', 'nonce' );

        $job_id = isset( $_POST['job_id'] ) ? absint( wp_unslash( $_POST['job_id'] ) ) : 0;

        if ( $job_id <= 0 ) {
            wp_send_json_error( [ 'message' => __( 'Job invalide.', 'keoni-bridge' ) ], 400 );
        }

        if ( ! $this->user_can_manage_job_matching( $job_id ) ) {
            wp_send_json_error( [ 'message' => __( 'Accès refusé.', 'keoni-bridge' ) ], 403 );
        }

        $deleted = Keoni_Bridge_Repository::delete_matching_results( $job_id );

        wp_send_json_success( [
            'message' => __( 'Résultats IA réinitialisés.', 'keoni-bridge' ),
            'deleted' => $deleted,
        ] );
    }

    public function ajax_save_scoring_profile(): void {
        check_ajax_referer( 'keoni_bridge_save_scoring_profile', 'nonce' );

        $job_id  = isset( $_POST['job_id'] ) ? absint( wp_unslash( $_POST['job_id'] ) ) : 0;
        $profile = isset( $_POST['scoring_profile'] ) ? sanitize_key( wp_unslash( $_POST['scoring_profile'] ) ) : '';

        if ( $job_id <= 0 ) {
            wp_send_json_error( [ 'message' => __( 'Job invalide.', 'keoni-bridge' ) ], 400 );
        }

        if ( ! $this->user_can_manage_job_matching( $job_id ) ) {
            wp_send_json_error( [ 'message' => __( 'Accès refusé.', 'keoni-bridge' ) ], 403 );
        }

        if ( '' !== $profile && ! in_array( $profile, self::SCORING_PROFILES, true ) ) {
            wp_send_json_error( [ 'message' => __( 'Profil de scoring inconnu.', 'keoni-bridge' ) ], 422 );
        }

        $previous_profile = Keoni_Bridge_Repository::get_job_scoring_profile( $job_id );

        if ( ! Keoni_Bridge_Repository::set_job_scoring_profile( $job_id, $profile ) ) {
            wp_send_json_error( [ 'message' => __( 'Échec de l\'enregistrement.', 'keoni-bridge' ) ], 500 );
        }

        // Les résultats déjà stockés ont été calculés sous l'ANCIEN profil
        // (ou l'absence de profil) -- les laisser affichés silencieusement
        // les ferait passer pour à jour alors qu'ils ne le sont plus.
        // Effacés uniquement si le profil a réellement changé : resélectionner
        // par erreur la même valeur ne doit pas détruire des résultats valides.
        $cleared = 0;
        if ( $previous_profile !== $profile ) {
            $cleared = Keoni_Bridge_Repository::delete_matching_results( $job_id );
        }

        wp_send_json_success( [
            'message'         => $cleared > 0
                ? __( 'Profil de scoring enregistré. Relancez l\'IA pour recalculer les scores sous ce profil.', 'keoni-bridge' )
                : __( 'Profil de scoring enregistré.', 'keoni-bridge' ),
            'scoring_profile' => $profile,
            'cleared_results' => $cleared,
        ] );
    }

    public function scan_js_jobs(): void {
        global $wpdb;

        $last_scan = (int) get_option( $this->option_last_scan, 0 );
        $now       = current_time( 'timestamp', true );

        $table = $wpdb->prefix . 'js_job_jobs';

        $rows = $wpdb->get_results(
            $wpdb->prepare(
                "SELECT id FROM {$table} WHERE jobstatus = 1 AND startpublishing <= %s AND (stoppublishing = '0000-00-00 00:00:00' OR stoppublishing >= %s) AND UNIX_TIMESTAMP(modified) > %d ORDER BY modified ASC LIMIT 50",
                gmdate( 'Y-m-d H:i:s', $now ),
                gmdate( 'Y-m-d H:i:s', $now ),
                $last_scan
            )
        );

        if ( empty( $rows ) ) {
            update_option( $this->option_last_scan, $now );
            return;
        }

        foreach ( $rows as $row ) {
            $job_id = (int) $row->id;
            $this->trigger_webhook( $job_id );
        }

        update_option( $this->option_last_scan, $now );
    }

    public function register_cron_interval( array $schedules ): array {
        if ( isset( $schedules['five_minutes'] ) ) {
            return $schedules;
        }

        $schedules['five_minutes'] = [
            'interval' => 5 * MINUTE_IN_SECONDS,
            'display'  => __( 'Toutes les 5 minutes', 'keoni-bridge' ),
        ];

        return $schedules;
    }

    private function user_can_manage_job_matching( int $job_id ): bool {
        $user_id = get_current_user_id();

        if ( $user_id <= 0 ) {
            return false;
        }

        if ( current_user_can( 'manage_keoni_bridge_cv_db' ) || current_user_can( 'manage_options' ) ) {
            return true;
        }

        global $wpdb;

        $table    = $wpdb->prefix . 'js_job_jobs';
        $owner_id = (int) $wpdb->get_var( $wpdb->prepare( "SELECT uid FROM {$table} WHERE id = %d LIMIT 1", $job_id ) );

        return $owner_id > 0 && $owner_id === $user_id;
    }
}
