<?php
/**
 * Shortcode Elementor/WordPress affichant les résultats.
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Keoni_Bridge_Shortcode {
    private string $style_handle = 'keoni-matching';
    private string $script_handle = 'keoni-matching-js';

    public function __construct() {
        add_shortcode( 'keoni_matching', [ $this, 'render' ] );
        add_action( 'wp_enqueue_scripts', [ $this, 'register_assets' ] );
        add_action( 'wp_ajax_keoni_matching_load_more', [ $this, 'ajax_load_more' ] );
        add_action( 'wp_ajax_nopriv_keoni_matching_load_more', [ $this, 'ajax_load_more' ] );
    }

    public function render( array $atts = [] ): string {
        $atts = shortcode_atts(
            [
                'job_id'    => 0,
                'limit'     => 20,
                'min_score' => 0,
                'offset'    => 0,
            ],
            $atts,
            'keoni_matching'
        );

        $job_id = absint( $atts['job_id'] );

        if ( 0 === $job_id ) {
            return '<p>' . esc_html__( 'Aucun job_id fourni.', 'keoni-bridge' ) . '</p>';
        }

        $data = Keoni_Bridge_Repository::get_matching_results(
            $job_id,
            floatval( $atts['min_score'] ),
            absint( $atts['limit'] ),
            absint( $atts['offset'] )
        );

        if ( empty( $data['items'] ) ) {
            return '<div class="keoni-matching__empty">' . esc_html__( 'Aucun candidat correspondant.', 'keoni-bridge' ) . '</div>';
        }

        wp_enqueue_style( $this->style_handle );
        wp_enqueue_script( $this->script_handle );

        $items    = $data['items'];
        $cv_ids   = wp_list_pluck( $items, 'cv_id' );
        $cv_map   = Keoni_Bridge_Repository::get_cvs_by_ids( $cv_ids );
        $emails   = array_filter( array_map( static function ( $cv ) {
            return $cv['candidate_email'] ?? '';
        }, array_values( $cv_map ) ) );
        $resume_map = Keoni_Bridge_Repository::get_resumes_by_emails( $emails );
        $resume_map_by_id = Keoni_Bridge_Repository::get_resumes_by_ids( $cv_ids );
        $total      = intval( $data['total'] ?? count( $items ) );
        $limit      = intval( $data['limit'] ?? $atts['limit'] );
        $offset     = intval( $data['offset'] ?? $atts['offset'] );
        $has_more   = ( $offset + $limit ) < $total;
        $kpis       = Keoni_Bridge_Repository::get_matching_kpis( $job_id );

        $avg_score_label = number_format_i18n( (float) ( $kpis['avg_score'] ?? 0 ), 1 );
        $best_score_label = number_format_i18n( (float) ( $kpis['best_score'] ?? 0 ), 1 );
        $duration_label = self::format_duration_ms( $kpis['duration_ms'] ?? null );
        $qualified_count = (int) ( $kpis['qualified_count'] ?? 0 );
        $candidates_count = (int) ( $kpis['candidates_count'] ?? 0 );
        $qualified_label = number_format_i18n( $qualified_count ) . ' / ' . number_format_i18n( $candidates_count );
        $cards_html  = self::render_cards_html( $items, $cv_map, $resume_map, $resume_map_by_id );
        $nonce       = wp_create_nonce( 'keoni_matching' );
        $reset_nonce = wp_create_nonce( 'keoni_bridge_reset_matching' );

        ob_start();
        ?>
        <div class="keoni-matching-wrapper">
        <section class="keoni-matching-kpis" aria-label="<?php echo esc_attr__( 'KPI workflow n8n', 'keoni-bridge' ); ?>">
            <div class="keoni-matching-kpis__grid">
                <article class="keoni-matching-kpis__item">
                    <span class="keoni-matching-kpis__label"><?php esc_html_e( 'Candidats analysés', 'keoni-bridge' ); ?></span>
                    <strong class="keoni-matching-kpis__value"><?php echo esc_html( number_format_i18n( (int) ( $kpis['candidates_count'] ?? 0 ) ) ); ?></strong>
                </article>
                <article class="keoni-matching-kpis__item">
                    <span class="keoni-matching-kpis__label"><?php esc_html_e( 'Score moyen', 'keoni-bridge' ); ?></span>
                    <strong class="keoni-matching-kpis__value"><?php echo esc_html( $avg_score_label ); ?></strong>
                </article>
                <article class="keoni-matching-kpis__item">
                    <span class="keoni-matching-kpis__label"><?php esc_html_e( 'Meilleur score', 'keoni-bridge' ); ?></span>
                    <strong class="keoni-matching-kpis__value"><?php echo esc_html( $best_score_label ); ?></strong>
                </article>
                <article class="keoni-matching-kpis__item">
                    <span class="keoni-matching-kpis__label"><?php esc_html_e( 'Durée exécution', 'keoni-bridge' ); ?></span>
                    <strong class="keoni-matching-kpis__value"><?php echo esc_html( $duration_label ); ?></strong>
                </article>
                <article class="keoni-matching-kpis__item">
                    <span class="keoni-matching-kpis__label"><?php esc_html_e( 'Candidats qualifiés', 'keoni-bridge' ); ?></span>
                    <strong class="keoni-matching-kpis__value"><?php echo esc_html( $qualified_label ); ?></strong>
                </article>
            </div>
        </section>
        <div class="keoni-matching__score-filter" data-keoni-score-filter>
            <label class="keoni-matching__score-filter-label" for="keoni-score-filter-<?php echo esc_attr( $job_id ); ?>"><?php esc_html_e( 'Score minimum', 'keoni-bridge' ); ?></label>
            <input type="range"
                   id="keoni-score-filter-<?php echo esc_attr( $job_id ); ?>"
                   min="0"
                   max="100"
                   step="1"
                   value="0"
                   data-keoni-score-slider />
            <span class="keoni-matching__score-filter-value" data-keoni-score-value>0</span>
            <span class="keoni-matching__score-filter-count" data-keoni-score-count></span>
        </div>
        <div class="keoni-matching">
            <?php echo $cards_html; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?>
            <div class="keoni-matching__empty keoni-matching__empty--filter" data-keoni-score-empty hidden><?php esc_html_e( 'Aucun candidat au-dessus de ce score.', 'keoni-bridge' ); ?></div>
        </div>
            <div class="keoni-matching__actions">
                <button type="button"
                        class="keoni-matching__btn keoni-matching__btn--ghost"
                        data-keoni-reset
                        data-job-id="<?php echo esc_attr( $job_id ); ?>"
                        data-nonce="<?php echo esc_attr( $reset_nonce ); ?>"
                        data-confirm-text="<?php esc_attr_e( 'Supprimer tous les résultats IA pour cette offre ?', 'keoni-bridge' ); ?>"
                        data-default-text="<?php esc_attr_e( 'Réinitialiser les résultats IA', 'keoni-bridge' ); ?>"
                        data-loading-text="<?php esc_attr_e( 'Réinitialisation...', 'keoni-bridge' ); ?>">
                    <?php esc_html_e( 'Réinitialiser les résultats IA', 'keoni-bridge' ); ?>
                </button>
                <?php if ( $has_more ) : ?>
                    <button type="button"
                            class="keoni-matching__btn keoni-matching__btn--ghost"
                            data-keoni-load-more
                            data-job-id="<?php echo esc_attr( $job_id ); ?>"
                            data-limit="<?php echo esc_attr( $limit ); ?>"
                            data-offset="<?php echo esc_attr( $offset ); ?>"
                            data-min-score="<?php echo esc_attr( $atts['min_score'] ); ?>"
                            data-nonce="<?php echo esc_attr( $nonce ); ?>"
                            data-default-text="<?php esc_attr_e( 'Afficher plus', 'keoni-bridge' ); ?>"
                            data-loading-text="<?php esc_attr_e( 'Chargement...', 'keoni-bridge' ); ?>">
                        <?php esc_html_e( 'Afficher plus', 'keoni-bridge' ); ?>
                    </button>
                <?php endif; ?>
            </div>
        </div>
        <?php
        return ob_get_clean();
    }

    public function register_assets(): void {
        $plugin_file = dirname( __DIR__ ) . '/keoni-bridge.php';
        $style_path  = dirname( __DIR__ ) . '/assets/css/keoni-matching.css';
        $script_path = dirname( __DIR__ ) . '/assets/js/keoni-matching.js';
        $style_url   = plugins_url( 'assets/css/keoni-matching.css', $plugin_file );
        $script_url  = plugins_url( 'assets/js/keoni-matching.js', $plugin_file );
        $style_ver   = file_exists( $style_path ) ? (string) filemtime( $style_path ) : KEONI_BRIDGE_VERSION;
        $script_ver  = file_exists( $script_path ) ? (string) filemtime( $script_path ) : KEONI_BRIDGE_VERSION;

        wp_register_style( $this->style_handle, $style_url, [], $style_ver );
        wp_register_script( $this->script_handle, $script_url, [], $script_ver, true );
        wp_localize_script( $this->script_handle, 'KeoniMatching', [
            'ajaxUrl' => admin_url( 'admin-ajax.php' ),
        ] );
    }

    public static function render_cards_html( array $items, array $cv_map, array $resume_map = [], array $resume_map_by_id = [] ): string {
        $default_avatar = defined( 'JSJOBS_PLUGIN_URL' ) ? JSJOBS_PLUGIN_URL . 'includes/images/users.png' : '';
        $date_format    = get_option( 'date_format', 'Y-m-d' );

        ob_start();

        foreach ( $items as $item ) {
            $cv_id       = (int) $item['cv_id'];
            $cv          = $cv_map[ $cv_id ] ?? [];
            $score       = floatval( $item['score'] );
            $score_class = self::get_score_class( $score );
            $keywords    = (array) ( $item['keywords'] ?? [] );
            $strengths   = (array) ( $item['strengths'] ?? [] );
            $weaknesses  = (array) ( $item['weaknesses'] ?? [] );
            $resume_url  = self::build_cv_url( $cv );
            $email_raw   = $cv['candidate_email'] ?? '';
            $resume_key  = strtolower( $email_raw );
            $resume      = $resume_key && isset( $resume_map[ $resume_key ] ) ? $resume_map[ $resume_key ] : null;

            if ( ! $resume && $cv_id && isset( $resume_map_by_id[ $cv_id ] ) ) {
                $resume = $resume_map_by_id[ $cv_id ];
            }

            $name = $resume
                ? trim( implode( ' ', array_filter( [ $resume['first_name'] ?? '', $resume['last_name'] ?? '' ] ) ) )
                : '';

            if ( '' === $name ) {
                $name = $cv['application_title'] ?? sprintf( __( 'Candidat #%d', 'keoni-bridge' ), $cv_id );
            }

            $job_type          = $resume['job_type'] ?? '';
            $application_title = $resume['application_title'] ?? ( $cv['application_title'] ?? '' );
            $category          = $resume['category'] ?? '';
            $experience        = $resume['experience'] ?? '';
            $salary            = $resume['salary'] ?? '';
            $location          = $resume['location'] ?? '';
            $photo             = $resume['photo_url'] ?? $default_avatar;
            $profile_url       = $resume['view_url'] ?? '';
            $created_at        = '';

            if ( ! empty( $resume['created_at'] ) ) {
                $timestamp  = strtotime( $resume['created_at'] );
                $created_at = $timestamp ? date_i18n( $date_format, $timestamp ) : '';
            }

            $rank_label = '';
            $rank_value = 0;
            if ( isset( $item['extra']['rank'] ) ) {
                $rank_value = (int) $item['extra']['rank'];
                $rank_label = sprintf( __( 'Rang #%d', 'keoni-bridge' ), $rank_value );
            }

            $score_percent = max( 0, min( 100, $score ) );
            $details_open  = ( 1 === $rank_value ) ? ' open' : '';
            ?>
            <article class="keoni-matching__card keoni-matching__card--resume" data-score="<?php echo esc_attr( number_format( $score, 2, '.', '' ) ); ?>">
                <div class="keoni-matching__body">
                    <div class="keoni-matching__top">
                        <div class="keoni-matching__avatar">
                            <img src="<?php echo esc_url( $photo ); ?>" alt="<?php echo esc_attr( $name ); ?>" />
                        </div>
                        <div class="keoni-matching__identity">
                            <h3 class="keoni-matching__resume-name"><?php echo esc_html( $name ); ?></h3>
                            <div class="keoni-matching__identity-badges">
                                <?php if ( $job_type ) : ?>
                                    <span class="keoni-matching__chip keoni-matching__chip--neutral"><?php echo esc_html( $job_type ); ?></span>
                                <?php endif; ?>
                                <?php if ( $rank_label ) : ?>
                                    <span class="keoni-matching__chip keoni-matching__chip--rank"><?php echo esc_html( $rank_label ); ?></span>
                                <?php endif; ?>
                            </div>
                        </div>
                        <div class="keoni-matching__score-panel">
                            <div class="keoni-matching__scoreline">
                                <span class="keoni-matching__score <?php echo esc_attr( $score_class ); ?>"><?php echo esc_html( number_format_i18n( $score, 1 ) ); ?></span>
                                <span class="keoni-matching__score-label"><?php esc_html_e( 'Score IA', 'keoni-bridge' ); ?></span>
                            </div>
                            <div class="keoni-matching__scorebar" aria-hidden="true">
                                <span class="<?php echo esc_attr( $score_class ); ?>" style="width:<?php echo esc_attr( number_format( $score_percent, 1, '.', '' ) ); ?>%"></span>
                            </div>
                        </div>
                    </div>

                    <div class="keoni-matching__resume-meta">
                        <?php if ( $application_title ) : ?>
                            <span class="keoni-matching__resume-meta-item">
                                <strong><?php esc_html_e( 'Titre', 'keoni-bridge' ); ?></strong>
                                <span><?php echo esc_html( $application_title ); ?></span>
                            </span>
                        <?php endif; ?>
                        <?php if ( $category ) : ?>
                            <span class="keoni-matching__resume-meta-item">
                                <strong><?php esc_html_e( 'Catégorie', 'keoni-bridge' ); ?></strong>
                                <span><?php echo esc_html( $category ); ?></span>
                            </span>
                        <?php endif; ?>
                        <?php if ( $experience ) : ?>
                            <span class="keoni-matching__resume-meta-item">
                                <strong><?php esc_html_e( 'Expérience', 'keoni-bridge' ); ?></strong>
                                <span><?php echo esc_html( $experience ); ?></span>
                            </span>
                        <?php endif; ?>
                        <?php if ( $created_at ) : ?>
                            <span class="keoni-matching__resume-meta-item">
                                <strong><?php esc_html_e( 'Créé le', 'keoni-bridge' ); ?></strong>
                                <span><?php echo esc_html( $created_at ); ?></span>
                            </span>
                        <?php endif; ?>
                    </div>

                    <details class="keoni-matching__details"<?php echo esc_attr( $details_open ); ?>>
                        <summary><?php esc_html_e( 'Voir détails', 'keoni-bridge' ); ?></summary>
                        <div class="keoni-matching__section-grid">
                            <div class="keoni-matching__section keoni-matching__section--strengths">
                                <strong><?php esc_html_e( 'POURQUOI CE MATCH', 'keoni-bridge' ); ?></strong>
                                <?php if ( ! empty( $strengths ) ) : ?>
                                    <ul class="keoni-matching__list">
                                        <?php foreach ( $strengths as $strength ) : ?>
                                            <li><?php echo esc_html( $strength ); ?></li>
                                        <?php endforeach; ?>
                                    </ul>
                                <?php else : ?>
                                    <p><?php esc_html_e( 'Aucune force détectée.', 'keoni-bridge' ); ?></p>
                                <?php endif; ?>
                            </div>
                            <div class="keoni-matching__section keoni-matching__section--weaknesses">
                                <strong><?php esc_html_e( 'Points de vigilance', 'keoni-bridge' ); ?></strong>
                                <?php if ( ! empty( $weaknesses ) ) : ?>
                                    <ul class="keoni-matching__list">
                                        <?php foreach ( $weaknesses as $weakness ) : ?>
                                            <li><?php echo esc_html( $weakness ); ?></li>
                                        <?php endforeach; ?>
                                    </ul>
                                <?php else : ?>
                                    <p><?php esc_html_e( 'Aucun signal particulier.', 'keoni-bridge' ); ?></p>
                                <?php endif; ?>
                            </div>
                        </div>

                        <div class="keoni-matching__section keoni-matching__section--keywords">
                            <strong><?php esc_html_e( 'Mots-clés', 'keoni-bridge' ); ?></strong>
                            <?php if ( empty( $keywords ) ) : ?>
                                <p class="keoni-matching__muted"><?php esc_html_e( 'Aucun mot-clé détecté.', 'keoni-bridge' ); ?></p>
                            <?php else : ?>
                                <div class="keoni-matching__resume-keywords">
                                    <?php foreach ( $keywords as $keyword ) : ?>
                                        <span><?php echo esc_html( $keyword ); ?></span>
                                    <?php endforeach; ?>
                                </div>
                            <?php endif; ?>
                        </div>
                    </details>

                    <div class="keoni-matching__resume-actions keoni-matching__actions">
                        <?php if ( $profile_url ) : ?>
                            <a class="keoni-matching__btn keoni-matching__btn--primary keoni-matching__btn--full" href="<?php echo esc_url( $profile_url ); ?>" target="_blank" rel="noopener">
                                <?php esc_html_e( 'Voir le CV', 'keoni-bridge' ); ?>
                            </a>
                        <?php endif; ?>
                        <div class="keoni-matching__actions-secondary">
                            <?php if ( $resume_url ) : ?>
                                <a class="keoni-matching__btn keoni-matching__btn--ghost" href="<?php echo esc_url( $resume_url ); ?>" target="_blank" rel="noopener">
                                    <?php esc_html_e( 'Télécharger le CV', 'keoni-bridge' ); ?>
                                </a>
                            <?php endif; ?>
                            <?php if ( $email_raw ) : ?>
                                <a class="keoni-matching__btn keoni-matching__btn--ghost" href="mailto:<?php echo esc_attr( $email_raw ); ?>">
                                    <?php esc_html_e( 'Envoyer un e-mail', 'keoni-bridge' ); ?>
                                </a>
                            <?php endif; ?>
                            <?php if ( $location ) : ?>
                                <span class="keoni-matching__chip keoni-matching__chip--neutral"><?php echo esc_html( $location ); ?></span>
                            <?php endif; ?>
                            <?php if ( $salary ) : ?>
                                <span class="keoni-matching__chip keoni-matching__chip--neutral"><?php echo esc_html( $salary ); ?></span>
                            <?php endif; ?>
                        </div>
                    </div>
                </div>
            </article>
            <?php
        }

        return ob_get_clean();
    }

    public function ajax_load_more(): void {
        check_ajax_referer( 'keoni_matching', 'nonce' );

        $job_id    = absint( wp_unslash( $_POST['job_id'] ?? 0 ) );
        $limit     = max( 1, absint( wp_unslash( $_POST['limit'] ?? 20 ) ) );
        $offset    = max( 0, absint( wp_unslash( $_POST['offset'] ?? 0 ) ) );
        $min_score = floatval( wp_unslash( $_POST['min_score'] ?? 0 ) );

        if ( 0 === $job_id ) {
            wp_send_json_error( [ 'message' => __( 'Job invalide.', 'keoni-bridge' ) ], 400 );
        }

        $results = Keoni_Bridge_Repository::get_matching_results( $job_id, $min_score, $limit, $offset );

        if ( empty( $results['items'] ) ) {
            $results['next_offset'] = min( $results['offset'], $results['total'] );
            $results['has_more']    = false;
            $results['html']        = '';
            wp_send_json_success( $results );
        }

        $cv_ids = wp_list_pluck( $results['items'], 'cv_id' );
        $cv_map = Keoni_Bridge_Repository::get_cvs_by_ids( $cv_ids );
        $emails = array_filter( array_map( static function ( $cv ) {
            return $cv['candidate_email'] ?? '';
        }, array_values( $cv_map ) ) );
        $resume_map           = Keoni_Bridge_Repository::get_resumes_by_emails( $emails );
        $resume_map_by_id     = Keoni_Bridge_Repository::get_resumes_by_ids( $cv_ids );
        $results['html']      = self::render_cards_html( $results['items'], $cv_map, $resume_map, $resume_map_by_id );
        $results['next_offset'] = min( $results['offset'] + $results['limit'], $results['total'] );
        $results['has_more']    = $results['next_offset'] < $results['total'];

        wp_send_json_success( $results );
    }

    private static function format_list( array $values ): string {
        $clean = array_filter( array_map( 'trim', $values ) );

        if ( empty( $clean ) ) {
            return __( 'Non renseigné', 'keoni-bridge' );
        }

        return implode( ', ', $clean );
    }

    private static function get_score_class( float $score ): string {
        if ( $score >= 80 ) {
            return 'score-high';
        }

        if ( $score >= 60 ) {
            return 'score-medium';
        }

        return 'score-low';
    }

    private static function format_duration_ms( $duration_ms ): string {
        if ( ! is_numeric( $duration_ms ) ) {
            return __( 'Non disponible', 'keoni-bridge' );
        }

        $duration = (int) $duration_ms;

        if ( $duration <= 0 ) {
            return __( 'Non disponible', 'keoni-bridge' );
        }

        if ( $duration < 1000 ) {
            return sprintf( __( '%d ms', 'keoni-bridge' ), $duration );
        }

        if ( $duration < 60000 ) {
            return sprintf( __( '%.1f s', 'keoni-bridge' ), $duration / 1000 );
        }

        $minutes = floor( $duration / 60000 );
        $seconds = floor( ( $duration % 60000 ) / 1000 );

        return sprintf( __( '%d min %d s', 'keoni-bridge' ), $minutes, $seconds );
    }

    private static function build_cv_url( array $cv ): string {
        $path = $cv['file_path'] ?? '';

        if ( empty( $path ) ) {
            return '';
        }

        if ( str_starts_with( $path, 'http://' ) || str_starts_with( $path, 'https://' ) ) {
            return esc_url_raw( $path );
        }

        if ( str_starts_with( $path, '/' ) ) {
            return esc_url_raw( home_url( $path ) );
        }

        $upload_dir = wp_get_upload_dir();

        return esc_url_raw( trailingslashit( $upload_dir['baseurl'] ) . ltrim( $path, '/' ) );
    }
}
