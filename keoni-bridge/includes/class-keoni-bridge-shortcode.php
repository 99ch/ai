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

        $items      = $data['items'];
        $cv_map     = Keoni_Bridge_Repository::get_cvs_by_ids( wp_list_pluck( $items, 'cv_id' ) );
        $total      = intval( $data['total'] ?? count( $items ) );
        $limit      = intval( $data['limit'] ?? $atts['limit'] );
        $offset     = intval( $data['offset'] ?? $atts['offset'] );
        $has_more   = ( $offset + $limit ) < $total;
        $cards_html = self::render_cards_html( $items, $cv_map );
        $nonce      = wp_create_nonce( 'keoni_matching' );

        ob_start();
        ?>
        <div class="keoni-matching-wrapper">
        <div class="keoni-matching">
            <?php echo $cards_html; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?>
        </div>
            <?php if ( $has_more ) : ?>
                <div class="keoni-matching__actions">
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
                </div>
            <?php endif; ?>
        </div>
        <?php
        return ob_get_clean();
    }

    public function register_assets(): void {
        $plugin_file = dirname( __DIR__ ) . '/keoni-bridge.php';
        $style_url   = plugins_url( 'assets/css/keoni-matching.css', $plugin_file );
        $script_url  = plugins_url( 'assets/js/keoni-matching.js', $plugin_file );

        wp_register_style( $this->style_handle, $style_url, [], KEONI_BRIDGE_VERSION );
        wp_register_script( $this->script_handle, $script_url, [], KEONI_BRIDGE_VERSION, true );
        wp_localize_script( $this->script_handle, 'KeoniMatching', [
            'ajaxUrl' => admin_url( 'admin-ajax.php' ),
        ] );
    }

    public static function render_cards_html( array $items, array $cv_map ): string {
        ob_start();

        foreach ( $items as $item ) {
            $cv_id       = (int) $item['cv_id'];
            $cv          = $cv_map[ $cv_id ] ?? null;
            $score       = floatval( $item['score'] );
            $score_class = self::get_score_class( $score );
            $name        = $cv['application_title'] ?? sprintf( __( 'Candidat #%d', 'keoni-bridge' ), $cv_id );
            $email       = $cv['candidate_email'] ?? '';
            $keywords    = (array) ( $item['keywords'] ?? [] );
            $strengths   = (array) ( $item['strengths'] ?? [] );
            $weaknesses  = (array) ( $item['weaknesses'] ?? [] );
            $resume_url  = $cv ? self::build_cv_url( $cv ) : '';
            ?>
            <article class="keoni-matching__card">
                <header class="keoni-matching__header">
                    <h3 class="keoni-matching__name"><?php echo esc_html( $name ); ?></h3>
                    <span class="keoni-matching__score <?php echo esc_attr( $score_class ); ?>">
                        <?php echo esc_html( number_format_i18n( $score, 1 ) ); ?>
                    </span>
                </header>
                <div class="keoni-matching__meta">
                    <span>#<?php echo esc_html( $cv_id ); ?></span>
                    <?php if ( $email ) : ?>
                        <span><?php echo esc_html( $email ); ?></span>
                    <?php endif; ?>
                </div>
                <div class="keoni-matching__section">
                    <strong><?php esc_html_e( 'Forces', 'keoni-bridge' ); ?></strong>
                    <p><?php echo esc_html( self::format_list( $strengths ) ); ?></p>
                </div>
                <?php if ( ! empty( $weaknesses ) ) : ?>
                    <div class="keoni-matching__section">
                        <strong><?php esc_html_e( 'Points de vigilance', 'keoni-bridge' ); ?></strong>
                        <p><?php echo esc_html( self::format_list( $weaknesses ) ); ?></p>
                    </div>
                <?php endif; ?>
                <div class="keoni-matching__section">
                    <strong><?php esc_html_e( 'Mots-clés', 'keoni-bridge' ); ?></strong>
                    <div class="keoni-matching__keywords">
                        <?php if ( empty( $keywords ) ) : ?>
                            <span><?php esc_html_e( 'Aucun', 'keoni-bridge' ); ?></span>
                        <?php else : ?>
                            <?php foreach ( $keywords as $keyword ) : ?>
                                <span class="keoni-matching__keyword"><?php echo esc_html( $keyword ); ?></span>
                            <?php endforeach; ?>
                        <?php endif; ?>
                    </div>
                </div>
                <footer class="keoni-matching__actions">
                    <?php if ( $email ) : ?>
                        <a class="keoni-matching__btn keoni-matching__btn--primary" href="mailto:<?php echo esc_attr( $email ); ?>">
                            <?php esc_html_e( 'Contacter', 'keoni-bridge' ); ?>
                        </a>
                    <?php endif; ?>
                    <?php if ( $resume_url ) : ?>
                        <a class="keoni-matching__btn keoni-matching__btn--ghost" href="<?php echo esc_url( $resume_url ); ?>" target="_blank" rel="noopener">
                            <?php esc_html_e( 'Voir le CV', 'keoni-bridge' ); ?>
                        </a>
                    <?php endif; ?>
                </footer>
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

        $cv_map = Keoni_Bridge_Repository::get_cvs_by_ids( wp_list_pluck( $results['items'], 'cv_id' ) );
        $results['html']     = self::render_cards_html( $results['items'], $cv_map );
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
