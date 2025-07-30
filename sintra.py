import argparse
import sys
import json
import logging
from pathlib import Path
from measurement_client.client import SintraMeasurementClient
from measurement_client.logger import logger
from event_manager.eventmanager import SintraEventManager
from event_manager.anomaly_types import ANOMALY_TYPES


def setup_logging(log_level: str) -> None:
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f'Invalid log level: {log_level}')
    
    logging.getLogger().setLevel(numeric_level)
    logger.setLevel(numeric_level)


def create_parser():
    parser = argparse.ArgumentParser(
        prog="sintra",
        description='Sintra Network Measurement & Event Management Tool',
        epilog='Use "sintra <command> --help" for command-specific options.'
    )
    
    # Global options
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='Set logging level (default: INFO)'
    )
    
    subparsers = parser.add_subparsers(dest='command', required=True, help='Available commands')
    
    # Measurement commands
    create_parser = subparsers.add_parser('create', help='Create RIPE Atlas measurements')
    create_parser.add_argument(
        '--config', 
        default='measurement_client/create_config.yaml',
        help='Configuration file path (default: measurement_client/create_config.yaml)'
    )
    create_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate configuration without creating measurements'
    )
    
    fetch_parser = subparsers.add_parser('fetch', help='Fetch measurement results from RIPE Atlas')
    fetch_parser.add_argument(
        '--config', 
        default='measurement_client/fetch_config.yaml',
        help='Configuration file path (default: measurement_client/fetch_config.yaml)'
    )
    fetch_parser.add_argument(
        '--measurement-id', 
        type=int, 
        help='Specific measurement ID to fetch (overrides config file)'
    )
    fetch_parser.add_argument(
        '--all',
        action='store_true',
        help='Fetch all saved measurements (ignores config file measurement_ids)'
    )
    
    # Event management commands
    detect_parser = subparsers.add_parser('detect', help='Detect anomalies in measurement results')
    detect_parser.add_argument(
        '--config',
        default='event_manager/config.json',
        help='Event manager configuration file path (default: event_manager/config.json)'
    )
    
    # Alerts command
    for alert_cmd in ['alerts', 'alert']:
        alerts_parser = subparsers.add_parser(alert_cmd, help='Show summary of detected alerts')
        alerts_parser.add_argument(
            '--detailed',
            action='store_true',
            help='Show detailed alert information'
        )
        alerts_parser.add_argument(
            '--measurement-id',
            type=str,
            help='Show alerts for specific measurement ID only'
        )
    
    return parser

# This function handles the create measurements command
# It initializes the SintraMeasurementClient and creates measurements based on the provided configuration
def handle_create_command(args):
    try:
        logger.info("=== Creating RIPE Atlas Measurements ===")
        
        # Check if config file exists
        if not Path(args.config).exists():
            logger.error(f"Configuration file not found: {args.config}")
            logger.info("Please create the configuration file or check the path")
            return
        
        client = SintraMeasurementClient(config_path=args.config)
        
        if args.dry_run:
            logger.info("Dry-run mode: Validating configuration only")
            client.load_config("create")
            logger.info("Configuration validation successful")
            return
        
        client.create_measurements()
        logger.info("Measurement creation process completed")
        
    except Exception as e:
        logger.error(f"Failed to create measurements: {e}")
        raise

# This function handles the fetch measurements command
# It fetches measurement results based on the provided configuration or specific measurement ID
def handle_fetch_command(args):
    try:
        logger.info("=== Fetching Measurement Results ===")
        
        client = SintraMeasurementClient(config_path=args.config)
        
        if args.all:
            # Fetch all saved measurements, ignore config
            saved_ids = client._get_saved_measurement_ids()
            if saved_ids:
                logger.info(f"Fetching all {len(saved_ids)} saved measurements")
                for measurement_id in saved_ids:
                    client.fetch_measurements(measurement_id)
            else:
                logger.warning("No saved measurements found")
        elif args.measurement_id:
            # Fetch specific measurement ID
            client.fetch_measurements(args.measurement_id)
        else:
            # Use config file
            if not Path(args.config).exists():
                logger.error(f"Configuration file not found: {args.config}")
                logger.info("Please create the configuration file, use --measurement-id, or use --all")
                return
            client.fetch_measurements()
            
        logger.info("Fetch process completed")
        
    except Exception as e:
        logger.error(f"Failed to fetch measurements: {e}")
        raise

# This function handles the anomaly detection command
# It initializes the event manager and runs the analysis on fetched measurement results
def handle_detect_command(args):
    try:
        logger.info("=== Running Anomaly Detection ===")
        
        # Check if config file exists, create default if not
        config_path = args.config
        if not Path(config_path).exists():
            logger.warning(f"Configuration file not found: {config_path}")
            logger.info("Using default configuration")
            config_path = None
        
        # Initialize Event Manager
        event_manager = SintraEventManager(config_path=config_path)
        
        # Check if results directory exists and has files
        results_dir = Path("measurement_client/results/fetched_measurements")
        if not results_dir.exists():
            logger.error(f"Results directory does not exist: {results_dir}")
            logger.info("Please run 'sintra fetch' first to get measurement results")
            return
        
        result_files = list(results_dir.glob("measurement_*_result.json"))
        if not result_files:
            logger.warning(f"No measurement result files found in {results_dir}")
            logger.info("Please run 'sintra fetch' first to get measurement results")
            return
        
        logger.info(f"Found {len(result_files)} measurement result files to analyze")
        
        # Run analysis
        event_manager.analyze_all()
        
        logger.info("Anomaly detection complete. Results saved to: event_manager/results/")
        logger.info("Use 'sintra alerts' to view detected anomalies")
        
    except Exception as e:
        logger.error(f"Failed to run anomaly detection: {e}")
        raise

