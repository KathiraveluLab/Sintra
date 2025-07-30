from datetime import datetime
import statistics
from typing import Dict, Any, Optional
from .logger import logger

# This module processes results from various types of measurements
def process_ping_result(result: Dict[str, Any]) -> Dict[str, Any]:
    try:
        ping_results = result.get("result", [])
        if not ping_results:
            logger.warning("Empty ping results received")
            return _create_empty_ping_result()
        
        rtts = []
        
        # Extract round-trip times (RTTs) from the ping results
        for ping in ping_results:
            rtt = ping.get("rtt")
            if rtt is not None:
                if isinstance(rtt, (int, float)) and rtt >= 0:
                    rtts.append(rtt)
                else:
                    logger.warning(f"Invalid RTT value: {rtt}")
        
        # Calculate the number of failed pings
        failed_pings = len([r for r in ping_results if r.get("rtt") is None])
        
        return {
            "packet_loss_percentage": (failed_pings / len(ping_results) * 100) if ping_results else 0,
            "latency_stats": {
                "min": min(rtts) if rtts else None,
                "max": max(rtts) if rtts else None,
                "avg": sum(rtts) / len(rtts) if rtts else None,
                "median": statistics.median(rtts) if rtts else None
            }
        }
    except Exception as e:
        logger.error(f"Error processing ping result: {e}")
        return _create_empty_ping_result()

def _create_empty_ping_result() -> Dict[str, Any]:
    return {
        "packet_loss_percentage": None,
        "latency_stats": {
            "min": None,
            "max": None,
            "avg": None,
            "median": None
        }
    }

# This function processes the result of a traceroute measurement
# It extracts the number of hops and calculates latency statistics
def process_traceroute_result(result: Dict[str, Any]) -> Dict[str, Any]:
    try:
        traceroute_results = result.get("result", [])
        
        return {
            "packet_loss_percentage": None,
            "latency_stats": {
                "min": None,
                "max": None, 
                "avg": None,
                "median": None
            },
            "hops_count": len(traceroute_results)
        }
    except Exception as e:
        logger.error(f"Error processing traceroute result: {e}")
        return _create_empty_traceroute_result()

def _create_empty_traceroute_result() -> Dict[str, Any]:
    return {
        "packet_loss_percentage": None,
        "latency_stats": {
            "min": None,
            "max": None,
            "avg": None,
            "median": None
        },
        "hops_count": 0
    }

# This function for default measurement results
# It returns a dictionary with None values for packet loss and latency stats                    
def process_default_result():
    return {
        "packet_loss_percentage": None,
        "latency_stats": {
            "min": None,
            "max": None,
            "avg": None, 
            "median": None
        }
    }

# This function creates a basic result dictionary from a measurement result
# It extracts the probe ID, source address, target address, and timestamp
def create_basic_result(result: Dict[str, Any]) -> Dict[str, Any]:
    try:
        timestamp = result.get("timestamp", 0)
        timestamp_iso = None
        if timestamp:
            try:
                timestamp_iso = datetime.utcfromtimestamp(timestamp).isoformat()
            except (ValueError, OSError) as e:
                logger.warning(f"Invalid timestamp {timestamp}: {e}")
        
        return {
            "probe_id": result.get("prb_id"),
            "source_address": result.get("from"),
            "target_address": result.get("dst_addr"),
            "timestamp": timestamp_iso,
        }
    except Exception as e:
        logger.error(f"Error creating basic result: {e}")
        return {
            "probe_id": None,
            "source_address": None,
            "target_address": None,
            "timestamp": None,
        }
