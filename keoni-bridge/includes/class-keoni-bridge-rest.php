<?php
/**
 * Endpoints REST permettant la communication avec n8n et le service Python.
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Keoni_Bridge_Rest {
    private string $namespace = 'keoni/v1';

    public function __construct() {
        add_action( 'rest_api_init', [ $this, 'register_routes' ] );
    }

    public function register_routes(): void {
        register_rest_route( $this->namespace, '/job/(?P<id>\d+)', [
            'methods'             => WP_REST_Server::READABLE,
            'callback'            => [ $this, 'get_job' ],
            'permission_callback' => [ $this, 'permission_check' ],
            'args'                => [
                'id' => [
                    'validate_callback' => [ $this, 'validate_numeric_param' ],
                ],
            ],
        ] );

        register_rest_route( $this->namespace, '/cvs', [
            'methods'             => WP_REST_Server::READABLE,
            'callback'            => [ $this, 'get_cvs' ],
            'permission_callback' => [ $this, 'permission_check' ],
            'args'                => [
                'offset' => [
                    'validate_callback' => [ $this, 'validate_numeric_param' ],
                    'default'           => 0,
                ],
                'limit'  => [
                    'validate_callback' => [ $this, 'validate_numeric_param' ],
                    'default'           => 100,
                ],
            ],
        ] );

        register_rest_route( $this->namespace, '/cv', [
            'methods'             => WP_REST_Server::CREATABLE,
            'callback'            => [ $this, 'store_cv' ],
            'permission_callback' => [ $this, 'permission_check' ],
        ] );

        register_rest_route( $this->namespace, '/cv/(?P<id>\d+)', [
            'methods'             => WP_REST_Server::READABLE,
            'callback'            => [ $this, 'get_cv_record' ],
            'permission_callback' => [ $this, 'permission_check' ],
            'args'                => [
                'id' => [
                    'validate_callback' => [ $this, 'validate_numeric_param' ],
                ],
            ],
        ] );

        register_rest_route( $this->namespace, '/matching', [
            'methods'             => WP_REST_Server::CREATABLE,
            'callback'            => [ $this, 'store_matching' ],
            'permission_callback' => [ $this, 'permission_check' ],
        ] );

        register_rest_route( $this->namespace, '/matching/(?P<job_id>\d+)', [
            'methods'             => WP_REST_Server::READABLE,
            'callback'            => [ $this, 'get_matching' ],
            'permission_callback' => '__return_true',
            'args'                => [
                'job_id'    => [ 'validate_callback' => [ $this, 'validate_numeric_param' ] ],
                'min_score' => [ 'validate_callback' => [ $this, 'validate_numeric_param' ], 'default' => 0 ],
                'limit'     => [ 'validate_callback' => [ $this, 'validate_numeric_param' ], 'default' => 20 ],
                'offset'    => [ 'validate_callback' => [ $this, 'validate_numeric_param' ], 'default' => 0 ],
            ],
        ] );
    }

    public function permission_check( WP_REST_Request $request ): bool {
        $provided = $request->get_header( 'x-api-key' );

        return ! empty( $provided ) && Keoni_Bridge::verify_api_key( $provided );
    }

    public function get_job( WP_REST_Request $request ): WP_REST_Response {
        global $wpdb;

        $job_id = absint( $request['id'] );
        $table  = $wpdb->prefix . 'js_job_jobs';

        $job = $wpdb->get_row(
            $wpdb->prepare( "SELECT * FROM {$table} WHERE id = %d LIMIT 1", $job_id ),
            ARRAY_A
        );

        if ( empty( $job ) ) {
            return new WP_REST_Response( [ 'message' => 'Job introuvable' ], 404 );
        }

        $data = [
            'id'         => $job_id,
            'title'      => sanitize_text_field( $job['title'] ?? '' ),
            'content'    => wp_kses_post( $job['description'] ?? '' ),
            'excerpt'    => wp_strip_all_tags( $job['description'] ?? '' ),
            'keywords'   => sanitize_text_field( $job['tags'] ?? '' ),
            'location'   => $this->build_job_location( $job ),
            'salary'     => $this->format_job_salary( $job ),
            'meta'       => [
                'company_id'      => absint( $job['companyid'] ?? 0 ),
                'jobcategory'     => absint( $job['jobcategory'] ?? 0 ),
                'jobtype'         => absint( $job['jobtype'] ?? 0 ),
                'jobstatus'       => absint( $job['jobstatus'] ?? 0 ),
                'experience'      => $job['experience'] ?? '',
                'skills'          => $job['prefferdskills'] ?? '',
                'applyinfo'       => $job['applyinfo'] ?? '',
                'startpublishing' => $job['startpublishing'] ?? '',
                'stoppublishing'  => $job['stoppublishing'] ?? '',
            ],
            'permalink'  => $this->build_job_permalink( $job_id ),
            'updated_at' => $this->job_updated_at( $job ),
        ];

        return new WP_REST_Response( $data );
    }

    public function get_cvs( WP_REST_Request $request ): WP_REST_Response {
        global $wpdb;

        $offset = absint( $request->get_param( 'offset' ) );
        $limit  = min( 500, max( 1, absint( $request->get_param( 'limit' ) ) ) );

        $resume_table = $wpdb->prefix . 'js_job_resume';
        $cv_table     = $wpdb->prefix . 'cv_database';

        $rows = $wpdb->get_results(
            $wpdb->prepare(
                "SELECT r.*, d.text_content AS cv_text_content, d.metadata AS cv_metadata
                 FROM {$resume_table} r
                 LEFT JOIN {$cv_table} d ON d.candidate_email = r.email_address
                 ORDER BY r.last_modified DESC
                 LIMIT %d OFFSET %d",
                $limit,
                $offset
            ),
            ARRAY_A
        );

        $items = array_map( [ $this, 'normalize_resume' ], $rows );

        return new WP_REST_Response( [
            'offset' => $offset,
            'limit'  => $limit,
            'count'  => count( $items ),
            'items'  => $items,
        ] );
    }

    public function store_cv( WP_REST_Request $request ): WP_REST_Response {
        $payload = $this->get_request_payload( $request );

        $email = sanitize_email( $payload['candidate_email'] ?? '' );

        if ( empty( $email ) ) {
            return new WP_REST_Response( [ 'message' => 'Payload invalide', 'detail' => 'candidate_email manquant' ], 400 );
        }

        $data = [
            'candidate_email'   => $email,
            'application_title' => sanitize_text_field( $payload['application_title'] ?? '' ),
            'file_name'         => sanitize_text_field( $payload['file_name'] ?? '' ),
            'file_path'         => sanitize_text_field( $payload['file_path'] ?? '' ),
            'text_content'      => wp_kses_post( $payload['text_content'] ?? '' ),
            'metadata'          => $payload['metadata'] ?? [],
        ];

        $result = Keoni_Bridge_Repository::upsert_cv( $data );
        $status = ( 'inserted' === $result['action'] ) ? 201 : 200;

        return new WP_REST_Response( $result, $status );
    }

    public function get_cv_record( WP_REST_Request $request ): WP_REST_Response {
        $cv_id = absint( $request['id'] );
        $cv    = Keoni_Bridge_Repository::get_cv( $cv_id );

        if ( empty( $cv ) ) {
            return new WP_REST_Response( [ 'message' => 'CV introuvable' ], 404 );
        }

        return new WP_REST_Response( $cv );
    }

    public function store_matching( WP_REST_Request $request ): WP_REST_Response {
        global $wpdb;

        $payload = $this->get_request_payload( $request );

        if ( empty( $payload['job_id'] ) ) {
            return new WP_REST_Response( [ 'message' => 'Payload invalide', 'detail' => 'job_id manquant' ], 400 );
        }

        if ( empty( $payload['results'] ) || ! is_array( $payload['results'] ) ) {
            return new WP_REST_Response( [ 'message' => 'Payload invalide', 'detail' => 'results manquant ou invalide' ], 400 );
        }

        $table = $wpdb->prefix . 'cv_matching_results';
        $jobId = absint( $payload['job_id'] );

        foreach ( $payload['results'] as $result ) {
            $wpdb->replace(
                $table,
                [
                    'job_id'    => $jobId,
                    'cv_id'     => absint( $result['cv_id'] ?? 0 ),
                    'score'     => floatval( $result['score'] ?? 0 ),
                    'strengths' => wp_json_encode( $result['strengths'] ?? [] ),
                    'weaknesses'=> wp_json_encode( $result['weaknesses'] ?? [] ),
                    'keywords'  => wp_json_encode( $result['keywords'] ?? [] ),
                    'extra'     => wp_json_encode( $result['extra'] ?? [] ),
                    'updated_at'=> current_time( 'mysql', true ),
                ]
            );
        }

        return new WP_REST_Response( [ 'inserted' => count( $payload['results'] ) ], 201 );
    }

    public function get_matching( WP_REST_Request $request ): WP_REST_Response {
        $job_id    = absint( $request['job_id'] );
        $min_score = floatval( $request->get_param( 'min_score' ) );
        $limit     = absint( $request->get_param( 'limit' ) );
        $offset    = absint( $request->get_param( 'offset' ) );

        $results = Keoni_Bridge_Repository::get_matching_results( $job_id, $min_score, $limit, $offset );

        $with_html = (bool) $request->get_param( 'with_html' );

        if ( $with_html && ! empty( $results['items'] ) && class_exists( 'Keoni_Bridge_Shortcode' ) ) {
            $cv_map = Keoni_Bridge_Repository::get_cvs_by_ids( wp_list_pluck( $results['items'], 'cv_id' ) );
            $results['items_html'] = Keoni_Bridge_Shortcode::render_cards_html( $results['items'], $cv_map );
        }

        return new WP_REST_Response( $results );
    }

    public function validate_numeric_param( $value, ?WP_REST_Request $request = null, string $param = '' ): bool {
        return is_numeric( $value );
    }

    private function build_job_location( array $job ): string {
        $parts = array_filter( [
            $job['city'] ?? '',
            $job['state'] ?? '',
            $job['country'] ?? '',
        ] );

        return implode( ', ', $parts );
    }

    private function format_job_salary( array $job ): string {
        $from = $job['salaryrangefrom'] ?? '';
        $to   = $job['salaryrangeto'] ?? '';

        if ( $from && $to ) {
            return trim( sprintf( '%s - %s', $from, $to ) );
        }

        return (string) ( $from ?: $to );
    }

    private function build_job_permalink( int $job_id ): string {
        $args = [
            'jsjobs'   => 'job',
            'jsjobslt' => 'viewjob',
            'jsjobsid' => $job_id,
        ];

        return esc_url_raw( add_query_arg( $args, home_url( '/' ) ) );
    }

    private function job_updated_at( array $job ): string {
        $modified = $job['modified'] ?? '';
        $created  = $job['created'] ?? '';

        if ( ! empty( $modified ) && '0000-00-00 00:00:00' !== $modified ) {
            return $modified;
        }

        return $created;
    }

    private function normalize_resume( array $resume ): array {
        return [
            'id'          => absint( $resume['id'] ?? 0 ),
            'title'       => sanitize_text_field( $resume['application_title'] ?? '' ),
            'keywords'    => sanitize_text_field( $resume['keywords'] ?? '' ),
            'first_name'  => sanitize_text_field( $resume['first_name'] ?? '' ),
            'last_name'   => sanitize_text_field( $resume['last_name'] ?? '' ),
            'email'       => sanitize_email( $resume['email_address'] ?? '' ),
            'phone'       => sanitize_text_field( $resume['cell'] ?? $resume['home_phone'] ?? '' ),
            'salary_from' => $resume['jobsalaryrangestart'] ?? '',
            'salary_to'   => $resume['jobsalaryrangeend'] ?? '',
            'job_type'    => absint( $resume['jobtype'] ?? 0 ),
            'experience'  => absint( $resume['experienceid'] ?? 0 ),
            'skills'      => wp_strip_all_tags( $resume['skills'] ?? '' ),
            'resume'      => wp_kses_post( $resume['resume'] ?? '' ),
            'text_content'=> wp_kses_post( $resume['cv_text_content'] ?? '' ),
            'metadata'    => $this->normalize_cv_metadata( $resume['cv_metadata'] ?? '' ),
            'updated_at'  => $this->resume_updated_at( $resume ),
        ];
    }

    private function normalize_cv_metadata( $raw ): array {
        if ( empty( $raw ) ) {
            return [];
        }

        if ( is_array( $raw ) ) {
            return $raw;
        }

        $decoded = json_decode( (string) $raw, true );

        return ( JSON_ERROR_NONE === json_last_error() && is_array( $decoded ) ) ? $decoded : [];
    }

    private function resume_updated_at( array $resume ): string {
        $modified = $resume['last_modified'] ?? '';
        $created  = $resume['created'] ?? '';

        if ( ! empty( $modified ) && '0000-00-00 00:00:00' !== $modified ) {
            return $modified;
        }

        return $created;
    }

    private function get_request_payload( WP_REST_Request $request ): array {
        $payload = $request->get_json_params();

        if ( is_array( $payload ) && ! empty( $payload ) ) {
            return $payload;
        }

        $raw_body = (string) $request->get_body();

        if ( empty( $raw_body ) ) {
            return [];
        }

        $decoded = json_decode( $raw_body, true );

        return ( JSON_ERROR_NONE === json_last_error() && is_array( $decoded ) ) ? $decoded : [];
    }
}