# This function handles the alerts command to show a summary of detected alerts
def handle_alerts_command(args):
    try:
        logger.info("=== Alerts Summary ===")
        
        events_dir = Path("event_manager/results")
        if not events_dir.exists():
            logger.error(f"Events directory does not exist: {events_dir}")
            logger.info("Please run 'sintra detect' first to generate events")
            return
        
        event_files = list(events_dir.glob("*.json"))
        if not event_files:
            logger.warning(f"No event files found in {events_dir}")
            logger.info("Please run 'sintra detect' first to generate events")
            return
        
        total_measurements = 0
        total_anomalies = 0
        global_anomaly_counts = {}
        
        for result_file in event_files:
            try:
                with open(result_file, "r") as f:
                    data = json.load(f)
                
                measurement_id = data.get("measurement_id")
                events = data.get("events", [])
                analysis = data.get("analysis", {})
                
                # Filter by measurement ID if specified
                if args.measurement_id and str(measurement_id) != args.measurement_id:
                    continue
                
                total_measurements += 1
                total_anomalies += len(events)
                
                logger.info(f"\nMeasurement {measurement_id}:")
                logger.info(f"  Total anomalies: {len(events)}")
                
                if analysis:
                    unique_probes = analysis.get("unique_probes_affected", 0)
                    logger.info(f"  Probes affected: {unique_probes}")
                
                # Show anomaly breakdown
                anomaly_summary = analysis.get("anomaly_summary", {})
                if anomaly_summary:
                    logger.info("  Anomaly breakdown:")
                    for anomaly, count in sorted(anomaly_summary.items()):
                        description = ANOMALY_TYPES.get(anomaly, {}).get("description", "Unknown")
                        logger.info(f"    {anomaly}: {count} events - {description}")
                        global_anomaly_counts[anomaly] = global_anomaly_counts.get(anomaly, 0) + count
                
                # Show detailed events if requested
                if args.detailed:
                    logger.info("  Detailed events:")
                    for i, event in enumerate(events[:5]):  # Show first 5 events
                        probe_id = event.get("probe_id")
                        target = event.get("target")
                        anomaly_type = event.get("anomaly")
                        value = event.get("value")
                        threshold = event.get("threshold")
                        severity = event.get("severity")
                        units = event.get("units", "")
                        
                        if units:
                            value_str = f"{value} {units}" if value is not None else "N/A"
                            threshold_str = f"{threshold} {units}" if threshold is not None else "N/A"
                        else:
                            value_str = str(value) if value is not None else "N/A"
                            threshold_str = str(threshold) if threshold is not None else "N/A"
                        
                        logger.info(f"    {i+1}. Probe {probe_id} -> {target}:")
                        logger.info(f"        Anomaly: {anomaly_type}")
                        logger.info(f"        Value: {value_str}, Threshold: {threshold_str}")
                        logger.info(f"        Severity: {severity}")
                        
                    if len(events) > 5:
                        logger.info(f"    ... and {len(events) - 5} more events")
                        
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Failed to read {result_file}: {e}")
        
        # Global summary (only if not filtering by measurement ID)
        if not args.measurement_id and total_measurements > 0:
            logger.info(f"\n=== Global Summary ===")
            logger.info(f"Total measurements analyzed: {total_measurements}")
            logger.info(f"Total anomalies detected: {total_anomalies}")
            
            if total_measurements > 0:
                logger.info(f"Average anomalies per measurement: {total_anomalies / total_measurements:.1f}")
            
            if global_anomaly_counts:
                logger.info("\nGlobal anomaly breakdown:")
                for anomaly, count in sorted(global_anomaly_counts.items(), key=lambda x: x[1], reverse=True):
                    description = ANOMALY_TYPES.get(anomaly, {}).get("description", "Unknown")
                    percentage = (count / total_anomalies) * 100 if total_anomalies > 0 else 0
                    logger.info(f"  {anomaly}: {count} events ({percentage:.1f}%) - {description}")
        elif args.measurement_id and total_measurements == 0:
            logger.info(f"No events found for measurement ID: {args.measurement_id}")
        
    except Exception as e:
        logger.error(f"Failed to show alerts: {e}")
        raise


# Main entry point for the Sintra
def main():
    parser = create_parser()
    args = parser.parse_args()
    
    # Set up logging
    try:
        setup_logging(args.log_level)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    
    logger.info(f"Sintra Network Management Tool - Command: {args.command}")
    
    try:
        if args.command == 'create':
            handle_create_command(args)
            
        elif args.command == 'fetch':
            handle_fetch_command(args)
        
        elif args.command == 'detect':
            handle_detect_command(args)

        elif args.command == 'alerts' or args.command == 'alert':
            handle_alerts_command(args)
            
        else:
            parser.print_help()
            sys.exit(1)
            
        logger.info("Command completed successfully")

    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Command failed: {e}")
        if args.log_level == 'DEBUG':
            logger.exception("Full traceback:")
        sys.exit(1)


if __name__ == "__main__":
    main()
