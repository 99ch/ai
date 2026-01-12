<?php
/**
 * Hooks WordPress (publication d'offres, CRON, etc.).
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Keoni_Bridge_Hooks {
    public function __construct() {
        add_action( 'publish_post', [ $this, 'handle_publish' ], 10, 2 );
        add_action( 'keoni_bridge_trigger_matching', [ $this, 'trigger_webhook' ], 10, 2 );
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

        if ( empty( $webhookUrl ) ) {
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
                'X-API-Key'    => sanitize_text_field( $_ENV['N8N_WEBHOOK_SECRET'] ?? '' ),
            ],
            'body'    => wp_json_encode( $body ),
        ] );
    }
}
