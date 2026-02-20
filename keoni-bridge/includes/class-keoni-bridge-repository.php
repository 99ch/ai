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
            "SELECT SQL_CALC_FOUND_ROWS
                    cv_id,
                    MAX(score) AS score,
                    MAX(strengths) AS strengths,
                    MAX(weaknesses) AS weaknesses,
                    MAX(keywords) AS keywords,
                    MAX(extra) AS extra,
                    MAX(updated_at) AS updated_at
             FROM {$table}
             WHERE job_id = %d AND score >= %f
             GROUP BY cv_id
             ORDER BY score DESC
             LIMIT %d OFFSET %d",
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

    public static function get_matching_status( int $job_id ): array {
        global $wpdb;

        $table = $wpdb->prefix . 'cv_matching_results';

        $last_updated = $wpdb->get_var(
            $wpdb->prepare( "SELECT MAX(updated_at) FROM {$table} WHERE job_id = %d", $job_id )
        );

        $total = (int) $wpdb->get_var(
            $wpdb->prepare( "SELECT COUNT(DISTINCT cv_id) FROM {$table} WHERE job_id = %d", $job_id )
        );

        return [
            'total'        => $total,
            'last_updated' => $last_updated ?: '',
        ];
    }

    public static function get_matching_kpis( int $job_id ): array {
        global $wpdb;

        $table = $wpdb->prefix . 'cv_matching_results';

        $aggregates = $wpdb->get_row(
            $wpdb->prepare(
                "SELECT
                    COUNT(*) AS candidates_count,
                    AVG(score) AS avg_score,
                    MAX(score) AS best_score,
                    MIN(score) AS min_score,
                    MAX(updated_at) AS last_updated
                 FROM (
                    SELECT
                        cv_id,
                        MAX(score) AS score,
                        MAX(updated_at) AS updated_at
                    FROM {$table}
                    WHERE job_id = %d
                    GROUP BY cv_id
                 ) grouped",
                $job_id
            ),
            ARRAY_A
        );

        $duration_ms = null;
        $rows = $wpdb->get_results(
            $wpdb->prepare(
                "SELECT extra, updated_at
                 FROM {$table}
                 WHERE job_id = %d
                   AND extra IS NOT NULL
                   AND extra != ''
                 ORDER BY updated_at DESC",
                $job_id
            ),
            ARRAY_A
        );

        if ( ! empty( $rows ) ) {
            foreach ( $rows as $row ) {
                $raw_extra = $row['extra'] ?? '';
                if ( empty( $raw_extra ) ) {
                    continue;
                }

                $extra = json_decode( (string) $raw_extra, true );

                if ( ! is_array( $extra ) ) {
                    continue;
                }

                $found = self::extract_duration_ms_from_extra( $extra );

                if ( null === $found ) {
                    $found = null;
                }

                if ( null !== $found ) {
                    $duration_ms = (int) $found;
                    break;
                }
            }
        }

        return [
            'candidates_count' => (int) ( $aggregates['candidates_count'] ?? 0 ),
            'avg_score'        => isset( $aggregates['avg_score'] ) ? (float) $aggregates['avg_score'] : 0,
            'best_score'       => isset( $aggregates['best_score'] ) ? (float) $aggregates['best_score'] : 0,
            'min_score'        => isset( $aggregates['min_score'] ) ? (float) $aggregates['min_score'] : 0,
            'last_updated'     => (string) ( $aggregates['last_updated'] ?? '' ),
            'duration_ms'      => null !== $duration_ms ? (int) $duration_ms : null,
        ];
    }

    public static function delete_matching_results( int $job_id ): int {
        global $wpdb;

        $table = $wpdb->prefix . 'cv_matching_results';

        return (int) $wpdb->delete( $table, [ 'job_id' => $job_id ] );
    }

    public static function get_resumes_by_emails( array $emails ): array {
        global $wpdb;

        $emails = array_values( array_unique( array_filter( array_map( 'sanitize_email', $emails ) ) ) );

        if ( empty( $emails ) ) {
            return [];
        }

        $placeholders = implode( ',', array_fill( 0, count( $emails ), '%s' ) );
        $resume_table = $wpdb->prefix . 'js_job_resume';
        $cat_table    = $wpdb->prefix . 'js_job_categories';
        $jobtype_tbl  = $wpdb->prefix . 'js_job_jobtypes';
        $salary_tbl   = $wpdb->prefix . 'js_job_salaryrange';
        $salary_type  = $wpdb->prefix . 'js_job_salaryrangetypes';
        $currency_tbl = $wpdb->prefix . 'js_job_currencies';
        $city_tbl     = $wpdb->prefix . 'js_job_cities';
        $state_tbl    = $wpdb->prefix . 'js_job_states';
        $country_tbl  = $wpdb->prefix . 'js_job_countries';
        $exp_tbl      = $wpdb->prefix . 'js_job_experiences';

          $query = $wpdb->prepare(
                "SELECT resume.id, CONCAT(resume.alias,'-',resume.id) AS aliasid, resume.first_name, resume.last_name,
                    resume.application_title, resume.email_address, category.cat_title,
                    exp.title AS total_experience, resume.created, jobtype.title AS jobtypetitle,
                    resume.photo, salary_from.rangestart, salary_to.rangeend, rangetype.title AS rangetype,
                          currency.symbol, city.cityName AS cityname, state.name AS statename,
                          country.name AS countryname
             FROM {$resume_table} AS resume
                 LEFT JOIN {$cat_table} AS category ON category.id = resume.job_category
             LEFT JOIN {$jobtype_tbl} AS jobtype ON jobtype.id = resume.jobtype
             LEFT JOIN {$salary_tbl} AS salary_from ON salary_from.id = resume.jobsalaryrangestart
             LEFT JOIN {$salary_tbl} AS salary_to ON salary_to.id = resume.jobsalaryrangeend
             LEFT JOIN {$salary_type} AS rangetype ON rangetype.id = resume.jobsalaryrangetype
             LEFT JOIN {$currency_tbl} AS currency ON currency.id = resume.currencyid
                 LEFT JOIN (
                     SELECT resumeid, MAX(address_city) AS address_city
                     FROM {$wpdb->prefix}js_job_resumeaddresses
                     GROUP BY resumeid
                 ) AS address ON address.resumeid = resume.id
             LEFT JOIN {$city_tbl} AS city ON city.id = address.address_city
             LEFT JOIN {$state_tbl} AS state ON state.id = city.stateid
             LEFT JOIN {$country_tbl} AS country ON country.id = city.countryid
             LEFT JOIN {$exp_tbl} AS exp ON exp.id = resume.experienceid
             WHERE resume.email_address IN ({$placeholders})
             GROUP BY resume.id",
            ...$emails
        );

        $rows = $wpdb->get_results( $query, ARRAY_A );

        if ( empty( $rows ) ) {
            return [];
        }

        $common_model = class_exists( 'JSJOBSincluder' ) ? JSJOBSincluder::getJSModel( 'common' ) : null;
        $config_model = class_exists( 'JSJOBSincluder' ) ? JSJOBSincluder::getJSModel( 'configuration' ) : null;
        $data_directory = $config_model ? $config_model->getConfigurationByConfigName( 'data_directory' ) : '';
        $uploads        = wp_get_upload_dir();
        $default_avatar = defined( 'JSJOBS_PLUGIN_URL' ) ? JSJOBS_PLUGIN_URL . 'includes/images/users.png' : '';
        $resume_page_id = class_exists( 'jsjobs' ) ? jsjobs::getPageid() : 0;

        $indexed = [];

        foreach ( $rows as $row ) {
            $salary = '';
            $location = '';

            if ( $common_model ) {
                $salary   = $common_model->getSalaryRangeView( $row['symbol'] ?? '', $row['rangestart'] ?? '', $row['rangeend'] ?? '', $row['rangetype'] ?? '' );
                $location = $common_model->getLocationForView( $row['cityname'] ?? '', $row['statename'] ?? '', $row['countryname'] ?? '' );
            } else {
                $location = implode( ', ', array_filter( [ $row['cityname'] ?? '', $row['statename'] ?? '', $row['countryname'] ?? '' ] ) );
            }

            $photo_url = $default_avatar;

            if ( ! empty( $row['photo'] ) && ! empty( $uploads['baseurl'] ) && ! empty( $data_directory ) ) {
                $photo_url = trailingslashit( $uploads['baseurl'] ) . $data_directory . '/data/jobseeker/resume_' . $row['id'] . '/photo/' . $row['photo'];
            }

            $view_url = '';

            if ( class_exists( 'jsjobs' ) ) {
                $view_url = jsjobs::makeUrl( [
                    'jsjobsme'    => 'resume',
                    'jsjobslt'    => 'viewresume',
                    'jsjobsid'    => $row['aliasid'],
                    'jsjobspageid'=> $resume_page_id,
                ] );
            }

            $email_key = strtolower( $row['email_address'] ?? '' );

            if ( empty( $email_key ) ) {
                continue;
            }

            $indexed[ $email_key ] = [
                'id'                => (int) $row['id'],
                'alias_id'          => $row['aliasid'],
                'first_name'        => $row['first_name'],
                'last_name'         => $row['last_name'],
                'job_type'          => $row['jobtypetitle'],
                'application_title' => $row['application_title'],
                'email'             => $row['email_address'],
                'category'          => $row['cat_title'],
                'experience'        => $row['total_experience'],
                'salary'            => $salary,
                'location'          => $location,
                'photo_url'         => $photo_url,
                'view_url'          => $view_url,
                'created_at'        => $row['created'],
            ];
        }

        return $indexed;
    }

    public static function get_resumes_by_ids( array $ids ): array {
        global $wpdb;

        $ids = array_values( array_unique( array_filter( array_map( 'absint', $ids ) ) ) );

        if ( empty( $ids ) ) {
            return [];
        }

        $placeholders = implode( ',', array_fill( 0, count( $ids ), '%d' ) );
        $resume_table = $wpdb->prefix . 'js_job_resume';
        $cat_table    = $wpdb->prefix . 'js_job_categories';
        $jobtype_tbl  = $wpdb->prefix . 'js_job_jobtypes';
        $salary_tbl   = $wpdb->prefix . 'js_job_salaryrange';
        $salary_type  = $wpdb->prefix . 'js_job_salaryrangetypes';
        $currency_tbl = $wpdb->prefix . 'js_job_currencies';
        $city_tbl     = $wpdb->prefix . 'js_job_cities';
        $state_tbl    = $wpdb->prefix . 'js_job_states';
        $country_tbl  = $wpdb->prefix . 'js_job_countries';
        $exp_tbl      = $wpdb->prefix . 'js_job_experiences';

        $query = $wpdb->prepare(
            "SELECT resume.id, CONCAT(resume.alias,'-',resume.id) AS aliasid, resume.first_name, resume.last_name,
                    resume.application_title, resume.email_address, category.cat_title,
                    exp.title AS total_experience, resume.created, jobtype.title AS jobtypetitle,
                    resume.photo, salary_from.rangestart, salary_to.rangeend, rangetype.title AS rangetype,
                          currency.symbol, city.cityName AS cityname, state.name AS statename,
                          country.name AS countryname
             FROM {$resume_table} AS resume
             LEFT JOIN {$cat_table} AS category ON category.id = resume.job_category
             LEFT JOIN {$jobtype_tbl} AS jobtype ON jobtype.id = resume.jobtype
             LEFT JOIN {$salary_tbl} AS salary_from ON salary_from.id = resume.jobsalaryrangestart
             LEFT JOIN {$salary_tbl} AS salary_to ON salary_to.id = resume.jobsalaryrangeend
             LEFT JOIN {$salary_type} AS rangetype ON rangetype.id = resume.jobsalaryrangetype
             LEFT JOIN {$currency_tbl} AS currency ON currency.id = resume.currencyid
             LEFT JOIN (
                 SELECT resumeid, MAX(address_city) AS address_city
                 FROM {$wpdb->prefix}js_job_resumeaddresses
                 GROUP BY resumeid
             ) AS address ON address.resumeid = resume.id
             LEFT JOIN {$city_tbl} AS city ON city.id = address.address_city
             LEFT JOIN {$state_tbl} AS state ON state.id = city.stateid
             LEFT JOIN {$country_tbl} AS country ON country.id = city.countryid
             LEFT JOIN {$exp_tbl} AS exp ON exp.id = resume.experienceid
             WHERE resume.id IN ({$placeholders})
             GROUP BY resume.id",
            ...$ids
        );

        $rows = $wpdb->get_results( $query, ARRAY_A );

        if ( empty( $rows ) ) {
            return [];
        }

        $common_model   = class_exists( 'JSJOBSincluder' ) ? JSJOBSincluder::getJSModel( 'common' ) : null;
        $config_model   = class_exists( 'JSJOBSincluder' ) ? JSJOBSincluder::getJSModel( 'configuration' ) : null;
        $data_directory = $config_model ? $config_model->getConfigurationByConfigName( 'data_directory' ) : '';
        $uploads        = wp_get_upload_dir();
        $default_avatar = defined( 'JSJOBS_PLUGIN_URL' ) ? JSJOBS_PLUGIN_URL . 'includes/images/users.png' : '';
        $resume_page_id = class_exists( 'jsjobs' ) ? jsjobs::getPageid() : 0;

        $indexed = [];

        foreach ( $rows as $row ) {
            $salary = '';
            $location = '';

            if ( $common_model ) {
                $salary   = $common_model->getSalaryRangeView( $row['symbol'] ?? '', $row['rangestart'] ?? '', $row['rangeend'] ?? '', $row['rangetype'] ?? '' );
                $location = $common_model->getLocationForView( $row['cityname'] ?? '', $row['statename'] ?? '', $row['countryname'] ?? '' );
            } else {
                $location = implode( ', ', array_filter( [ $row['cityname'] ?? '', $row['statename'] ?? '', $row['countryname'] ?? '' ] ) );
            }

            $photo_url = $default_avatar;

            if ( ! empty( $row['photo'] ) && ! empty( $uploads['baseurl'] ) && ! empty( $data_directory ) ) {
                $photo_url = trailingslashit( $uploads['baseurl'] ) . $data_directory . '/data/jobseeker/resume_' . $row['id'] . '/photo/' . $row['photo'];
            }

            $view_url = '';

            if ( class_exists( 'jsjobs' ) ) {
                $view_url = jsjobs::makeUrl( [
                    'jsjobsme'    => 'resume',
                    'jsjobslt'    => 'viewresume',
                    'jsjobsid'    => $row['aliasid'],
                    'jsjobspageid'=> $resume_page_id,
                ] );
            }

            $indexed[ (int) $row['id'] ] = [
                'id'                => (int) $row['id'],
                'alias_id'          => $row['aliasid'],
                'first_name'        => $row['first_name'],
                'last_name'         => $row['last_name'],
                'job_type'          => $row['jobtypetitle'],
                'application_title' => $row['application_title'],
                'email'             => $row['email_address'],
                'category'          => $row['cat_title'],
                'experience'        => $row['total_experience'],
                'salary'            => $salary,
                'location'          => $location,
                'photo_url'         => $photo_url,
                'view_url'          => $view_url,
                'created_at'        => $row['created'],
            ];
        }

        return $indexed;
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

    private static function extract_duration_ms_from_extra( array $extra ): ?int {
        $keys = [
            'workflow_duration_ms',
            'duration_ms',
            'processing_duration_ms',
            'execution_ms',
            'elapsed_ms',
            'duration',
            'duration_s',
            'duration_sec',
            'duration_seconds',
            'execution_time_s',
            'elapsed_seconds',
            'duration_text',
        ];

        foreach ( $keys as $key ) {
            if ( ! isset( $extra[ $key ] ) ) {
                continue;
            }

            $raw = $extra[ $key ];

            if ( is_numeric( $raw ) ) {
                $num = (float) $raw;
                if ( $num <= 0 ) {
                    continue;
                }

                if ( str_ends_with( $key, '_ms' ) ) {
                    return (int) round( $num );
                }

                if ( in_array( $key, [ 'duration_s', 'duration_sec', 'duration_seconds', 'execution_time_s', 'elapsed_seconds' ], true ) ) {
                    return (int) round( $num * 1000 );
                }

                if ( 'duration' === $key ) {
                    return $num >= 1000 ? (int) round( $num ) : (int) round( $num * 1000 );
                }

                return (int) round( $num );
            }

            if ( is_string( $raw ) ) {
                $value = trim( strtolower( $raw ) );

                if ( preg_match( '/([0-9]+(?:\.[0-9]+)?)\s*ms/', $value, $m ) ) {
                    return (int) round( (float) $m[1] );
                }

                if ( preg_match( '/([0-9]+(?:\.[0-9]+)?)\s*s(ec)?\b/', $value, $m ) ) {
                    return (int) round( (float) $m[1] * 1000 );
                }

                if ( is_numeric( $value ) ) {
                    $num = (float) $value;
                    return $num >= 1000 ? (int) round( $num ) : (int) round( $num * 1000 );
                }
            }
        }

        return null;
    }

    private static function extract_batch_size_from_extra( array $extra ): ?int {
        $keys = [ 'batch_size', 'results_count', 'processed_count' ];

        foreach ( $keys as $key ) {
            if ( isset( $extra[ $key ] ) && is_numeric( $extra[ $key ] ) ) {
                $value = (int) $extra[ $key ];
                if ( $value > 0 ) {
                    return $value;
                }
            }
        }

        return null;
    }

    private static function extract_processed_at_from_extra( array $extra ): string {
        $keys = [ 'processed_at', 'executed_at', 'completed_at' ];

        foreach ( $keys as $key ) {
            if ( empty( $extra[ $key ] ) ) {
                continue;
            }

            $value = (string) $extra[ $key ];
            if ( strtotime( $value ) ) {
                return $value;
            }
        }

        return '';
    }
}
