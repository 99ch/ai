<?php
/**
 * Page d'administration et réglages.
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Keoni_Bridge_Admin {
    private string $option_group = 'keoni_bridge_settings_group';
    private string $option_name  = 'keoni_bridge_settings';

    public function __construct() {
        add_action( 'admin_menu', [ $this, 'register_menu' ] );
        add_action( 'admin_init', [ $this, 'register_settings' ] );
    }

    public function register_menu(): void {
        add_options_page(
            __( 'Keoni Bridge', 'keoni-bridge' ),
            __( 'Keoni Bridge', 'keoni-bridge' ),
            'manage_options',
            'keoni-bridge',
            [ $this, 'render_page' ]
        );
    }

    public function register_settings(): void {
        register_setting( $this->option_group, $this->option_name, [ $this, 'sanitize_settings' ] );

        add_settings_section(
            'keoni_bridge_section_main',
            __( 'Configuration API', 'keoni-bridge' ),
            '__return_false',
            'keoni-bridge'
        );

        add_settings_field(
            'keoni_bridge_api_key',
            __( 'Clé API', 'keoni-bridge' ),
            [ $this, 'render_api_key_field' ],
            'keoni-bridge',
            'keoni_bridge_section_main'
        );

        add_settings_field(
            'keoni_bridge_webhook',
            __( 'Webhook n8n', 'keoni-bridge' ),
            [ $this, 'render_webhook_field' ],
            'keoni-bridge',
            'keoni_bridge_section_main'
        );

        add_settings_field(
            'keoni_bridge_matching',
            __( 'URL matching API', 'keoni-bridge' ),
            [ $this, 'render_matching_field' ],
            'keoni-bridge',
            'keoni_bridge_section_main'
        );
    }

    public function sanitize_settings( array $input ): array {
        $output = Keoni_Bridge::get_settings();

        if ( isset( $input['webhook_url'] ) ) {
            $output['webhook_url'] = esc_url_raw( $input['webhook_url'] );
        }

        if ( isset( $input['matching_url'] ) ) {
            $output['matching_url'] = esc_url_raw( $input['matching_url'] );
        }

        if ( ! empty( $input['regenerate_api_key'] ) ) {
            $new_key = $this->generate_api_key();
            update_option( 'keoni_bridge_api_key', wp_hash_password( $new_key ) );
            add_settings_error( 'keoni_bridge_api_key', 'keoni_bridge_api_key', __( 'Nouvelle clé générée.', 'keoni-bridge' ), 'updated' );
            $output['last_generated_key'] = $new_key;
        }

        return $output;
    }

    public function render_page(): void {
        if ( ! current_user_can( 'manage_options' ) ) {
            return;
        }

        $settings = Keoni_Bridge::get_settings();
        ?>
        <div class="wrap">
            <h1><?php esc_html_e( 'Keoni Bridge', 'keoni-bridge' ); ?></h1>
            <form method="post" action="options.php">
                <?php
                settings_fields( $this->option_group );
                do_settings_sections( 'keoni-bridge' );
                submit_button();
                ?>
                <p>
                    <button class="button" name="keoni_bridge_settings[regenerate_api_key]" value="1">
                        <?php esc_html_e( 'Régénérer la clé API', 'keoni-bridge' ); ?>
                    </button>
                </p>
                <?php if ( ! empty( $settings['last_generated_key'] ) ) : ?>
                    <p><strong><?php esc_html_e( 'Nouvelle clé (copiez-la maintenant) :', 'keoni-bridge' ); ?></strong><br>
                        <code><?php echo esc_html( $settings['last_generated_key'] ); ?></code></p>
                <?php endif; ?>
            </form>
        </div>
        <?php
    }

    public function render_api_key_field(): void {
        esc_html_e( 'Cliquez sur "Régénérer" pour obtenir une nouvelle clé.', 'keoni-bridge' );
    }

    public function render_webhook_field(): void {
        $settings = Keoni_Bridge::get_settings();
        printf(
            '<input type="url" name="%1$s[webhook_url]" value="%2$s" class="regular-text" placeholder="https://n8n.local/webhook/..." />',
            esc_attr( $this->option_name ),
            esc_attr( $settings['webhook_url'] )
        );
    }

    public function render_matching_field(): void {
        $settings = Keoni_Bridge::get_settings();
        printf(
            '<input type="url" name="%1$s[matching_url]" value="%2$s" class="regular-text" placeholder="https://matching.local/score" />',
            esc_attr( $this->option_name ),
            esc_attr( $settings['matching_url'] )
        );
    }

    private function generate_api_key(): string {
        $length = 64;

        do {
            $candidate = wp_generate_password( $length, true, true );
            $clean     = preg_replace( '/\s+/', '', $candidate );
        } while ( strlen( $clean ) < $length );

        return substr( $clean, 0, $length );
    }
}
