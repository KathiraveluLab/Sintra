import os
import json
import yaml
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from ripe.atlas.cousteau import (
    Ping, Traceroute, AtlasCreateRequest, AtlasResultsRequest,
    AtlasSource
)
from measurement_client.logger import logger
from measurement_client.processors import (
    process_ping_result, process_traceroute_result, 
    process_default_result
)

class SintraMeasurementClient:
    def __init__(self, config_path=None, create_config="measurement_client/create_config.yaml", fetch_config="measurement_client/fetch_config.yaml"):
        load_dotenv()

        # RIPE Atlas API Key
        # Ensure the API key is set in the environment variables
        self.api_key = os.getenv('RIPE_ATLAS_API_KEY')
        if not self.api_key:
            raise ValueError("RIPE_ATLAS_API_KEY not found in environment variables")
        
        # Configuration paths for creating and fetching measurements
        self.config_path = config_path

        # This path was the measurement_client/create_config.yaml
        self.create_config_path = create_config
        # This path was the measurement_client/fetch_config.yaml
        self.fetch_config_path = fetch_config

        # The results will be stored in these directories
        self.results_dir = Path("measurement_client/results")
        self.created_measurements_dir = self.results_dir / "created_measurements"
        self.fetched_measurements_dir = self.results_dir / "fetched_measurements"
        
        self.create_config = None
        self.fetch_config = None
    
    # This method for creating measurements by loading the configuration
    # from the specified path and processing each measurement configuration.
    def load_config(self, config_type="create"):
        config_path = None
        try:
            if config_type == "create":
                config_path = self.config_path or self.create_config_path
                if config_path is None:
                    raise ValueError("No configuration path provided for 'create' config")
                with open(config_path, 'r') as file:
                    #read the YAML configuration file
                    # and load it into the create_config attribute
                    self.create_config = yaml.safe_load(file)
            elif config_type == "fetch":
                # This is for fetching measurements
                # It will load the fetch configuration from the specified path
                config_path = self.config_path or self.fetch_config_path
                if config_path is None:
                    raise ValueError("No configuration path provided for 'fetch' config")
                with open(config_path, 'r') as file:
                    #read the YAML configuration file
                    # and load it into the fetch_config attribute
                    self.fetch_config = yaml.safe_load(file)
            else:
                config_path = self.config_path
                if config_path is None:
                    raise ValueError("No configuration path provided")
                with open(config_path, 'r') as file:
                    self.config = yaml.safe_load(file)
        except FileNotFoundError:
            raise FileNotFoundError(f"Configuration file {config_path} not found")
    
    def create_measurements(self):
        # This method creates measurements based on the loaded configuration.
        # It processes each measurement configuration, creates the measurement,
        logger.info("Creating measurements...")
        self.load_config("create")
        
        if not self.create_config:
            logger.error("No create configuration loaded. Please check your config file.")
            return

        for measurement_config in self.create_config.get('measurements', []):
            try:
                # Extract measurement type, target, and probe configuration
                # Ensure that the measurement type is specified and valid
                measurement_type = measurement_config.get('type', 'ping').lower()
                target = measurement_config.get('target')
                if not target:
                    logger.warning("No target specified for measurement. Skipping...")
                    continue
                # Support both area and country-based probe selection
                # If 'probes' is not specified, default to an empty dict
                probe_config = measurement_config.get('probes', {})

                # Create the measurement based on the type
                if measurement_type == 'ping':
                    measurement = Ping(
                        # Use the 'af' (address family) from the ping config
                        # If not specified, it will default to IPv4 (4)
                        af=measurement_config.get('af'),
                        target=target,
                        description=measurement_config.get('description', f'Sintra ping to {target}'),
                        interval=measurement_config.get('interval')
                    )
                elif measurement_type == 'traceroute':
                    traceroute_kwargs = {
                        # Use the 'af' (address family) from the traceroute config
                        "af": measurement_config.get('af'),
                        "target": target,
                        "description": measurement_config.get('description', f'Sintra traceroute to {target}'),
                        "interval": measurement_config.get('interval')
                    }
                    if 'protocol' in measurement_config:
                        # If 'protocol' is specified, use it
                        # Otherwise, it will default to 'ICMP'
                        traceroute_kwargs["protocol"] = measurement_config.get('protocol')
                    measurement = Traceroute(**traceroute_kwargs)
                else:
                    logger.error(f"Unsupported measurement type: {measurement_type}")
                    continue

                # Support both area and country-based probe selection
                probe_config = measurement_config.get('probes', {})
                if 'country' in probe_config and 'area' in probe_config:
                    raise ValueError("Both 'country' and 'area' cannot be specified in probes config; please use one or the other.")
                if 'country' in probe_config:
                    source = AtlasSource(
                        type="country",
                        value=probe_config.get('country'),
                        requested=probe_config.get('count', 5)
                    )
                else:
                    # Default to area if 'country' is not specified
                    # This will use the 'area' field if available, or default to 'WW'
                    # If 'count' is not specified, default to 5
                    source = AtlasSource(
                        type="area",
                        value=probe_config.get('area', 'WW'),
                        requested=probe_config.get('count', 5)
                    )

                # Set the start and stop times for the measurement
                # Default to starting 1 minute from now and lasting for 1 hour
                start_time = datetime.utcnow() + timedelta(minutes=1)
                # If 'duration_hours' is specified in the measurement config,
                # use it to calculate the stop time
                stop_time = start_time + timedelta(hours=measurement_config.get('duration_hours', 1)) # Default to 1 hour if not specified


                # Create the Atlas request for measurement creation
                # This will use the start and stop times, API key, measurement, and source
                # The AtlasCreateRequest will handle the actual API call to create the measurement
                # This will return a success flag and the response from the API

                atlas_request = AtlasCreateRequest(
                    start_time=start_time,
                    stop_time=stop_time,
                    key=self.api_key,
                    measurements=[measurement],
                    sources=[source]
                )
                
                # Create the measurement using the Atlas API
                is_success, response = atlas_request.create()

                if is_success:
                    try:
                        if isinstance(response, dict) and "measurements" in response:
                            measurement_id = response["measurements"][0]
                        else:
                            measurement_id = response[0][0]
                        logger.info(f"Created {measurement_type} measurement {measurement_id} for {target}")
                        logger.debug(f"Measurement response: {response}")
                        self._save_measurement_info(measurement_id, measurement_config, target)
                    except Exception as e:
                        logger.error(f"Measurement created for {target}, but failed to extract measurement ID: {e}, response: {response}")
                else:
                    logger.error(f"Failed to create measurement for {target}: {response}")
            except Exception as e:
                logger.exception(f"Error creating measurement for {measurement_config.get('target', 'unknown')}: {e}")
    
    # This method fetches measurements based on the provided measurement ID
    # If no measurement ID is provided, it will load the fetch configuration
    # and fetch all measurements specified in the configuration or saved measurements.
    def fetch_measurements(self, measurement_id=None):
        logger.info("Fetching measurements...")
        self.created_measurements_dir.mkdir(parents=True, exist_ok=True)
        self.fetched_measurements_dir.mkdir(parents=True, exist_ok=True)
        
        if measurement_id:
            measurement_ids = [measurement_id]
        else:
            # If no measurement ID is provided, load the fetch configuration
            # and get the measurement IDs from the configuration or saved measurements
            self.load_config("fetch")
            measurement_ids = []
            if self.fetch_config is not None:
                measurement_ids = self.fetch_config.get('measurement_ids', [])
            
            if not measurement_ids:
                measurement_ids = self._get_saved_measurement_ids()
        
        for measurement_id in measurement_ids:
            logger.info(f"Fetching ALL results for measurement {measurement_id}...")
            
            # Prepare the request parameters for fetching results
            kwargs = {
                "msm_id": measurement_id,
                "format": "json"
            }
            
            # If fetch_config is provided, use it to set the start and stop times
            # and any other fetch settings
            # This will allow for more flexible fetching of results
            if hasattr(self, 'fetch_config') and self.fetch_config:
                fetch_settings = self.fetch_config.get('fetch_settings', {})
                
                if 'start_time' in fetch_settings:
                    kwargs['start'] = fetch_settings['start_time']
                if 'stop_time' in fetch_settings:
                    kwargs['stop'] = fetch_settings['stop_time']
                if 'probe_ids' in fetch_settings:
                    kwargs['probe_ids'] = fetch_settings['probe_ids']
            
            is_success, results = AtlasResultsRequest(**kwargs).create()
            
            if is_success:
                logger.info(f"Retrieved {len(results)} results for measurement {measurement_id}")
                processed_results = self._process_all_results(results, measurement_id)
                self._save_results(measurement_id, processed_results)
                logger.info(f"Saved ALL results for measurement {measurement_id}")
            else:
                logger.error(f"Failed to fetch results for measurement {measurement_id}")
    
    # This method saves the measurement information to a JSON file
    # It includes the measurement ID, target, type, created_at timestamp, and configuration.
    def _save_measurement_info(self, measurement_id, config, target):
        info = {
            "measurement_id": measurement_id,
            "target": target,
            "type": config.get('type', 'ping'),
            "created_at": datetime.utcnow().isoformat(),
            "config": config
        }
        
        # Ensure the created_measurements_dir exists
        info_file = self.created_measurements_dir / f"measurement_{measurement_id}_info.json"
        with open(info_file, 'w') as f:
            json.dump(info, f, indent=2)
    
    # This method retrieves the saved measurement IDs from the created_measurements_dir
    # It looks for files named "measurement_*_info.json" and extracts the measurement_id
    def _get_saved_measurement_ids(self):
        measurement_ids = []
        if self.created_measurements_dir.exists():
            for info_file in self.created_measurements_dir.glob("measurement_*_info.json"):
                try:
                    with open(info_file, 'r') as f:
                        info = json.load(f)
                        measurement_ids.append(info['measurement_id'])
                except json.JSONDecodeError:
                    continue
        return measurement_ids
    
    # This method processes the results fetched from the RIPE Atlas API
    # It takes the results and measurement_id as input and returns a processed dictionary
    def _process_results(self, results, measurement_id):
        processed = {
            "measurement_id": measurement_id,
            "fetched_at": datetime.utcnow().isoformat(),
            "results_count": len(results),
            "results": []
        }
        
        for result in results:
            processed_result = {
                "probe_id": result.get("prb_id"),
                "timestamp": result.get("timestamp"),
                "from": result.get("from"),
                "target": result.get("dst_name"),
            }
            
            if "result" in result:
                ping_results = result["result"]
                rtts = [r.get("rtt") for r in ping_results if r.get("rtt")]
                processed_result.update({
                    "packet_loss": len([r for r in ping_results if r.get("x")]) / len(ping_results) * 100,
                    "avg_latency": sum(rtts) / len(rtts) if rtts else None,
                    "min_latency": min(rtts) if rtts else None,
                    "max_latency": max(rtts) if rtts else None,
                    "packets_sent": len(ping_results),
                    "packets_received": len(rtts)
                })
            
            if "result" in result and any("hop" in str(result).lower() for r in result.get("result", [])):
                processed_result["traceroute_hops"] = result.get("result", [])
            
            processed["results"].append(processed_result)
        
        return processed
    
    # This method processes all results fetched from the RIPE Atlas API
    # It takes the results and measurement_id as input and returns a processed dictionary
    def _process_all_results(self, results, measurement_id):
        processed = {
            "measurement_id": measurement_id,
            "fetched_at": datetime.utcnow().isoformat(),
            "results_count": len(results),
            "summary": {
                "total_probes": len(set(result.get("prb_id") for result in results)),
                "total_results": len(results),
                "time_range": {
                    "start": min(result.get("timestamp", 0) for result in results) if results else None,
                    "end": max(result.get("timestamp", 0) for result in results) if results else None
                }
            },
            "results": []
        }

        probe_results = {}
        for result in results:
            probe_id = result.get("prb_id")
            measurement_type = result.get("type")
            if probe_id not in probe_results:
                probe_results[probe_id] = {
                    "measurement_type": measurement_type,
                    "measurement_id": measurement_id,
                    "probe_id": probe_id,
                    "source_address": result.get("from"),
                    "target_address": result.get("dst_addr"),
                    "target_name": result.get("dst_name"),
                    "timestamp": datetime.utcfromtimestamp(result.get("timestamp", 0)).isoformat() if result.get("timestamp") else None,
                    "firmware_version": result.get("fw"),
                    "probe_asn": result.get("from_asn"),
                    "probe_country": result.get("country_code"),
                    "protocol": result.get("proto", "ICMP"),
                    "address_family": result.get("af", 4)
                }
                # Initialize aggregation fields
                if measurement_type == "ping":
                    probe_results[probe_id].update({
                        "latency_stats": {"rtts": [], "avg": None, "min": None, "max": None},
                        "packet_loss_percentage": None,
                        "packets_sent": 0,
                        "packets_received": 0
                    })
                elif measurement_type == "traceroute":
                    probe_results[probe_id].update({
                        "hops": [],
                        "hops_count": 0
                    })

            # Aggregate ping results
            if measurement_type == "ping" and "result" in result:
                ping_results = result["result"]
                rtts = [r.get("rtt") for r in ping_results if r.get("rtt") is not None]
                probe_results[probe_id]["latency_stats"]["rtts"].extend(rtts)
                probe_results[probe_id]["packets_sent"] += len(ping_results)
                probe_results[probe_id]["packets_received"] += len(rtts)
                loss_count = len([r for r in ping_results if r.get("x")])
                # Calculate packet loss percentage for this batch
                if probe_results[probe_id]["packets_sent"] > 0:
                    probe_results[probe_id]["packet_loss_percentage"] = (
                        loss_count / probe_results[probe_id]["packets_sent"] * 100
                    )
            # Aggregate traceroute results
            elif measurement_type == "traceroute" and "result" in result:
                hops = result.get("result", [])
                probe_results[probe_id]["hops"] = hops
                probe_results[probe_id]["hops_count"] = len(hops)

        # Finalize latency stats for ping
        for probe_id, res in probe_results.items():
            if res.get("measurement_type") == "ping":
                rtts = res["latency_stats"]["rtts"]
                if rtts:
                    res["latency_stats"]["avg"] = sum(rtts) / len(rtts)
                    res["latency_stats"]["min"] = min(rtts)
                    res["latency_stats"]["max"] = max(rtts)
                else:
                    res["latency_stats"]["avg"] = None
                    res["latency_stats"]["min"] = None
                    res["latency_stats"]["max"] = None

        processed["results"] = list(probe_results.values())
        return processed
    
    # This method analyzes the traceroute path and returns a summary of the hops
    # It takes the hops as input and returns a dictionary with hop details.
    def _analyze_traceroute_path(self, hops):
        path_analysis = {
            "total_hops": len(hops),
            "responding_hops": 0,
            "non_responding_hops": 0,
            "unique_ips": set(),
            "hop_details": []
        }
        
        for hop in hops:
            hop_info = {
                "hop_number": hop.get("hop"),
                "responses": hop.get("result", [])
            }
            
            has_response = False
            for response in hop.get("result", []):
                if response.get("from"):
                    has_response = True
                    path_analysis["unique_ips"].add(response.get("from"))
            
            if has_response:
                path_analysis["responding_hops"] += 1
            else:
                path_analysis["non_responding_hops"] += 1
            
            path_analysis["hop_details"].append(hop_info)
        
        path_analysis["unique_ips"] = list(path_analysis["unique_ips"])
        return path_analysis
    
    # This method calculates aggregated statistics from the results
    # It computes average packet loss, average latency, min/max latency for ping,
    # average hops for traceroute, and unique probes.
    # It returns a dictionary with the aggregated statistics.
    def _calculate_aggregated_stats(self, results):
        stats = {
            "ping_stats": {
                "total_measurements": 0,
                "avg_packet_loss": 0,
                "avg_latency": 0,
                "min_latency": float('inf'),
                "max_latency": 0
            },
            "traceroute_stats": {
                "total_measurements": 0,
                "avg_hops": 0,
                "unique_paths": 0
            },
            "probe_stats": {
                "unique_probes": set(),
                "measurements_per_probe": {}
            }
        }
        
        ping_count = 0
        ping_latency_sum = 0
        ping_loss_sum = 0
        traceroute_count = 0
        traceroute_hops_sum = 0
        min_latency = float('inf')
        max_latency = 0
        
        for result in results:
            probe_id = result.get("probe_id")
            if probe_id:
                # Track unique probes and measurements per probe
                stats["probe_stats"]["unique_probes"].add(probe_id)
                # Track measurements per probe
                stats["probe_stats"]["measurements_per_probe"][probe_id] = \
                    stats["probe_stats"]["measurements_per_probe"].get(probe_id, 0) + 1
            
            if result.get("measurement_type") == "ping" and result.get("latency_stats"):
                ping_count += 1
                latency_stats = result["latency_stats"]
                
                if latency_stats["avg"]:
                    ping_latency_sum += latency_stats["avg"]
                    min_latency = min(min_latency, latency_stats["min"])
                    max_latency = max(max_latency, latency_stats["max"])
                
                ping_loss_sum += result.get("packet_loss_percentage", 0)
                
            elif result.get("measurement_type") == "traceroute":
                traceroute_count += 1
                if result.get("hops_count"):
                    traceroute_hops_sum += result["hops_count"]
        
        # Calculate final averages
        if ping_count > 0:
            stats["ping_stats"]["total_measurements"] = ping_count
            stats["ping_stats"]["avg_latency"] = ping_latency_sum / ping_count
            stats["ping_stats"]["avg_packet_loss"] = ping_loss_sum / ping_count
            stats["ping_stats"]["min_latency"] = min_latency if min_latency != float('inf') else 0
            stats["ping_stats"]["max_latency"] = max_latency
        
        if traceroute_count > 0:
            stats["traceroute_stats"]["total_measurements"] = traceroute_count
            stats["traceroute_stats"]["avg_hops"] = traceroute_hops_sum / traceroute_count
        
        stats["probe_stats"]["unique_probes"] = list(stats["probe_stats"]["unique_probes"])
        
        return stats
    
    def _save_results(self, measurement_id, processed_results):
        results_file = self.fetched_measurements_dir / f"measurement_{measurement_id}_result.json"
        
        with open(results_file, 'w') as f:
            json.dump(processed_results, f, indent=2)

