<?php
/**
 * Accès aux tables personnalisées du plugin.
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Keoni_Bridge_Repository {
    public static function upsert_cv( array $data ): array {
        global $wpdb;

        $table = $wpdb->prefix . 'cv_database';
        $existing_id = self::get_cv_id_by_email( $data['candidate_email'] );

        $payload = self::format_cv_payload( $data );

        if ( $existing_id ) {
            $wpdb->update( $table, $payload, [ 'id' => $existing_id ] );

            return [
                'id'     => $existing_id,
                'action' => 'updated',
            ];
        }

        $wpdb->insert( $table, $payload );

        return [
            'id'     => (int) $wpdb->insert_id,
            'action' => 'inserted',
        ];
    }

    public static function get_cv( int $id ): ?array {
        global $wpdb;

        $table = $wpdb->prefix . 'cv_database';
        $row   = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$table} WHERE id = %d LIMIT 1", $id ), ARRAY_A );

        if ( empty( $row ) ) {
            return null;
        }

        $row['metadata'] = json_decode( (string) ( $row['metadata'] ?? '' ), true ) ?: [];

        return $row;
    }

    public static function get_cvs_by_ids( array $ids ): array {
        global $wpdb;

        $ids = array_values( array_unique( array_filter( array_map( 'absint', $ids ) ) ) );

        if ( empty( $ids ) ) {
            return [];
        }

        $table        = $wpdb->prefix . 'cv_database';
        $placeholders = implode( ',', array_fill( 0, count( $ids ), '%d' ) );
        $query        = "SELECT * FROM {$table} WHERE id IN ($placeholders)";
        $prepared     = $wpdb->prepare( $query, ...$ids );
        $rows         = $wpdb->get_results( $prepared, ARRAY_A );

        if ( empty( $rows ) ) {
            return [];
        }

        $indexed = [];

        foreach ( $rows as $row ) {
            $row['metadata'] = json_decode( (string) ( $row['metadata'] ?? '' ), true ) ?: [];
            $indexed[ (int) $row['id'] ] = $row;
        }

        return $indexed;
    }

    public static function get_matching_results( int $job_id, float $min_score, int $limit, int $offset ): array {
        global $wpdb;

        $limit  = min( 100, max( 1, $limit ) );
        $offset = max( 0, $offset );

        $table = $wpdb->prefix . 'cv_matching_results';

        $query = $wpdb->prepare(
            "SELECT SQL_CALC_FOUND_ROWS * FROM {$table} WHERE job_id = %d AND score >= %f ORDER BY score DESC LIMIT %d OFFSET %d",
            $job_id,
            $min_score,
            $limit,
            $offset
        );

        $items = $wpdb->get_results( $query, ARRAY_A );
        $total = (int) $wpdb->get_var( 'SELECT FOUND_ROWS()' );

        foreach ( $items as &$item ) {
            $item['strengths'] = json_decode( (string) ( $item['strengths'] ?? '' ), true ) ?: [];
            $item['weaknesses']= json_decode( (string) ( $item['weaknesses'] ?? '' ), true ) ?: [];
            $item['keywords']  = json_decode( (string) ( $item['keywords'] ?? '' ), true ) ?: [];
            $item['extra']     = json_decode( (string) ( $item['extra'] ?? '' ), true ) ?: [];
        }

        return [
            'items'  => $items,
            'total'  => $total,
            'limit'  => $limit,
            'offset' => $offset,
        ];
    }

    public static function list_cvs( array $args = [] ): array {
        global $wpdb;

        $defaults = [
            'paged'        => 1,
            'per_page'     => 20,
            'search'       => '',
            'order'        => 'DESC',
            'status'       => '',
            'updated_from' => '',
            'updated_to'   => '',
        ];

        $args = wp_parse_args( $args, $defaults );

        $paged        = max( 1, (int) $args['paged'] );
        $per_page     = max( 1, min( 100, (int) $args['per_page'] ) );
        $offset       = ( $paged - 1 ) * $per_page;
        $order        = strtoupper( $args['order'] ) === 'ASC' ? 'ASC' : 'DESC';
        $status       = sanitize_text_field( (string) $args['status'] );
        $updated_from = sanitize_text_field( (string) $args['updated_from'] );
        $updated_to   = sanitize_text_field( (string) $args['updated_to'] );

        $table = $wpdb->prefix . 'cv_database';

        $where  = [ '1 = 1' ];
        $params = [];

        if ( ! empty( $args['search'] ) ) {
            $like      = '%' . $wpdb->esc_like( $args['search'] ) . '%';
            $where[]   = '(candidate_email LIKE %s OR application_title LIKE %s)';
            $params [] = $like;
            $params [] = $like;
        }

        if ( ! empty( $status ) ) {
            $needle    = '%' . $wpdb->esc_like( '"status":"' . $status . '"' ) . '%';
            $where[]   = 'metadata LIKE %s';
            $params [] = $needle;
        }

        if ( ! empty( $updated_from ) ) {
            $where[]   = 'DATE(updated_at) >= %s';
            $params [] = $updated_from;
        }

        if ( ! empty( $updated_to ) ) {
            $where[]   = 'DATE(updated_at) <= %s';
            $params [] = $updated_to;
        }

        $params[] = $per_page;
        $params[] = $offset;

        $prepared_where = implode( ' AND ', $where );

        $query = $wpdb->prepare(
            "SELECT SQL_CALC_FOUND_ROWS * FROM {$table} WHERE {$prepared_where} ORDER BY updated_at {$order} LIMIT %d OFFSET %d",
            ...$params
        );

        $items = $wpdb->get_results( $query, ARRAY_A );
        $total = (int) $wpdb->get_var( 'SELECT FOUND_ROWS()' );

        foreach ( $items as &$item ) {
            $item['metadata'] = json_decode( (string) ( $item['metadata'] ?? '' ), true ) ?: [];
        }

        return [
            'items'    => $items,
            'total'    => $total,
            'per_page' => $per_page,
            'paged'    => $paged,
        ];
    }

    public static function update_cv( int $id, array $data ): bool {
        global $wpdb;

        if ( $id <= 0 ) {
            return false;
        }

        $table   = $wpdb->prefix . 'cv_database';
        $payload = [];

        if ( isset( $data['candidate_email'] ) ) {
            $payload['candidate_email'] = $data['candidate_email'];
        }

        if ( isset( $data['application_title'] ) ) {
            $payload['application_title'] = $data['application_title'];
        }

        if ( isset( $data['text_content'] ) ) {
            $payload['text_content'] = $data['text_content'];
        }

        if ( array_key_exists( 'metadata', $data ) ) {
            $payload['metadata'] = wp_json_encode( $data['metadata'] ?? [] );
        }

        if ( empty( $payload ) ) {
            return false;
        }

        $payload['updated_at'] = current_time( 'mysql', true );

        return false !== $wpdb->update( $table, $payload, [ 'id' => $id ] );
    }

    private static function get_cv_id_by_email( string $email ): ?int {
        global $wpdb;

        $table = $wpdb->prefix . 'cv_database';
        $id    = $wpdb->get_var( $wpdb->prepare( "SELECT id FROM {$table} WHERE candidate_email = %s LIMIT 1", $email ) );

        return $id ? (int) $id : null;
    }

    private static function format_cv_payload( array $data ): array {
        $metadata = $data['metadata'];

        if ( is_string( $metadata ) ) {
            $decoded = json_decode( $metadata, true );
            $metadata = ( JSON_ERROR_NONE === json_last_error() ) ? $decoded : [];
        }

        if ( ! is_array( $metadata ) ) {
            $metadata = [];
        }

        return [
            'candidate_email'  => $data['candidate_email'],
            'application_title'=> $data['application_title'],
            'file_name'        => $data['file_name'],
            'file_path'        => $data['file_path'],
            'text_content'     => $data['text_content'],
            'metadata'         => wp_json_encode( $metadata ),
            'updated_at'       => current_time( 'mysql', true ),
        ];
    }
}
