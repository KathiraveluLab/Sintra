import os
import json
import yaml
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
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
from collections import defaultdict
from statistics import mean, median
import requests

class SintraMeasurementClient:
    def __init__(self, config_path=None, create_config="measurement_client/create_config.yaml", fetch_config="measurement_client/fetch_config.yaml"):
        # Initialize the Sintra Measurement Client.
        try:
            load_dotenv()

            # RIPE Atlas API Key validation
            self.api_key = os.getenv('RIPE_ATLAS_API_KEY')
            if not self.api_key:
                raise ValueError("RIPE_ATLAS_API_KEY not found in environment variables")
            
            # RIPE Atlas API base URL
            self.base_url = "https://atlas.ripe.net/api/v2"
            
            # Configuration paths
            self.config_path = config_path
            self.create_config_path = create_config
            self.fetch_config_path = fetch_config

            # Results directories
            self.results_dir = Path("measurement_client/results")
            self.created_measurements_dir = self.results_dir / "created_measurements"
            self.fetched_measurements_dir = self.results_dir / "fetched_measurements"
            
            # Ensure directories exists or not
            self._ensure_directories()
            
            self.create_config = None
            self.fetch_config = None
            
            logger.info("SintraMeasurementClient initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize SintraMeasurementClient: {e}")
            raise

    def _ensure_directories(self) -> None:
        try:
            self.results_dir.mkdir(parents=True, exist_ok=True)
            self.created_measurements_dir.mkdir(parents=True, exist_ok=True)
            self.fetched_measurements_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create directories: {e}")
            raise

    def load_config(self, config_type="create"):
        config_path = None
        try:
            if config_type == "create":
                config_path = self.config_path or self.create_config_path
                if not config_path:
                    raise ValueError("No configuration path provided for 'create' config")
                
                if not Path(config_path).exists():
                    raise FileNotFoundError(f"Create configuration file {config_path} not found")
                
                with open(config_path, 'r') as file:
                    self.create_config = yaml.safe_load(file)
                
                # Validate create configuration
                self._validate_create_config()
                
            elif config_type == "fetch":
                config_path = self.config_path or self.fetch_config_path
                if not config_path:
                    raise ValueError("No configuration path provided for 'fetch' config")
                
                if not Path(config_path).exists():
                    raise FileNotFoundError(f"Fetch configuration file {config_path} not found")
                
                with open(config_path, 'r') as file:
                    self.fetch_config = yaml.safe_load(file)
                
                # Validate fetch configuration
                self._validate_fetch_config()
            else:
                raise ValueError(f"Invalid config_type: {config_type}")
                
            logger.info(f"Configuration loaded successfully from {config_path}")
            
        except (yaml.YAMLError, IOError) as e:
            logger.error(f"Failed to load configuration from {config_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error loading configuration: {e}")
            raise

    def _validate_create_config(self) -> None:
        if not self.create_config:
            raise ValueError("Create configuration is empty")
        
        measurements = self.create_config.get('measurements', [])
        if not measurements:
            raise ValueError("No measurements defined in create configuration")
        
        for i, measurement in enumerate(measurements):
            # Validate required fields
            if 'target' not in measurement:
                raise ValueError(f"Measurement {i}: 'target' field is required")
            
            measurement_type = measurement.get('type', 'ping').lower()
            if measurement_type not in ['ping', 'traceroute']:
                raise ValueError(f"Measurement {i}: Invalid type '{measurement_type}'. Must be 'ping' or 'traceroute'")
            
            # Validate probes configuration
            probes = measurement.get('probes', {})
            if 'country' in probes and 'area' in probes:
                raise ValueError(f"Measurement {i}: Cannot specify both 'country' and 'area' in probes")
            
            logger.debug(f"Measurement {i} validation passed")

    def _validate_fetch_config(self) -> None:
        if not self.fetch_config:
            raise ValueError("Fetch configuration is empty")
        
        measurement_ids = self.fetch_config.get('measurement_ids', [])
        if not measurement_ids:
            logger.warning("No measurement_ids defined in fetch configuration")
        
        for measurement_id in measurement_ids:
            if not isinstance(measurement_id, int):
                raise ValueError(f"Invalid measurement_id: {measurement_id}. Must be an integer")

    # This method creates measurements based on the loaded configuration.
    # It processes each measurement configuration, creates the measurement,
    logger.info("Creating measurements...")
    def create_measurements(self):
        logger.info("Creating measurements...")
        
        try:
            self.load_config("create")
        except Exception as e:
            logger.error(f"Failed to load create configuration: {e}")
            return

        if not self.create_config:
            logger.error("No create configuration loaded. Please check your config file.")
            return

        measurements = self.create_config.get('measurements', [])
        successful_count = 0
        failed_count = 0

        for i, measurement_config in enumerate(measurements):
            try:
                success = self._create_single_measurement(measurement_config, i)
                if success:
                    successful_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                failed_count += 1
                target = measurement_config.get('target', 'unknown')
                logger.exception(f"Error creating measurement for {target}: {e}")

        logger.info(f"Measurement creation complete: {successful_count} successful, {failed_count} failed")

    def _create_single_measurement(self, measurement_config: Dict[str, Any], index: int) -> bool:
        try:
            # Extract and validate measurement parameters
            measurement_type = measurement_config.get('type', 'ping').lower()
            target = measurement_config.get('target')
            
            if not target:
                logger.warning(f"Measurement {index}: No target specified. Skipping...")
                return False
            
            # Create the measurement object
            measurement = self._create_measurement_object(measurement_config, measurement_type, target)
            if not measurement:
                return False
            
            # Create source configuration
            source = self._create_source_configuration(measurement_config)
            if not source:
                return False
            
            # Set timing parameters
            start_time = datetime.utcnow() + timedelta(minutes=1)
            duration_hours = measurement_config.get('duration_hours', 1)
            stop_time = start_time + timedelta(hours=duration_hours)

            # Create the Atlas request
            atlas_request = AtlasCreateRequest(
                start_time=start_time,
                stop_time=stop_time,
                key=self.api_key,
                measurements=[measurement],
                sources=[source]
            )
            
            # Execute the measurement creation
            is_success, response = atlas_request.create()

            if is_success:
                measurement_id = self._extract_measurement_id(response)
                if measurement_id:
                    logger.info(f"Created {measurement_type} measurement {measurement_id} for {target}")
                    self._save_measurement_info(measurement_id, measurement_config, target)
                    return True
                else:
                    logger.error(f"Measurement created for {target}, but failed to extract measurement ID")
                    return False
            else:
                logger.error(f"Failed to create measurement for {target}: {response}")
                return False
                
        except Exception as e:
            logger.error(f"Exception in _create_single_measurement: {e}")
            return False

    def _create_measurement_object(self, config: Dict[str, Any], measurement_type: str, target: str):
        try:
            if measurement_type == 'ping':
                return Ping(
                    af=config.get('af'),
                    target=target,
                    description=config.get('description', f'Sintra ping to {target}'),
                    interval=config.get('interval')
                )
            elif measurement_type == 'traceroute':
                traceroute_kwargs = {
                    "af": config.get('af'),
                    "target": target,
                    "description": config.get('description', f'Sintra traceroute to {target}'),
                    "interval": config.get('interval')
                }
                
                if 'protocol' in config:
                    protocol = config.get('protocol', 'ICMP').upper()
                    if protocol in ['ICMP', 'TCP', 'UDP']:
                        traceroute_kwargs["protocol"] = protocol
                    else:
                        logger.warning(f"Invalid protocol {protocol}, using ICMP")
                        
                return Traceroute(**traceroute_kwargs)
            else:
                logger.error(f"Unsupported measurement type: {measurement_type}")
                return None
        except Exception as e:
            logger.error(f"Failed to create measurement object: {e}")
            return None

    def _create_source_configuration(self, config: Dict[str, Any]):
        try:
            probe_config = config.get('probes', {})
            
            if 'country' in probe_config and 'area' in probe_config:
                raise ValueError("Both 'country' and 'area' cannot be specified in probes config")
            
            if 'country' in probe_config:
                return AtlasSource(
                    type="country",
                    value=probe_config.get('country'),
                    requested=probe_config.get('count', 5)
                )
            else:
                return AtlasSource(
                    type="area",
                    value=probe_config.get('area', 'WW'),
                    requested=probe_config.get('count', 5)
                )
        except Exception as e:
            logger.error(f"Failed to create source configuration: {e}")
            return None

    def _extract_measurement_id(self, response):
        try:
            if isinstance(response, dict) and "measurements" in response:
                return response["measurements"][0]
            elif isinstance(response, list) and len(response) > 0:
                return response[0][0] if isinstance(response[0], list) else response[0]
            else:
                logger.warning(f"Unexpected response format: {response}")
                return None
        except (IndexError, KeyError, TypeError) as e:
            logger.error(f"Failed to extract measurement ID from response: {e}")
            return None

    # This method fetches measurements based on the provided measurement ID
    # If no measurement ID is provided, it will load the fetch configuration
    # and fetch all measurements specified in the configuration or saved measurements.
    def fetch_measurements(self, measurement_id=None):
        logger.info("Fetching measurements...")
        
        try:
            self._ensure_directories()
            
            if measurement_id:
                measurement_ids = [measurement_id]
                logger.info(f"Fetching specific measurement: {measurement_id}")
            else:
                # Load fetch configuration and get measurement IDs
                try:
                    self.load_config("fetch")
                    measurement_ids = []
                    if self.fetch_config is not None:
                        measurement_ids = self.fetch_config.get('measurement_ids', [])
                    
                    if not measurement_ids:
                        measurement_ids = self._get_saved_measurement_ids()
                        logger.info(f"Using saved measurement IDs: {len(measurement_ids)} found")
                    else:
                        logger.info(f"Using configuration measurement IDs: {len(measurement_ids)} found")
                        
                except Exception as e:
                    logger.warning(f"Failed to load fetch config: {e}. Trying saved measurements...")
                    measurement_ids = self._get_saved_measurement_ids()
            
            if not measurement_ids:
                logger.warning("No measurement IDs found to fetch")
                return
            
            successful_count = 0
            failed_count = 0
            
            for measurement_id in measurement_ids:
                try:
                    success = self._fetch_single_measurement(measurement_id)
                    if success:
                        successful_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Failed to fetch measurement {measurement_id}: {e}")
            
            logger.info(f"Fetch complete: {successful_count} successful, {failed_count} failed")
            
        except Exception as e:
            logger.error(f"Error in fetch_measurements: {e}")
            raise

    def _fetch_single_measurement(self, measurement_id: int) -> bool:
        try:
            logger.info(f"Fetching results for measurement {measurement_id}...")
            
            # Get measurement info first to understand the type
            measurement_info = self._get_measurement_info(measurement_id)
            if not measurement_info:
                logger.error(f"Could not get measurement info for {measurement_id}")
                return False
            
            # Prepare the request parameters for fetching results
            kwargs = {
                "msm_id": measurement_id,
                "format": "json"
            }
            
            # Apply fetch settings if available
            if hasattr(self, 'fetch_config') and self.fetch_config:
                fetch_settings = self.fetch_config.get('fetch_settings', {})
                
                if 'start_time' in fetch_settings:
                    kwargs['start'] = fetch_settings['start_time']
                if 'stop_time' in fetch_settings:
                    kwargs['stop'] = fetch_settings['stop_time']
                if 'probe_ids' in fetch_settings:
                    kwargs['probe_ids'] = fetch_settings['probe_ids']
            
            # Execute the fetch request
            is_success, results = AtlasResultsRequest(**kwargs).create()
            
            if is_success:
                if not results:
                    logger.warning(f"No results returned for measurement {measurement_id}")
                    return False
                
                logger.info(f"Retrieved {len(results)} raw results for measurement {measurement_id}")
                
                # Process results with regional information
                processed_results = self._process_all_results_with_regions(results, measurement_id, measurement_info)
                self._save_results(measurement_id, processed_results)
                logger.info(f"Saved results with regional analysis for measurement {measurement_id}")
                return True
            else:
                logger.error(f"Failed to fetch results for measurement {measurement_id}: {results}")
                return False
                
        except Exception as e:
            logger.error(f"Exception fetching measurement {measurement_id}: {e}")
            return False

    def _get_measurement_info(self, measurement_id: int) -> Optional[Dict[str, Any]]:
        """Get measurement information from RIPE Atlas API."""
        try:
            measurement_url = f"{self.base_url}/measurements/{measurement_id}/"
            response = requests.get(measurement_url)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error getting measurement info for {measurement_id}: {e}")
            return None

    def _process_all_results_with_regions(self, results, measurement_id, measurement_info):
        """Process results with enhanced regional information and analysis."""
        processed = {
            "measurement_id": measurement_id,
            "measurement_type": measurement_info.get("type"),
            "target": measurement_info.get("target"),
            "description": measurement_info.get("description"),
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
            "results": [],
            "regional_analysis": {}
        }

        # Get unique probe IDs and fetch their information in batches
        probe_ids = list(set(result.get("prb_id") for result in results if result.get("prb_id")))
        logger.info(f"Fetching regional information for {len(probe_ids)} unique probes...")
        
        probe_info_cache = self._batch_fetch_probe_info(probe_ids)
        
        # Process individual results with regional information
        probe_results = {}
        regional_data = defaultdict(list)
        
        for result in results:
            probe_id = result.get("prb_id")
            measurement_type = measurement_info.get("type")
            
            if probe_id not in probe_results:
                probe_info = probe_info_cache.get(probe_id, {})
                country = probe_info.get("country", "Unknown")
                country_code = probe_info.get("country_code")
                
                probe_results[probe_id] = {
                    "measurement_type": measurement_type,
                    "measurement_id": measurement_id,
                    "probe_id": probe_id,
                    "probe_country": country,
                    "probe_country_code": country_code,
                    "probe_asn": probe_info.get("asn"),
                    "probe_latitude": probe_info.get("latitude"),
                    "probe_longitude": probe_info.get("longitude"),
                    "source_address": result.get("from"),
                    "target_address": result.get("dst_addr"),
                    "target_name": result.get("dst_name"),
                    "timestamp": datetime.utcfromtimestamp(result.get("timestamp", 0)).isoformat() if result.get("timestamp") else None,
                    "firmware_version": result.get("fw"),
                    "protocol": result.get("proto", "ICMP"),
                    "address_family": result.get("af", 4)
                }
                
                # Initialize measurement-specific fields
                if measurement_type == "ping":
                    probe_results[probe_id].update({
                        "latency_stats": {"rtts": [], "avg": None, "min": None, "max": None},
                        "packet_loss_percentage": 0,
                        "packets_sent": 0,
                        "packets_received": 0
                    })
                elif measurement_type == "traceroute":
                    probe_results[probe_id].update({
                        "hops": [],
                        "hops_count": 0
                    })

            # Process measurement data
            if measurement_type == "ping" and "result" in result:
                self._process_ping_data(result, probe_results[probe_id])
            elif measurement_type == "traceroute" and "result" in result:
                self._process_traceroute_data(result, probe_results[probe_id])

        # Finalize individual probe results
        for probe_id, probe_result in probe_results.items():
            if probe_result.get("measurement_type") == "ping":
                self._finalize_ping_stats(probe_result)
            
            # Group by region for regional analysis
            country = probe_result.get("probe_country", "Unknown")
            if country != "Unknown":
                regional_data[country].append(probe_result)

        # Perform regional analysis
        processed["regional_analysis"] = self._compute_regional_analysis(regional_data)
        processed["results"] = list(probe_results.values())
        
        logger.info(f"Processed {len(probe_results)} probe results with regional analysis for {len(regional_data)} regions")
        return processed

    def _batch_fetch_probe_info(self, probe_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """Fetch probe information in batches to get regional data efficiently."""
        probe_info_cache = {}
        batch_size = 100  # RIPE Atlas API limit
        
        for i in range(0, len(probe_ids), batch_size):
            batch = probe_ids[i:i + batch_size]
            try:
                # Use bulk probe API endpoint
                probe_ids_str = ','.join(map(str, batch))
                probe_url = f"{self.base_url}/probes/?id__in={probe_ids_str}"
                
                response = requests.get(probe_url)
                response.raise_for_status()
                probe_data = response.json()
                
                # Process batch results
                for probe in probe_data.get("results", []):
                    probe_id = probe.get("id")
                    if probe_id:
                        probe_info_cache[probe_id] = {
                            "country_code": probe.get("country_code"),
                            "country": self._get_country_name(probe.get("country_code")),
                            "asn": probe.get("asn_v4"),
                            "latitude": probe.get("latitude"),
                            "longitude": probe.get("longitude"),
                            "status": probe.get("status", {}).get("name") if probe.get("status") else None
                        }
                
                logger.info(f"Fetched probe info for batch {i//batch_size + 1}/{(len(probe_ids) + batch_size - 1)//batch_size}")
                
            except requests.RequestException as e:
                logger.warning(f"Error fetching probe info batch: {e}")
                # Fall back to individual requests for this batch
                for probe_id in batch:
                    if probe_id not in probe_info_cache:
                        probe_info_cache[probe_id] = self._get_probe_info(probe_id)
        
        return probe_info_cache

    def _process_ping_data(self, result: Dict, probe_result: Dict) -> None:
        """Process ping data for a single result."""
        ping_results = result.get("result", [])
        rtts = [r.get("rtt") for r in ping_results if r.get("rtt") is not None]
        
        probe_result["latency_stats"]["rtts"].extend(rtts)
        probe_result["packets_sent"] += len(ping_results)
        probe_result["packets_received"] += len(rtts)
        
        # Calculate packet loss
        loss_count = len([r for r in ping_results if r.get("x")])
        if probe_result["packets_sent"] > 0:
            probe_result["packet_loss_percentage"] = (loss_count / probe_result["packets_sent"]) * 100

    def _process_traceroute_data(self, result: Dict, probe_result: Dict) -> None:
        """Process traceroute data for a single result."""
        hops = result.get("result", [])
        probe_result["hops"] = hops
        probe_result["hops_count"] = len(hops)

    def _finalize_ping_stats(self, probe_result: Dict) -> None:
        """Finalize ping statistics for a probe."""
        rtts = probe_result["latency_stats"]["rtts"]
        if rtts:
            probe_result["latency_stats"]["avg"] = mean(rtts)
            probe_result["latency_stats"]["min"] = min(rtts)
            probe_result["latency_stats"]["max"] = max(rtts)
        else:
            probe_result["latency_stats"]["avg"] = None
            probe_result["latency_stats"]["min"] = None
            probe_result["latency_stats"]["max"] = None

    def _compute_regional_analysis(self, regional_data: Dict[str, List[Dict]]) -> Dict[str, Any]:
        """Compute comprehensive regional analysis."""
        regional_stats: Dict[str, Any] = {}
        
        for country, probe_results in regional_data.items():
            if len(probe_results) < 1:
                continue
            
            # Analyze ping measurements
            ping_probes = [p for p in probe_results if p.get("measurement_type") == "ping"]
            traceroute_probes = [p for p in probe_results if p.get("measurement_type") == "traceroute"]
            
            country_stats: Dict[str, Any] = {
                "probe_count": len(probe_results),
                "ping_probe_count": len(ping_probes),
                "traceroute_probe_count": len(traceroute_probes)
            }
            
            # Ping analysis
            if ping_probes:
                latencies = []
                packet_losses = []
                jitters = []
                
                for probe in ping_probes:
                    latency_stats = probe.get("latency_stats", {})
                    if latency_stats.get("avg") is not None:
                        latencies.append(float(latency_stats["avg"]))
                        packet_losses.append(float(probe.get("packet_loss_percentage", 0)))
                        
                        # Calculate jitter (standard deviation of RTTs)
                        rtts = latency_stats.get("rtts", [])
                        if len(rtts) > 1:
                            from statistics import stdev
                            jitters.append(stdev([float(rtt) for rtt in rtts]))
                        else:
                            jitters.append(0.0)
                
                if latencies:
                    ping_stats: Dict[str, float] = {
                        "median_latency": float(median(latencies)),
                        "mean_latency": float(mean(latencies)),
                        "min_latency": float(min(latencies)),
                        "max_latency": float(max(latencies)),
                        "avg_packet_loss": float(mean(packet_losses)),
                        "max_packet_loss": float(max(packet_losses)),
                        "avg_jitter": float(mean(jitters)) if jitters else 0.0,
                        "max_jitter": float(max(jitters)) if jitters else 0.0
                    }
                    country_stats["ping_stats"] = ping_stats
            
            # Traceroute analysis
            if traceroute_probes:
                hop_counts = [float(p.get("hops_count", 0)) for p in traceroute_probes if p.get("hops_count")]
                if hop_counts:
                    traceroute_stats: Dict[str, float] = {
                        "avg_hops": float(mean(hop_counts)),
                        "min_hops": float(min(hop_counts)),
                        "max_hops": float(max(hop_counts)),
                        "median_hops": float(median(hop_counts))
                    }
                    country_stats["traceroute_stats"] = traceroute_stats
            
            regional_stats[country] = country_stats
            logger.info(f"Regional analysis for {country}: {country_stats.get('probe_count', 0)} probes")
        
        # Add summary statistics
        total_countries = len(regional_stats)
        total_probes = sum(int(stats.get("probe_count", 0)) for stats in regional_stats.values())
        
        summary: Dict[str, Any] = {
            "total_countries": total_countries,
            "total_probes_analyzed": total_probes,
            "countries": list(regional_stats.keys())
        }
        
        return {
            "summary": summary,
            "by_country": regional_stats
        }

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
        """Retrieve the saved measurement IDs from the created_measurements_dir."""
        measurement_ids = []
        if self.created_measurements_dir.exists():
            for info_file in self.created_measurements_dir.glob("measurement_*_info.json"):
                try:
                    with open(info_file, 'r') as f:
                        info = json.load(f)
                        measurement_id = info.get('measurement_id')
                        if measurement_id:
                            measurement_ids.append(int(measurement_id))
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.warning(f"Error reading measurement info from {info_file}: {e}")
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

    def fetch_and_analyze_measurements(self, measurement_ids: List[str]) -> List[Dict[str, Any]]:
        """Fetch measurements and perform regional analysis."""
        all_results = []
        
        for measurement_id in measurement_ids:
            logger.info(f"Fetching measurement {measurement_id}")
            success = self._fetch_single_measurement(int(measurement_id))
            
            if success:
                # Load the saved results
                results_file = self.fetched_measurements_dir / f"measurement_{measurement_id}_result.json"
                if results_file.exists():
                    with open(results_file, 'r') as f:
                        measurement_result = json.load(f)
                    
                    # Add regional analysis
                    measurement_result = self._add_regional_analysis(measurement_result)
                    all_results.append(measurement_result)
                    
                    # Save updated result with regional analysis
                    self._save_results(measurement_id, measurement_result)
        
        return all_results
    
    def _add_regional_analysis(self, measurement_result: Dict[str, Any]) -> Dict[str, Any]:
        """Add regional analysis to measurement results."""
        results = measurement_result.get("results", [])
        if not results:
            return measurement_result
        
        # Group results by country/region
        regional_data = defaultdict(list)
        for result in results:
            country = result.get("probe_country")
            if country and result.get("measurement_type") == "ping":
                regional_data[country].append(result)
        
        # Calculate regional statistics
        regional_stats: Dict[str, Any] = {}
        for country, probe_results in regional_data.items():
            if len(probe_results) >= 2:  # Minimum 2 probes for regional analysis
                latencies = []
                packet_losses = []
                
                for probe_result in probe_results:
                    latency_stats = probe_result.get("latency_stats", {})
                    avg_latency = latency_stats.get("avg")
                    if avg_latency is not None:
                        latencies.append(float(avg_latency))
                        packet_loss = probe_result.get("packet_loss_percentage", 0)
                        packet_losses.append(float(packet_loss))
                
                if latencies:
                    country_analysis: Dict[str, Any] = {
                        "probe_count": len(probe_results),
                        "median_latency": float(median(latencies)),
                        "mean_latency": float(mean(latencies)),
                        "min_latency": float(min(latencies)),
                        "max_latency": float(max(latencies)),
                        "avg_packet_loss": float(mean(packet_losses)),
                        "max_packet_loss": float(max(packet_losses))
                    }
                    regional_stats[country] = country_analysis
        
        # Add regional analysis to measurement result
        measurement_result["regional_analysis"] = regional_stats
        logger.info(f"Added regional analysis for {len(regional_stats)} regions")
        
        return measurement_result

    def fetch_measurement_results(self, measurement_id: str) -> Optional[Dict[str, Any]]:
        """Fetch results for a specific measurement with enhanced probe information."""
        try:
            # Get measurement info first
            measurement_url = f"{self.base_url}/measurements/{measurement_id}/"
            measurement_response = requests.get(measurement_url)
            measurement_response.raise_for_status()
            measurement_info = measurement_response.json()
            
            # Get measurement results
            results_url = f"{self.base_url}/measurements/{measurement_id}/results/"
            params = {"format": "json"}
            
            response = requests.get(results_url, params=params)
            response.raise_for_status()
            
            raw_results = response.json()
            logger.info(f"Retrieved {len(raw_results)} raw results for measurement {measurement_id}")
            
            # Process results and add probe information
            processed_results = []
            probe_cache = {}  # Cache probe info to avoid repeated API calls
            
            for result in raw_results:
                probe_id = result.get("prb_id")
                if probe_id:
                    # Get probe information including country
                    if probe_id not in probe_cache:
                        probe_info = self._get_probe_info(probe_id)
                        probe_cache[probe_id] = probe_info
                    
                    probe_info = probe_cache[probe_id]
                    processed_result = self._process_measurement_result(result, measurement_info, probe_info)
                    if processed_result:
                        processed_results.append(processed_result)
            
            logger.info(f"Processed {len(processed_results)} results with probe information")
            
            return {
                "measurement_id": measurement_id,
                "measurement_type": measurement_info.get("type"),
                "target": measurement_info.get("target"),
                "creation_time": measurement_info.get("creation_time"),
                "results": processed_results,
                "total_probes": len(processed_results)
            }
            
        except requests.RequestException as e:
            logger.error(f"Error fetching measurement results for {measurement_id}: {e}")
            return None

    def _get_probe_info(self, probe_id: int) -> Dict[str, Any]:
        """Get probe information including country code."""
        try:
            probe_url = f"{self.base_url}/probes/{probe_id}/"
            response = requests.get(probe_url)
            response.raise_for_status()
            probe_data = response.json()
            
            return {
                "country_code": probe_data.get("country_code"),
                "country": self._get_country_name(probe_data.get("country_code")),
                "asn": probe_data.get("asn_v4"),
                "prefix": probe_data.get("prefix_v4"),
                "status": probe_data.get("status", {}).get("name"),
                "latitude": probe_data.get("latitude"),
                "longitude": probe_data.get("longitude")
            }
        except requests.RequestException as e:
            logger.warning(f"Could not fetch probe info for probe {probe_id}: {e}")
            return {"country_code": None, "country": "Unknown"}

    def _get_country_name(self, country_code: str) -> str:
        """Convert country code to country name with expanded mapping."""
        if not country_code:
            return "Unknown"
        
        # Expanded country code to name mapping
        country_map = {
            "AD": "Andorra", "AE": "United Arab Emirates", "AF": "Afghanistan", "AG": "Antigua and Barbuda",
            "AI": "Anguilla", "AL": "Albania", "AM": "Armenia", "AO": "Angola", "AQ": "Antarctica",
            "AR": "Argentina", "AS": "American Samoa", "AT": "Austria", "AU": "Australia", "AW": "Aruba",
            "AX": "Åland Islands", "AZ": "Azerbaijan", "BA": "Bosnia and Herzegovina", "BB": "Barbados",
            "BD": "Bangladesh", "BE": "Belgium", "BF": "Burkina Faso", "BG": "Bulgaria", "BH": "Bahrain",
            "BI": "Burundi", "BJ": "Benin", "BL": "Saint Barthélemy", "BM": "Bermuda", "BN": "Brunei",
            "BO": "Bolivia", "BQ": "Caribbean Netherlands", "BR": "Brazil", "BS": "Bahamas", "BT": "Bhutan",
            "BV": "Bouvet Island", "BW": "Botswana", "BY": "Belarus", "BZ": "Belize", "CA": "Canada",
            "CC": "Cocos Islands", "CD": "DR Congo", "CF": "Central African Republic", "CG": "Republic of the Congo",
            "CH": "Switzerland", "CI": "Côte d'Ivoire", "CK": "Cook Islands", "CL": "Chile", "CM": "Cameroon",
            "CN": "China", "CO": "Colombia", "CR": "Costa Rica", "CU": "Cuba", "CV": "Cape Verde",
            "CW": "Curaçao", "CX": "Christmas Island", "CY": "Cyprus", "CZ": "Czech Republic", "DE": "Germany",
            "DJ": "Djibouti", "DK": "Denmark", "DM": "Dominica", "DO": "Dominican Republic", "DZ": "Algeria",
            "EC": "Ecuador", "EE": "Estonia", "EG": "Egypt", "EH": "Western Sahara", "ER": "Eritrea",
            "ES": "Spain", "ET": "Ethiopia", "FI": "Finland", "FJ": "Fiji", "FK": "Falkland Islands",
            "FM": "Micronesia", "FO": "Faroe Islands", "FR": "France", "GA": "Gabon", "GB": "United Kingdom",
            "GD": "Grenada", "GE": "Georgia", "GF": "French Guiana", "GG": "Guernsey", "GH": "Ghana",
            "GI": "Gibraltar", "GL": "Greenland", "GM": "Gambia", "GN": "Guinea", "GP": "Guadeloupe",
            "GQ": "Equatorial Guinea", "GR": "Greece", "GS": "South Georgia", "GT": "Guatemala", "GU": "Guam",
            "GW": "Guinea-Bissau", "GY": "Guyana", "HK": "Hong Kong", "HM": "Heard Island", "HN": "Honduras",
            "HR": "Croatia", "HT": "Haiti", "HU": "Hungary", "ID": "Indonesia", "IE": "Ireland",
            "IL": "Israel", "IM": "Isle of Man", "IN": "India", "IO": "British Indian Ocean Territory",
            "IQ": "Iraq", "IR": "Iran", "IS": "Iceland", "IT": "Italy", "JE": "Jersey", "JM": "Jamaica",
            "JO": "Jordan", "JP": "Japan", "KE": "Kenya", "KG": "Kyrgyzstan", "KH": "Cambodia",
            "KI": "Kiribati", "KM": "Comoros", "KN": "Saint Kitts and Nevis", "KP": "North Korea",
            "KR": "South Korea", "KW": "Kuwait", "KY": "Cayman Islands", "KZ": "Kazakhstan", "LA": "Laos",
            "LB": "Lebanon", "LC": "Saint Lucia", "LI": "Liechtenstein", "LK": "Sri Lanka", "LR": "Liberia",
            "LS": "Lesotho", "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia", "LY": "Libya",
            "MA": "Morocco", "MC": "Monaco", "MD": "Moldova", "ME": "Montenegro", "MF": "Saint Martin",
            "MG": "Madagascar", "MH": "Marshall Islands", "MK": "North Macedonia", "ML": "Mali", "MM": "Myanmar",
            "MN": "Mongolia", "MO": "Macao", "MP": "Northern Mariana Islands", "MQ": "Martinique",
            "MR": "Mauritania", "MS": "Montserrat", "MT": "Malta", "MU": "Mauritius", "MV": "Maldives",
            "MW": "Malawi", "MX": "Mexico", "MY": "Malaysia", "MZ": "Mozambique", "NA": "Namibia",
            "NC": "New Caledonia", "NE": "Niger", "NF": "Norfolk Island", "NG": "Nigeria", "NI": "Nicaragua",
            "NL": "Netherlands", "NO": "Norway", "NP": "Nepal", "NR": "Nauru", "NU": "Niue", "NZ": "New Zealand",
            "OM": "Oman", "PA": "Panama", "PE": "Peru", "PF": "French Polynesia", "PG": "Papua New Guinea",
            "PH": "Philippines", "PK": "Pakistan", "PL": "Poland", "PM": "Saint Pierre and Miquelon",
            "PN": "Pitcairn Islands", "PR": "Puerto Rico", "PS": "Palestine", "PT": "Portugal", "PW": "Palau",
            "PY": "Paraguay", "QA": "Qatar", "RE": "Réunion", "RO": "Romania", "RS": "Serbia",
            "RU": "Russia", "RW": "Rwanda", "SA": "Saudi Arabia", "SB": "Solomon Islands", "SC": "Seychelles",
            "SD": "Sudan", "SE": "Sweden", "SG": "Singapore", "SH": "Saint Helena", "SI": "Slovenia",
            "SJ": "Svalbard and Jan Mayen", "SK": "Slovakia", "SL": "Sierra Leone", "SM": "San Marino",
            "SN": "Senegal", "SO": "Somalia", "SR": "Suriname", "SS": "South Sudan", "ST": "São Tomé and Príncipe",
            "SV": "El Salvador", "SX": "Sint Maarten", "SY": "Syria", "SZ": "Eswatini", "TC": "Turks and Caicos",
            "TD": "Chad", "TF": "French Southern Territories", "TG": "Togo", "TH": "Thailand", "TJ": "Tajikistan",
            "TK": "Tokelau", "TL": "East Timor", "TM": "Turkmenistan", "TN": "Tunisia", "TO": "Tonga",
            "TR": "Turkey", "TT": "Trinidad and Tobago", "TV": "Tuvalu", "TW": "Taiwan", "TZ": "Tanzania",
            "UA": "Ukraine", "UG": "Uganda", "UM": "US Minor Outlying Islands", "US": "United States",
            "UY": "Uruguay", "UZ": "Uzbekistan", "VA": "Vatican City", "VC": "Saint Vincent and the Grenadines",
            "VE": "Venezuela", "VG": "British Virgin Islands", "VI": "US Virgin Islands", "VN": "Vietnam",
            "VU": "Vanuatu", "WF": "Wallis and Futuna", "WS": "Samoa", "YE": "Yemen", "YT": "Mayotte",
            "ZA": "South Africa", "ZM": "Zambia", "ZW": "Zimbabwe"
        }
        
        return country_map.get(country_code, country_code)

    def _process_measurement_result(self, result: Dict, measurement_info: Dict, probe_info: Dict) -> Optional[Dict[str, Any]]:
        """Process a single measurement result with probe information."""
        try:
            measurement_type = measurement_info.get("type")
            processed_result = {
                "probe_id": result.get("prb_id"),
                "measurement_type": measurement_type,
                "probe_country": probe_info.get("country", "Unknown"),
                "probe_country_code": probe_info.get("country_code"),
                "probe_asn": probe_info.get("asn"),
                "timestamp": result.get("timestamp"),
                "target": measurement_info.get("target")
            }
            
            if measurement_type == "ping":
                processed_result.update(self._process_ping_result(result))
            elif measurement_type == "traceroute":
                processed_result.update(self._process_traceroute_result(result))
            
            return processed_result
            
        except Exception as e:
            logger.warning(f"Error processing result for probe {result.get('prb_id')}: {e}")
            return None

    def _process_ping_result(self, result: Dict) -> Dict[str, Any]:
        """Process ping measurement result."""
        ping_data = {}
        
        if "result" in result:
            ping_results = result["result"]
            rtts = [r.get("rtt") for r in ping_results if r.get("rtt") is not None]
            
            ping_data.update({
                "latency_stats": {
                    "rtts": rtts,
                    "avg": sum(rtts) / len(rtts) if rtts else None,
                    "min": min(rtts) if rtts else None,
                    "max": max(rtts) if rtts else None
                },
                "packet_loss_percentage": len([r for r in ping_results if r.get("x")]) / len(ping_results) * 100 if ping_results else 0,
                "packets_sent": len(ping_results),
                "packets_received": len(rtts)
            })
        
        return ping_data

    def _process_traceroute_result(self, result: Dict) -> Dict[str, Any]:
        """Process traceroute measurement result."""
        traceroute_data = {}
        
        if "result" in result:
            hops = result.get("result", [])
            traceroute_data.update({
                "hops": hops,
                "hops_count": len(hops)
            })
        
        return traceroute_data

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