def main():
    # This is the main entry point for the Sintra Measurement Client
    # It sets up the argument parser, loads the configuration, and executes the appropriate command.
    parser = argparse.ArgumentParser(description='Sintra Measurement Client')
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Create subparsers for 'create' and 'fetch' commands
    # Each command can have its own configuration file path
    create_parser = subparsers.add_parser('create', help='Create measurements')
    # This will allow for more flexible creation of measurements
    # It will use the create_config_path by default, or a custom config if provided
    create_parser.add_argument('--config', help='Configuration file path (overrides default)')
    
    # This will fetch measurement results
    # It can fetch all results or a specific measurement ID
    fetch_parser = subparsers.add_parser('fetch', help='Fetch measurement results')
    # It can fetch all results or a specific measurement ID
    # If no measurement ID is provided, it will fetch all results
    fetch_parser.add_argument('--config', help='Configuration file path (overrides default)')
    # If no measurement ID is provided, it will fetch all results
    # If a measurement ID is provided, it will fetch results for that specific measurement
    fetch_parser.add_argument('--measurement-id', type=int, help='Specific measurement ID to fetch')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return

    try:
        client = SintraMeasurementClient(config_path=args.config)
        if args.command == 'create':
            client.create_measurements()
        elif args.command == 'fetch':
            client.fetch_measurements(args.measurement_id)

    except Exception as e:
        logger.error(f"Error: {e}")

if __name__ == "__main__":
    main()
