<?php
/**
 * Shortcode Elementor/WordPress affichant les résultats.
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Keoni_Bridge_Shortcode {
    public function __construct() {
        add_shortcode( 'keoni_matching', [ $this, 'render' ] );
    }

    public function render( array $atts = [] ): string {
        $atts = shortcode_atts(
            [
                'job_id'    => 0,
                'limit'     => 20,
                'min_score' => 0,
            ],
            $atts,
            'keoni_matching'
        );

        $job_id = absint( $atts['job_id'] );

        if ( 0 === $job_id ) {
            return '<p>' . esc_html__( 'Aucun job_id fourni.', 'keoni-bridge' ) . '</p>';
        }

        $endpoint = rest_url( sprintf( 'keoni/v1/matching/%d', $job_id ) );
        $args     = [
            'timeout' => 15,
            'body'    => [
                'min_score' => $atts['min_score'],
                'limit'     => $atts['limit'],
            ],
        ];

        $response = wp_remote_get( add_query_arg( $args['body'], $endpoint ), [ 'timeout' => $args['timeout'] ] );

        if ( is_wp_error( $response ) ) {
            return '<p>' . esc_html__( 'Impossible de récupérer les résultats.', 'keoni-bridge' ) . '</p>';
        }

        $data = json_decode( wp_remote_retrieve_body( $response ), true );

        if ( empty( $data['items'] ) ) {
            return '<p>' . esc_html__( 'Aucun candidat correspondant.', 'keoni-bridge' ) . '</p>';
        }

        ob_start();
        ?>
        <div class="keoni-matching">
            <table>
                <thead>
                <tr>
                    <th><?php esc_html_e( 'Candidat', 'keoni-bridge' ); ?></th>
                    <th><?php esc_html_e( 'Score', 'keoni-bridge' ); ?></th>
                    <th><?php esc_html_e( 'Forces', 'keoni-bridge' ); ?></th>
                    <th><?php esc_html_e( 'Mots-clés', 'keoni-bridge' ); ?></th>
                </tr>
                </thead>
                <tbody>
                <?php foreach ( $data['items'] as $item ) : ?>
                    <tr>
                        <td>#<?php echo esc_html( $item['cv_id'] ); ?></td>
                        <td><strong><?php echo esc_html( $item['score'] ); ?></strong></td>
                        <td><?php echo esc_html( implode( ', ', (array) $item['strengths'] ) ); ?></td>
                        <td><?php echo esc_html( implode( ', ', (array) $item['keywords'] ) ); ?></td>
                    </tr>
                <?php endforeach; ?>
                </tbody>
            </table>
        </div>
        <?php
        return ob_get_clean();
    }
}
