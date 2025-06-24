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
        self.api_key = os.getenv('RIPE_ATLAS_API_KEY')
        if not self.api_key:
            raise ValueError("RIPE_ATLAS_API_KEY not found in environment variables")
        
        self.config_path = config_path
        self.create_config_path = create_config
        self.fetch_config_path = fetch_config
        self.results_dir = Path("measurement_client/results")
        self.created_measurements_dir = self.results_dir / "created_measurements"
        self.fetched_measurements_dir = self.results_dir / "fetched_measurements"
        
        self.create_config = None
        self.fetch_config = None
    
    def load_config(self, config_type="create"):
        config_path = None
        try:
            if config_type == "create":
                config_path = self.config_path or self.create_config_path
                if config_path is None:
                    raise ValueError("No configuration path provided for 'create' config")
                with open(config_path, 'r') as file:
                    self.create_config = yaml.safe_load(file)
            elif config_type == "fetch":
                config_path = self.config_path or self.fetch_config_path
                if config_path is None:
                    raise ValueError("No configuration path provided for 'fetch' config")
                with open(config_path, 'r') as file:
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
        logger.info("Creating measurements...")
        self.load_config("create")
        
        if not self.create_config:
            logger.error("No create configuration loaded. Please check your config file.")
            return

        for measurement_config in self.create_config.get('measurements', []):
            try:
                measurement_type = measurement_config.get('type', 'ping').lower()
                target = measurement_config.get('target')
                if not target:
                    logger.warning("No target specified for measurement. Skipping...")
                    continue
                probe_config = measurement_config.get('probes', {})

                if measurement_type == 'ping':
                    measurement = Ping(
                        af=measurement_config.get('af'),
                        target=target,
                        description=measurement_config.get('description', f'Sintra ping to {target}'),
                        interval=measurement_config.get('interval')
                    )
                elif measurement_type == 'traceroute':
                    traceroute_kwargs = {
                        "af": measurement_config.get('af'),
                        "target": target,
                        "description": measurement_config.get('description', f'Sintra traceroute to {target}'),
                        "interval": measurement_config.get('interval')
                    }
                    if 'protocol' in measurement_config:
                        traceroute_kwargs["protocol"] = measurement_config.get('protocol')
                    measurement = Traceroute(**traceroute_kwargs)
                else:
                    logger.error(f"Unsupported measurement type: {measurement_type}")
                    continue

                source = AtlasSource(
                    type="area",
                    value=probe_config.get('area', 'WW'),
                    requested=probe_config.get('count', 5)
                )

                start_time = datetime.utcnow() + timedelta(minutes=1)
                stop_time = start_time + timedelta(hours=measurement_config.get('duration_hours', 1)) # Default to 1 hour if not specified

                atlas_request = AtlasCreateRequest(
                    start_time=start_time,
                    stop_time=stop_time,
                    key=self.api_key,
                    measurements=[measurement],
                    sources=[source]
                )

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
    
    def fetch_measurements(self, measurement_id=None):
        logger.info("Fetching measurements...")
        self.created_measurements_dir.mkdir(parents=True, exist_ok=True)
        self.fetched_measurements_dir.mkdir(parents=True, exist_ok=True)
        
        if measurement_id:
            measurement_ids = [measurement_id]
        else:
            self.load_config("fetch")
            measurement_ids = []
            if self.fetch_config is not None:
                measurement_ids = self.fetch_config.get('measurement_ids', [])
            
            if not measurement_ids:
                measurement_ids = self._get_saved_measurement_ids()
        
        for measurement_id in measurement_ids:
            logger.info(f"Fetching ALL results for measurement {measurement_id}...")
            
            kwargs = {
                "msm_id": measurement_id,
                "format": "json"
            }
            
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
    
    def _save_measurement_info(self, measurement_id, config, target):
        info = {
            "measurement_id": measurement_id,
            "target": target,
            "type": config.get('type', 'ping'),
            "created_at": datetime.utcnow().isoformat(),
            "config": config
        }
        
        info_file = self.created_measurements_dir / f"measurement_{measurement_id}_info.json"
        with open(info_file, 'w') as f:
            json.dump(info, f, indent=2)
    
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
        
        for result in results:
            processed_result = {
                "probe_id": result.get("prb_id"),
                "source_address": result.get("from"),
                "target_address": result.get("dst_addr"),
                "timestamp": datetime.utcfromtimestamp(result.get("timestamp", 0)).isoformat() if result.get("timestamp") else None,
            }
            
            # Process based on measurement type
            if "result" in result and result.get("type") == "ping":
                processed_result.update(process_ping_result(result))
            elif "result" in result and result.get("type") == "traceroute":
                processed_result.update(process_traceroute_result(result))
            else:
                processed_result.update(process_default_result())
            
            processed["results"].append(processed_result)
        
        return processed
    
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
        
        ping_latencies = []
        ping_losses = []
        traceroute_hops = []
        
        for result in results:
            probe_id = result.get("probe_id")
            if probe_id:
                stats["probe_stats"]["unique_probes"].add(probe_id)
                stats["probe_stats"]["measurements_per_probe"][probe_id] = \
                    stats["probe_stats"]["measurements_per_probe"].get(probe_id, 0) + 1
            
            if result.get("measurement_type") == "ping" and result.get("latency_stats"):
                stats["ping_stats"]["total_measurements"] += 1
                if result["latency_stats"]["avg"]:
                    ping_latencies.append(result["latency_stats"]["avg"])
                    stats["ping_stats"]["min_latency"] = min(stats["ping_stats"]["min_latency"], 
                                                           result["latency_stats"]["min"])
                    stats["ping_stats"]["max_latency"] = max(stats["ping_stats"]["max_latency"], 
                                                           result["latency_stats"]["max"])
                
                ping_losses.append(result.get("packet_loss_percentage", 0))
            
            elif result.get("measurement_type") == "traceroute":
                stats["traceroute_stats"]["total_measurements"] += 1
                if result.get("hops_count"):
                    traceroute_hops.append(result["hops_count"])
        
        if ping_latencies:
            stats["ping_stats"]["avg_latency"] = sum(ping_latencies) / len(ping_latencies)
        if ping_losses:
            stats["ping_stats"]["avg_packet_loss"] = sum(ping_losses) / len(ping_losses)
        if traceroute_hops:
            stats["traceroute_stats"]["avg_hops"] = sum(traceroute_hops) / len(traceroute_hops)
        
        stats["probe_stats"]["unique_probes"] = list(stats["probe_stats"]["unique_probes"])
        
        return stats
    
    def _save_results(self, measurement_id, processed_results):
        results_file = self.fetched_measurements_dir / f"measurement_{measurement_id}_result.json"
        
        with open(results_file, 'w') as f:
            json.dump(processed_results, f, indent=2)

def main():
    parser = argparse.ArgumentParser(description='Sintra Measurement Client')
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    create_parser = subparsers.add_parser('create', help='Create measurements')
    create_parser.add_argument('--config', help='Configuration file path (overrides default)')
    
    fetch_parser = subparsers.add_parser('fetch', help='Fetch measurement results')
    fetch_parser.add_argument('--config', help='Configuration file path (overrides default)')
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
