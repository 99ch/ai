<?php
/**
 * Hooks WordPress (publication d'offres, CRON, etc.).
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Keoni_Bridge_Hooks {
    private string $option_last_scan = 'keoni_bridge_last_job_scan';

    // Doit rester synchronisé avec js-jobs/modules/job/tmpl/viewjob.php et
    // app/scoring.py::SCORING_PROFILES côté matching-api.
    public const SCORING_PROFILES = [
        ''                    => 'Équilibré (défaut)',
        'priorite_experience' => 'Priorité expérience',
        'priorite_mots_cles'  => 'Priorité mots-clés',
    ];

    public function __construct() {
        add_action( 'publish_post', [ $this, 'handle_publish' ], 10, 2 );
        add_action( 'keoni_bridge_trigger_matching', [ $this, 'trigger_webhook' ], 10, 2 );
        add_action( 'keoni_bridge_scan_jobs', [ $this, 'scan_js_jobs' ] );
        add_filter( 'cron_schedules', [ $this, 'register_cron_interval' ] );

        add_action( 'wp_ajax_keoni_bridge_run_matching', [ $this, 'ajax_run_matching' ] );
        add_action( 'wp_ajax_keoni_bridge_matching_status', [ $this, 'ajax_matching_status' ] );
        add_action( 'wp_ajax_keoni_bridge_reset_matching', [ $this, 'ajax_reset_matching' ] );
        add_action( 'wp_ajax_keoni_bridge_extract_cv', [ $this, 'ajax_extract_cv' ] );
        add_action( 'wp_ajax_keoni_bridge_extract_job', [ $this, 'ajax_extract_job' ] );
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

        // Branche rapide : appel synchrone direct à matching-api
        // (/score-fast, dérivé de l'URL /score réglée dans les paramètres),
        // plus de passage par n8n. La réponse HTTP contient déjà les
        // résultats définitifs -- pas de polling nécessaire côté frontend,
        // contrairement à l'ancien flux webhook. Purge d'abord, même
        // raison que l'ancien flux : un candidat absent du nouveau run ne
        // doit pas rester affiché indéfiniment avec un score obsolète.
        // Table cv_matching_results_fast uniquement -- la branche autonome
        // (cv_matching_results, "Voir résultat2") n'est jamais touchée ici.
        Keoni_Bridge_Repository::delete_matching_results_fast( $job_id );

        $response = $this->call_score_fast( $job_id );

        if ( null === $response ) {
            wp_send_json_error( [ 'message' => __( 'Impossible de contacter le service de matching.', 'keoni-bridge' ) ], 500 );
        }

        $results     = is_array( $response['results'] ?? null ) ? $response['results'] : [];
        $duration_ms = (int) ( $response['duration_ms'] ?? 0 );
        Keoni_Bridge_Repository::store_matching_results_fast( $job_id, $results );
        Keoni_Bridge_Repository::set_workflow_kpi_fast( $job_id, [ 'duration_ms' => $duration_ms ] );

        wp_send_json_success( [
            'message'     => __( 'Matching IA terminé.', 'keoni-bridge' ),
            'complete'    => true,
            'count'       => count( $results ),
            'duration_ms' => $duration_ms,
        ] );
    }

    /**
     * Appelle matching-api directement (POST /score-fast), sans passer par
     * n8n -- voir ajax_run_matching(). L'URL /score-fast est dérivée du
     * réglage "URL matching API" existant (matching_url, jusqu'ici réservé
     * sans jamais être câblé) en remplaçant son suffixe /score.
     */
    private string $last_score_fast_error = '';

    private function call_score_fast( int $job_id ): ?array {
        $settings = Keoni_Bridge::get_settings();
        $base     = $settings['matching_url'] ?? '';
        $api_key  = $settings['matching_api_key'] ?? '';

        if ( empty( $base ) || empty( $api_key ) ) {
            $this->last_score_fast_error = 'settings manquants (matching_url ou matching_api_key)';
            error_log( '[Keoni Bridge] /score-fast: matching_url ou matching_api_key manquant dans les réglages.' );
            return null;
        }

        $url = preg_match( '#/score$#', $base )
            ? preg_replace( '#/score$#', '/score-fast', $base )
            : rtrim( $base, '/' ) . '/score-fast';

        $response = wp_remote_post( $url, [
            'timeout' => 120,
            'headers' => [
                'Content-Type' => 'application/json',
                'X-API-Key'    => sanitize_text_field( $api_key ),
            ],
            'body'    => wp_json_encode( [ 'job_id' => $job_id ] ),
        ] );

        if ( is_wp_error( $response ) ) {
            $this->last_score_fast_error = 'url=' . $url . ' wp_error=' . $response->get_error_message();
            error_log( sprintf( '[Keoni Bridge] /score-fast error for job %d: %s', $job_id, $response->get_error_message() ) );
            return null;
        }

        $status_code = (int) wp_remote_retrieve_response_code( $response );
        $body        = json_decode( (string) wp_remote_retrieve_body( $response ), true );

        if ( $status_code < 200 || $status_code >= 300 || ! is_array( $body ) ) {
            $this->last_score_fast_error = 'url=' . $url . ' http=' . $status_code . ' body=' . substr( (string) wp_remote_retrieve_body( $response ), 0, 300 );
            error_log( sprintf( '[Keoni Bridge] /score-fast HTTP %d for job %d.', $status_code, $job_id ) );
            return null;
        }

        return $body;
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

        // Le workflow n8n écrit les résultats lot par lot au fil de l'eau
        // (Store Results A/B/Single) -- le premier lot stocké ne veut pas
        // dire que le matching est fini, seulement que le premier lot l'est.
        // Le vrai signal de fin est l'appel à /matching-kpi (nœud "Store
        // Final KPI"), déclenché une seule fois, après la fusion de tous
        // les lots parallèles. Sans ça, le frontend affichait "terminé"
        // dès l'arrivée du premier lot alors que n8n continuait de tourner
        // en arrière-plan (constaté en prod : toujours "(10)", le compte
        // du tout premier lot, jamais le total réel).
        $kpi     = Keoni_Bridge_Repository::get_workflow_kpi( $job_id );
        $kpi_ts  = ! empty( $kpi['updated_at'] ) ? strtotime( $kpi['updated_at'] ) : 0;
        $complete = $kpi_ts > 0;

        if ( $complete && $started_at > 0 ) {
            $complete = $kpi_ts >= $started_at;
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
        $source = isset( $_POST['source'] ) ? sanitize_text_field( wp_unslash( $_POST['source'] ) ) : '';

        if ( $job_id <= 0 ) {
            wp_send_json_error( [ 'message' => __( 'Job invalide.', 'keoni-bridge' ) ], 400 );
        }

        if ( ! $this->user_can_manage_job_matching( $job_id ) ) {
            wp_send_json_error( [ 'message' => __( 'Accès refusé.', 'keoni-bridge' ) ], 403 );
        }

        $deleted = 'fast' === $source
            ? Keoni_Bridge_Repository::delete_matching_results_fast( $job_id )
            : Keoni_Bridge_Repository::delete_matching_results( $job_id );

        wp_send_json_success( [
            'message' => __( 'Résultats IA réinitialisés.', 'keoni-bridge' ),
            'deleted' => $deleted,
        ] );
    }

    public function ajax_extract_cv(): void {
        check_ajax_referer( 'keoni_bridge_extract_cv', 'nonce' );

        $cv_id  = isset( $_POST['cv_id'] ) ? absint( wp_unslash( $_POST['cv_id'] ) ) : 0;
        $job_id = isset( $_POST['job_id'] ) ? absint( wp_unslash( $_POST['job_id'] ) ) : 0;

        if ( $cv_id <= 0 || $job_id <= 0 ) {
            wp_send_json_error( [ 'message' => __( 'Requête invalide.', 'keoni-bridge' ) ], 400 );
        }

        if ( ! $this->user_can_manage_job_matching( $job_id ) ) {
            wp_send_json_error( [ 'message' => __( 'Accès refusé.', 'keoni-bridge' ) ], 403 );
        }

        // "cv_id" est en réalité l'id de la fiche candidat côté js-jobs
        // (wp_js_job_resume.id) -- wp_cv_database n'est jamais peuplée par le
        // pipeline n8n actif, le vrai fichier CV vient de resume_file_url
        // (construit depuis wp_js_job_resumefiles). matching-api télécharge
        // et extrait ce fichier lui-même (voir assemble_cv_text/fetch_remote_file).
        $resume = Keoni_Bridge_Repository::get_resumes_by_ids( [ $cv_id ] )[ $cv_id ] ?? null;

        if ( empty( $resume ) || empty( $resume['resume_file_url'] ) ) {
            wp_send_json_error( [ 'message' => __( 'CV introuvable.', 'keoni-bridge' ) ], 404 );
        }

        $payload = [
            'id'                => $cv_id,
            'candidate_email'   => $resume['email'] ?? '',
            'application_title' => $resume['application_title'] ?? '',
            'file_path'         => $resume['resume_file_url'],
        ];

        $result = $this->call_extract_webhook( 'keoni/extract-cv', $payload );

        if ( null === $result ) {
            wp_send_json_error( [ 'message' => __( 'Impossible de contacter le service IA.', 'keoni-bridge' ) ], 500 );
        }

        wp_send_json_success( $result );
    }

    public function ajax_extract_job(): void {
        check_ajax_referer( 'keoni_bridge_extract_job', 'nonce' );

        $job_id = isset( $_POST['job_id'] ) ? absint( wp_unslash( $_POST['job_id'] ) ) : 0;

        if ( $job_id <= 0 ) {
            wp_send_json_error( [ 'message' => __( 'Offre invalide.', 'keoni-bridge' ) ], 400 );
        }

        if ( ! $this->user_can_manage_job_matching( $job_id ) ) {
            wp_send_json_error( [ 'message' => __( 'Accès refusé.', 'keoni-bridge' ) ], 403 );
        }

        $rest     = new Keoni_Bridge_Rest();
        $request  = new WP_REST_Request( 'GET', '/keoni/v1/job/' . $job_id );
        $request->set_param( 'id', $job_id );
        $response = $rest->get_job( $request );
        $job      = $response->get_data();

        if ( empty( $job ) || 404 === $response->get_status() ) {
            wp_send_json_error( [ 'message' => __( 'Offre introuvable.', 'keoni-bridge' ) ], 404 );
        }

        $payload = [
            'id'          => $job['id'],
            'title'       => $job['title'] ?? '',
            'description' => $job['content'] ?? '',
            'content'     => $job['content'] ?? '',
            'excerpt'     => $job['excerpt'] ?? '',
            'keywords'    => $job['keywords'] ?? '',
            'location'    => $job['location'] ?? '',
            'meta'        => $job['meta'] ?? [],
        ];

        $result = $this->call_extract_webhook( 'keoni/extract-job', $payload );

        if ( null === $result ) {
            wp_send_json_error( [ 'message' => __( 'Impossible de contacter le service IA.', 'keoni-bridge' ) ], 500 );
        }

        wp_send_json_success( $result );
    }

    private function post_extract_webhook( string $path, array $payload ): ?array {
        $settings = Keoni_Bridge::get_settings();
        $base     = $settings['webhook_url'] ?? '';
        $secret   = $settings['webhook_secret'] ?? '';

        if ( empty( $base ) || empty( $secret ) ) {
            return null;
        }

        $pos = strpos( $base, '/webhook/' );

        if ( false === $pos ) {
            return null;
        }

        $url = substr( $base, 0, $pos + strlen( '/webhook/' ) ) . $path;

        $response = wp_remote_post( $url, [
            'timeout' => 20,
            'headers' => [
                'Content-Type' => 'application/json',
                'X-API-Key'    => sanitize_text_field( $secret ),
            ],
            'body'    => wp_json_encode( $payload ),
        ] );

        if ( is_wp_error( $response ) ) {
            error_log( sprintf( '[Keoni Bridge] Extract webhook error (%s): %s', $path, $response->get_error_message() ) );
            return null;
        }

        $status_code = (int) wp_remote_retrieve_response_code( $response );
        $body        = json_decode( (string) wp_remote_retrieve_body( $response ), true );

        if ( $status_code < 200 || $status_code >= 300 || ! is_array( $body ) ) {
            error_log( sprintf( '[Keoni Bridge] Extract webhook HTTP %d (%s).', $status_code, $path ) );
            return null;
        }

        return $body;
    }

    private function call_extract_webhook( string $path, array $payload ): ?array {
        $body = $this->post_extract_webhook( $path, $payload );

        if ( null === $body ) {
            return null;
        }

        return [
            'text'   => (string) ( $body['text'] ?? '' ),
            'skills' => array_values( array_filter( array_map( 'sanitize_text_field', (array) ( $body['skills'] ?? [] ) ) ) ),
        ];
    }

    public function ajax_save_scoring_profile(): void {
        check_ajax_referer( 'keoni_bridge_save_scoring_profile', 'nonce' );

        $job_id  = isset( $_POST['job_id'] ) ? absint( wp_unslash( $_POST['job_id'] ) ) : 0;
        $profile = isset( $_POST['scoring_profile'] ) ? sanitize_text_field( wp_unslash( $_POST['scoring_profile'] ) ) : '';

        if ( $job_id <= 0 ) {
            wp_send_json_error( [ 'message' => __( 'Job invalide.', 'keoni-bridge' ) ], 400 );
        }

        if ( ! array_key_exists( $profile, self::SCORING_PROFILES ) ) {
            wp_send_json_error( [ 'message' => __( 'Profil de scoring invalide.', 'keoni-bridge' ) ], 400 );
        }

        if ( ! $this->user_can_manage_job_matching( $job_id ) ) {
            wp_send_json_error( [ 'message' => __( 'Accès refusé.', 'keoni-bridge' ) ], 403 );
        }

        $previous = Keoni_Bridge_Repository::get_job_scoring_profile( $job_id );
        Keoni_Bridge_Repository::save_job_scoring_profile( $job_id, $profile );

        $cleared_results = 0;
        if ( $previous !== $profile ) {
            $cleared_results = Keoni_Bridge_Repository::delete_matching_results( $job_id );
        }

        wp_send_json_success( [
            'message'         => __( 'Profil de scoring enregistré.', 'keoni-bridge' ),
            'cleared_results' => $cleared_results > 0,
        ] );
    }

    public function scan_js_jobs(): void {
        global $wpdb;

        $last_scan = (int) get_option( $this->option_last_scan, 0 );
        $now       = current_time( 'timestamp', true );

        $table = $wpdb->prefix . 'js_job_jobs';

        // `status` (pas `jobstatus`, étape du pipeline RH -- voir la même
        // correction et sa justification dans
        // Keoni_Bridge_Rest::get_jobs()) : ce cron cherchait jusqu'ici sur
        // le mauvais champ et ne trouvait donc jamais aucune offre à
        // rescanner, silencieusement (aucune erreur, juste 0 ligne à
        // chaque passage).
        $rows = $wpdb->get_results(
            $wpdb->prepare(
                "SELECT id FROM {$table} WHERE status = 1 AND DATE(startpublishing) <= CURDATE() AND DATE(stoppublishing) >= CURDATE() AND UNIX_TIMESTAMP(modified) > %d ORDER BY modified ASC LIMIT 50",
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
