<?php
/**
 * Plugin Name:       Keoni Bridge
 * Plugin URI:        https://keoni-consulting.net
 * Description:       Pont d'intégration entre WordPress, n8n et le service de matching IA.
 * Version:           0.1.0
 * Author:            Chilavert N'Dah
 * Author URI:        https://keoni-consulting.net
 * License:           GPL-2.0-or-later
 * License URI:       https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain:       keoni-bridge
 * Domain Path:       /languages
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

const KEONI_BRIDGE_VERSION = '0.2.0';
const KEONI_BRIDGE_MIN_PHP = '8.0';

if ( version_compare( PHP_VERSION, KEONI_BRIDGE_MIN_PHP, '<' ) ) {
    add_action( 'admin_notices', static function () {
        echo '<div class="notice notice-error"><p>' . esc_html__( 'Keoni Bridge requiert PHP 8.0 ou supérieur.', 'keoni-bridge' ) . '</p></div>';
    } );
    return;
}

require_once __DIR__ . '/includes/class-keoni-bridge-install.php';
require_once __DIR__ . '/includes/class-keoni-bridge.php';

add_action( 'init', 'keoni_bridge_load_textdomain' );
add_action( 'plugins_loaded', [ 'Keoni_Bridge_Install', 'maybe_upgrade' ] );

function keoni_bridge_load_textdomain(): void {
    load_plugin_textdomain( 'keoni-bridge', false, dirname( plugin_basename( __FILE__ ) ) . '/languages' );
}

register_activation_hook( __FILE__, [ 'Keoni_Bridge_Install', 'activate' ] );
register_deactivation_hook( __FILE__, [ 'Keoni_Bridge_Install', 'deactivate' ] );
register_uninstall_hook( __FILE__, 'keoni_bridge_uninstall' );

function keoni_bridge_uninstall(): void {
    require_once __DIR__ . '/uninstall.php';
}

Keoni_Bridge::instance();
