<?php
/**
 * Hooks WordPress (publication d'offres, CRON, etc.).
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Keoni_Bridge_Hooks {
    private string $option_last_scan = 'keoni_bridge_last_job_scan';

    public function __construct() {
        add_action( 'publish_post', [ $this, 'handle_publish' ], 10, 2 );
        add_action( 'keoni_bridge_trigger_matching', [ $this, 'trigger_webhook' ], 10, 2 );
        add_action( 'keoni_bridge_scan_jobs', [ $this, 'scan_js_jobs' ] );
        add_filter( 'cron_schedules', [ $this, 'register_cron_interval' ] );

        add_action( 'wp_ajax_keoni_bridge_run_matching', [ $this, 'ajax_run_matching' ] );

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

    public function trigger_webhook( int $post_id ): void {
        $settings   = Keoni_Bridge::get_settings();
        $webhookUrl = $settings['webhook_url'] ?? '';
        $secret     = $settings['webhook_secret'] ?? '';

        if ( empty( $webhookUrl ) || empty( $secret ) ) {
            return;
        }

        $body = [
            'job_post_id' => $post_id,
            'site'        => home_url(),
        ];

        wp_remote_post( $webhookUrl, [
            'timeout' => 15,
            'headers' => [
                'Content-Type' => 'application/json',
                'X-API-Key'    => sanitize_text_field( $secret ),
            ],
            'body'    => wp_json_encode( $body ),
        ] );
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

        $this->trigger_webhook( $job_id );

        wp_send_json_success( [ 'message' => __( 'Matching IA lancé pour cette offre.', 'keoni-bridge' ) ] );
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
        if ( current_user_can( 'manage_keoni_bridge_cv_db' ) ) {
            return true;
        }

        $user_id = get_current_user_id();

        if ( $user_id <= 0 ) {
            return false;
        }

        $jobs_role = get_user_meta( $user_id, 'jobs_role', true );

        if ( 'employer' !== $jobs_role ) {
            return false;
        }

        global $wpdb;

        $table    = $wpdb->prefix . 'js_job_jobs';
        $owner_id = (int) $wpdb->get_var( $wpdb->prepare( "SELECT uid FROM {$table} WHERE id = %d LIMIT 1", $job_id ) );

        return $owner_id > 0 && $owner_id === $user_id;
    }
}
