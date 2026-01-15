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
    private string $menu_slug    = 'keoni-bridge-dashboard';
    private string $cv_capability = 'manage_keoni_bridge_cv_db';

    public function __construct() {
        add_action( 'admin_menu', [ $this, 'register_menu' ] );
        add_action( 'admin_init', [ $this, 'register_settings' ] );
        add_action( 'init', [ $this, 'ensure_cv_capability_assignment' ] );
    }

    public function register_menu(): void {
        add_menu_page(
            __( 'Keoni Bridge', 'keoni-bridge' ),
            __( 'Keoni Bridge', 'keoni-bridge' ),
            'manage_options',
            $this->menu_slug,
            [ $this, 'render_page' ],
            'dashicons-networking',
            58
        );

        add_submenu_page(
            $this->menu_slug,
            __( 'Paramètres', 'keoni-bridge' ),
            __( 'Paramètres', 'keoni-bridge' ),
            'manage_options',
            $this->menu_slug,
            [ $this, 'render_page' ]
        );

        add_submenu_page(
            $this->menu_slug,
            __( 'CV Database', 'keoni-bridge' ),
            __( 'CV Database', 'keoni-bridge' ),
            $this->cv_capability,
            'keoni-bridge-cv-db',
            [ $this, 'render_cv_database_page' ]
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

        add_settings_field(
            'keoni_bridge_webhook_secret',
            __( 'Secret Webhook n8n', 'keoni-bridge' ),
            [ $this, 'render_webhook_secret_field' ],
            'keoni-bridge',
            'keoni_bridge_section_main'
        );

        add_settings_field(
            'keoni_bridge_cv_roles',
            __( 'Accès base CV', 'keoni-bridge' ),
            [ $this, 'render_cv_roles_field' ],
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

        if ( isset( $input['webhook_secret'] ) ) {
            $output['webhook_secret'] = sanitize_text_field( $input['webhook_secret'] );
        }

        $cv_roles = $this->sanitize_cv_roles_input( $input['cv_roles'] ?? null );
        $output['cv_roles'] = $cv_roles;
        $this->sync_cv_capability( $cv_roles );

        if ( ! empty( $input['regenerate_api_key'] ) ) {
            $new_key = $this->generate_api_key();
            update_option( 'keoni_bridge_api_key', wp_hash_password( $new_key ) );
            add_settings_error( 'keoni_bridge_api_key', 'keoni_bridge_api_key', __( 'Nouvelle clé générée.', 'keoni-bridge' ), 'updated' );
            $output['last_generated_key'] = $new_key;
        }

        if ( ! empty( $input['trigger_scan'] ) ) {
            do_action( 'keoni_bridge_scan_jobs' );
            add_settings_error( 'keoni_bridge_scan', 'keoni_bridge_scan', __( 'Scan des offres lancé.', 'keoni-bridge' ), 'updated' );
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
                    <button class="button" name="keoni_bridge_settings[trigger_scan]" value="1">
                        <?php esc_html_e( 'Scanner les nouvelles offres maintenant', 'keoni-bridge' ); ?>
                    </button>
                </p>
                <?php if ( ! empty( $settings['last_generated_key'] ) ) : ?>
                    <p><strong><?php esc_html_e( 'Nouvelle clé (copiez-la maintenant) :', 'keoni-bridge' ); ?></strong><br>
                        <code><?php echo esc_html( $settings['last_generated_key'] ); ?></code></p>
                <?php endif; ?>
                <p>
                    <?php
                    $last_scan = get_option( 'keoni_bridge_last_job_scan', 0 );
                    if ( $last_scan ) {
                        printf(
                            '<em>' . esc_html__( 'Dernier scan : %s', 'keoni-bridge' ) . '</em>',
                            esc_html( wp_date( 'Y-m-d H:i:s', $last_scan ) )
                        );
                    } else {
                        esc_html_e( 'Aucun scan effectué pour le moment.', 'keoni-bridge' );
                    }
                    ?>
                </p>
            </form>
        </div>
        <?php
    }

    public function render_cv_database_page(): void {
        if ( ! current_user_can( $this->cv_capability ) ) {
            return;
        }

        $this->maybe_handle_cv_update();

        $action = isset( $_GET['action'] ) ? sanitize_key( wp_unslash( $_GET['action'] ) ) : 'list';
        $cv_id  = isset( $_GET['cv_id'] ) ? absint( $_GET['cv_id'] ) : 0;
        ?>
        <div class="wrap">
            <h1><?php esc_html_e( 'CV Database', 'keoni-bridge' ); ?></h1>
            <?php settings_errors( 'keoni_bridge_cv' ); ?>
            <?php
            if ( 'edit' === $action && $cv_id ) {
                $this->render_cv_edit_view( $cv_id );
            } else {
                $this->render_cv_list_view();
            }
            ?>
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

    public function render_webhook_secret_field(): void {
        $settings = Keoni_Bridge::get_settings();
        printf(
            '<input type="text" name="%1$s[webhook_secret]" value="%2$s" class="regular-text" placeholder="secret-n8n" />',
            esc_attr( $this->option_name ),
            esc_attr( $settings['webhook_secret'] )
        );
        echo '<p class="description">' . esc_html__( 'Le même secret que celui attendu par le workflow n8n.', 'keoni-bridge' ) . '</p>';
    }

    public function render_cv_roles_field(): void {
        $settings = Keoni_Bridge::get_settings();
        $selected = (array) ( $settings['cv_roles'] ?? [ 'administrator' ] );
        $roles    = get_editable_roles();

        echo '<fieldset>';
        foreach ( $roles as $role_slug => $role_data ) {
            $checked = in_array( $role_slug, $selected, true ) ? 'checked="checked"' : '';
            printf(
                '<label><input type="checkbox" name="%1$s[cv_roles][]" value="%2$s" %3$s %4$s/> %5$s</label><br />',
                esc_attr( $this->option_name ),
                esc_attr( $role_slug ),
                $checked,
                'administrator' === $role_slug ? 'disabled="disabled"' : '',
                esc_html( $role_data['name'] )
            );
        }
        echo '<p class="description">' . esc_html__( 'Sélectionnez les rôles autorisés à consulter/éditer les CV. Les administrateurs y ont toujours accès.', 'keoni-bridge' ) . '</p>';
        echo '</fieldset>';
    }

    private function render_cv_list_view(): void {
        $search       = isset( $_GET['s'] ) ? sanitize_text_field( wp_unslash( $_GET['s'] ) ) : '';
        $paged        = isset( $_GET['paged'] ) ? max( 1, (int) $_GET['paged'] ) : 1;
        $status       = isset( $_GET['status'] ) ? sanitize_text_field( wp_unslash( $_GET['status'] ) ) : '';
        $updated_from = isset( $_GET['updated_from'] ) ? sanitize_text_field( wp_unslash( $_GET['updated_from'] ) ) : '';
        $updated_to   = isset( $_GET['updated_to'] ) ? sanitize_text_field( wp_unslash( $_GET['updated_to'] ) ) : '';

        $results = Keoni_Bridge_Repository::list_cvs(
            [
                'search'       => $search,
                'paged'        => $paged,
                'status'       => $status,
                'updated_from' => $updated_from,
                'updated_to'   => $updated_to,
            ]
        );

        $items       = $results['items'];
        $total       = $results['total'];
        $per_page    = $results['per_page'];
        $total_pages = max( 1, (int) ceil( $total / $per_page ) );

        $base_url = add_query_arg(
            [
                'page'         => 'keoni-bridge-cv-db',
                's'            => $search,
                'status'       => $status,
                'updated_from' => $updated_from,
                'updated_to'   => $updated_to,
            ],
            admin_url( 'admin.php' )
        );

        $pagination = paginate_links(
            [
                'base'      => add_query_arg( 'paged', '%#%', $base_url ),
                'format'    => '',
                'current'   => $results['paged'],
                'total'     => $total_pages,
                'prev_text' => '&laquo;',
                'next_text' => '&raquo;',
                'type'      => 'array',
            ]
        );
        ?>
        <form method="get" class="keoni-bridge-cv-filters">
            <input type="hidden" name="page" value="keoni-bridge-cv-db" />
            <p class="search-box">
                <label class="screen-reader-text" for="keoni-bridge-cv-search"><?php esc_html_e( 'Rechercher des CV', 'keoni-bridge' ); ?></label>
                <input type="search" id="keoni-bridge-cv-search" name="s" value="<?php echo esc_attr( $search ); ?>" placeholder="<?php esc_attr_e( 'Email ou titre', 'keoni-bridge' ); ?>" />
                <label for="keoni-bridge-cv-status" class="screen-reader-text"><?php esc_html_e( 'Statut', 'keoni-bridge' ); ?></label>
                <input type="text" id="keoni-bridge-cv-status" name="status" value="<?php echo esc_attr( $status ); ?>" placeholder="<?php esc_attr_e( 'Statut (ex: validé)', 'keoni-bridge' ); ?>" />
                <label for="keoni-bridge-cv-date-from"><?php esc_html_e( 'Du', 'keoni-bridge' ); ?></label>
                <input type="date" id="keoni-bridge-cv-date-from" name="updated_from" value="<?php echo esc_attr( $updated_from ); ?>" />
                <label for="keoni-bridge-cv-date-to"><?php esc_html_e( 'Au', 'keoni-bridge' ); ?></label>
                <input type="date" id="keoni-bridge-cv-date-to" name="updated_to" value="<?php echo esc_attr( $updated_to ); ?>" />
                <button type="submit" class="button"><?php esc_html_e( 'Filtrer', 'keoni-bridge' ); ?></button>
            </p>
        </form>

        <table class="widefat fixed striped">
            <thead>
            <tr>
                <th><?php esc_html_e( 'ID', 'keoni-bridge' ); ?></th>
                <th><?php esc_html_e( 'Email candidat', 'keoni-bridge' ); ?></th>
                <th><?php esc_html_e( 'Titre de candidature', 'keoni-bridge' ); ?></th>
                <th><?php esc_html_e( 'Fichier', 'keoni-bridge' ); ?></th>
                <th><?php esc_html_e( 'Mise à jour', 'keoni-bridge' ); ?></th>
                <th><?php esc_html_e( 'Actions', 'keoni-bridge' ); ?></th>
            </tr>
            </thead>
            <tbody>
            <?php if ( empty( $items ) ) : ?>
                <tr>
                    <td colspan="6"><?php esc_html_e( 'Aucun CV enregistré.', 'keoni-bridge' ); ?></td>
                </tr>
            <?php else : ?>
                <?php foreach ( $items as $item ) :
                    $edit_url = add_query_arg(
                        [
                            'page'   => 'keoni-bridge-cv-db',
                            'action' => 'edit',
                            'cv_id'  => (int) $item['id'],
                        ],
                        admin_url( 'admin.php' )
                    );
                    ?>
                    <tr>
                        <td><?php echo esc_html( $item['id'] ); ?></td>
                        <td><?php echo esc_html( $item['candidate_email'] ); ?></td>
                        <td><?php echo esc_html( $item['application_title'] ); ?></td>
                        <td><?php echo esc_html( $item['file_name'] ); ?></td>
                        <td><?php echo esc_html( $item['updated_at'] ); ?></td>
                        <td><a class="button button-small" href="<?php echo esc_url( $edit_url ); ?>"><?php esc_html_e( 'Voir / éditer', 'keoni-bridge' ); ?></a></td>
                    </tr>
                <?php endforeach; ?>
            <?php endif; ?>
            </tbody>
        </table>

        <?php if ( ! empty( $pagination ) ) : ?>
            <div class="tablenav">
                <div class="tablenav-pages">
                    <?php foreach ( $pagination as $link ) { echo wp_kses_post( $link ); } ?>
                </div>
            </div>
        <?php endif; ?>
        <?php
    }

    private function render_cv_edit_view( int $cv_id ): void {
        $cv = Keoni_Bridge_Repository::get_cv( $cv_id );

        if ( ! $cv ) {
            echo '<p>' . esc_html__( 'CV introuvable.', 'keoni-bridge' ) . '</p>';
            return;
        }

        $metadata = ! empty( $cv['metadata'] ) ? wp_json_encode( $cv['metadata'], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES ) : '';
        $list_url = add_query_arg( [ 'page' => 'keoni-bridge-cv-db' ], admin_url( 'admin.php' ) );
        ?>
        <p><a class="button" href="<?php echo esc_url( $list_url ); ?>">&larr; <?php esc_html_e( 'Retour à la liste', 'keoni-bridge' ); ?></a></p>
        <form method="post">
            <?php wp_nonce_field( 'keoni_bridge_save_cv', 'keoni_bridge_cv_nonce' ); ?>
            <input type="hidden" name="keoni_bridge_cv_action" value="save" />
            <input type="hidden" name="cv_id" value="<?php echo esc_attr( $cv_id ); ?>" />

            <table class="form-table" role="presentation">
                <tr>
                    <th scope="row"><label for="keoni-candidate-email"><?php esc_html_e( 'Email candidat', 'keoni-bridge' ); ?></label></th>
                    <td><input type="email" class="regular-text" id="keoni-candidate-email" name="candidate_email" value="<?php echo esc_attr( $cv['candidate_email'] ); ?>" required /></td>
                </tr>
                <tr>
                    <th scope="row"><label for="keoni-application-title"><?php esc_html_e( 'Titre de candidature', 'keoni-bridge' ); ?></label></th>
                    <td><input type="text" class="regular-text" id="keoni-application-title" name="application_title" value="<?php echo esc_attr( $cv['application_title'] ); ?>" /></td>
                </tr>
                <tr>
                    <th scope="row"><?php esc_html_e( 'Fichier source', 'keoni-bridge' ); ?></th>
                    <td><code><?php echo esc_html( $cv['file_name'] ); ?></code></td>
                </tr>
                <tr>
                    <th scope="row"><label for="keoni-text-content"><?php esc_html_e( 'Contenu texte extrait', 'keoni-bridge' ); ?></label></th>
                    <td>
                        <textarea id="keoni-text-content" name="text_content" rows="10" class="large-text code"><?php echo esc_textarea( $cv['text_content'] ); ?></textarea>
                        <p class="description"><?php esc_html_e( 'Corrigez ou enrichissez le texte avant scoring.', 'keoni-bridge' ); ?></p>
                    </td>
                </tr>
                <tr>
                    <th scope="row"><label for="keoni-metadata"><?php esc_html_e( 'Métadonnées (JSON)', 'keoni-bridge' ); ?></label></th>
                    <td>
                        <textarea id="keoni-metadata" name="metadata" rows="8" class="large-text code"><?php echo esc_textarea( (string) $metadata ); ?></textarea>
                        <p class="description"><?php esc_html_e( 'Collez un objet JSON valide (compétences, tags, etc.).', 'keoni-bridge' ); ?></p>
                    </td>
                </tr>
            </table>

            <?php submit_button( __( 'Enregistrer le CV', 'keoni-bridge' ) ); ?>
        </form>
        <?php
    }

    private function maybe_handle_cv_update(): void {
        if ( empty( $_POST['keoni_bridge_cv_action'] ) || 'save' !== $_POST['keoni_bridge_cv_action'] ) {
            return;
        }

        if ( ! current_user_can( $this->cv_capability ) ) {
            return;
        }

        check_admin_referer( 'keoni_bridge_save_cv', 'keoni_bridge_cv_nonce' );

        $cv_id = isset( $_POST['cv_id'] ) ? absint( $_POST['cv_id'] ) : 0;

        if ( $cv_id <= 0 || ! Keoni_Bridge_Repository::get_cv( $cv_id ) ) {
            add_settings_error( 'keoni_bridge_cv', 'keoni_bridge_cv_missing', __( 'CV introuvable.', 'keoni-bridge' ), 'error' );
            return;
        }

        $email = sanitize_email( wp_unslash( $_POST['candidate_email'] ?? '' ) );

        if ( empty( $email ) ) {
            add_settings_error( 'keoni_bridge_cv', 'keoni_bridge_cv_email', __( 'Email invalide.', 'keoni-bridge' ), 'error' );
            return;
        }

        $application_title = sanitize_text_field( wp_unslash( $_POST['application_title'] ?? '' ) );
        $text_content      = wp_kses_post( wp_unslash( $_POST['text_content'] ?? '' ) );
        $metadata_raw      = wp_unslash( $_POST['metadata'] ?? '' );
        $metadata          = [];

        if ( '' !== trim( $metadata_raw ) ) {
            $decoded = json_decode( $metadata_raw, true );
            if ( JSON_ERROR_NONE !== json_last_error() || ! is_array( $decoded ) ) {
                add_settings_error( 'keoni_bridge_cv', 'keoni_bridge_cv_metadata', __( 'Métadonnées JSON invalides.', 'keoni-bridge' ), 'error' );
                return;
            }
            $metadata = $decoded;
        }

        $updated = Keoni_Bridge_Repository::update_cv(
            $cv_id,
            [
                'candidate_email'   => $email,
                'application_title' => $application_title,
                'text_content'      => $text_content,
                'metadata'          => $metadata,
            ]
        );

        if ( $updated ) {
            add_settings_error( 'keoni_bridge_cv', 'keoni_bridge_cv_saved', __( 'CV mis à jour.', 'keoni-bridge' ), 'updated' );
        } else {
            add_settings_error( 'keoni_bridge_cv', 'keoni_bridge_cv_failed', __( 'Impossible d\'enregistrer le CV.', 'keoni-bridge' ), 'error' );
        }
    }

    private function generate_api_key(): string {
        $length = 64;

        do {
            $candidate = wp_generate_password( $length, true, true );
            $clean     = preg_replace( '/\s+/', '', $candidate );
        } while ( strlen( $clean ) < $length );

        return substr( $clean, 0, $length );
    }

    public function ensure_cv_capability_assignment(): void {
        $this->ensure_role_helpers_loaded();
        $settings  = Keoni_Bridge::get_settings();
        $cv_roles  = (array) ( $settings['cv_roles'] ?? [ 'administrator' ] );
        $this->sync_cv_capability( $cv_roles );
    }

    private function sanitize_cv_roles_input( $raw ): array {
        $this->ensure_role_helpers_loaded();
        $editable_roles = array_keys( get_editable_roles() );
        $selected       = [];

        if ( is_array( $raw ) ) {
            foreach ( $raw as $role_slug ) {
                $role_slug = sanitize_key( $role_slug );
                if ( in_array( $role_slug, $editable_roles, true ) ) {
                    $selected[] = $role_slug;
                }
            }
        }

        if ( ! in_array( 'administrator', $selected, true ) ) {
            $selected[] = 'administrator';
        }

        return array_values( array_unique( $selected ) );
    }

    private function sync_cv_capability( array $roles ): void {
        $this->ensure_role_helpers_loaded();
        $roles = array_unique( array_map( 'sanitize_key', $roles ) );
        $editable_roles = get_editable_roles();

        foreach ( $editable_roles as $role_slug => $data ) {
            $role = get_role( $role_slug );

            if ( ! $role ) {
                continue;
            }

            if ( in_array( $role_slug, $roles, true ) ) {
                if ( ! $role->has_cap( $this->cv_capability ) ) {
                    $role->add_cap( $this->cv_capability );
                }
            } else {
                if ( $role->has_cap( $this->cv_capability ) ) {
                    $role->remove_cap( $this->cv_capability );
                }
            }
        }
    }

    private function ensure_role_helpers_loaded(): void {
        if ( function_exists( 'get_editable_roles' ) ) {
            return;
        }

        require_once ABSPATH . 'wp-admin/includes/user.php';
    }
}
