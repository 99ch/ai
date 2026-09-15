<?php
/**
 * Désinstallation du plugin (suppression contrôlée des options).
 */

if ( ! defined( 'WP_UNINSTALL_PLUGIN' ) ) {
    exit;
}

$keep_data = apply_filters( 'keoni_bridge_keep_data_on_uninstall', true );

if ( ! $keep_data ) {
    global $wpdb;

    $wpdb->query( "DROP TABLE IF EXISTS {$wpdb->prefix}cv_database" );
    $wpdb->query( "DROP TABLE IF EXISTS {$wpdb->prefix}cv_matching_results" );
    $wpdb->query( "DROP TABLE IF EXISTS {$wpdb->prefix}keoni_job_scoring_settings" );
}

delete_option( 'keoni_bridge_version' );
delete_option( 'keoni_bridge_api_key' );
delete_option( 'keoni_bridge_settings' );
