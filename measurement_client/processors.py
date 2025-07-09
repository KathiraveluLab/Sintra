from datetime import datetime
import statistics

# This module processes results from various types of measurements
def process_ping_result(result):
    # This function processes the result of a ping measurement
    # It calculates packet loss percentage and latency statistics
    ping_results = result.get("result", [])
    rtts = []
    
    # Extract round-trip times (RTTs) from the ping results
    # RTTs are the times it takes for a ping to go to the target and back
    # If RTT is None, it indicates a failed ping
    # We will calculate statistics only for successful pings
    for ping in ping_results:
        if ping.get("rtt") is not None:
            rtts.append(ping["rtt"])
    
    # Calculate the number of failed pings
    # A failed ping is one where the RTT is None   
    # We will use this to calculate packet loss percentage
    # Packet loss percentage is the number of failed pings divided by total pings, multiplied
    failed_pings = len([r for r in ping_results if r.get("rtt") is None])
    
    # Return a dictionary with packet loss percentage and latency statistics
    # Latency statistics include minimum, maximum, average, and median RTTs 
    # If there are no pings, we return 0% packet loss and None for latency stats
    # If there are no RTTs, we return None for all latency stats
    # If there are RTTs, we calculate the min, max, avg, and median
    # We use the statistics module to calculate the median
    return {
        "packet_loss_percentage": (failed_pings / len(ping_results) * 100) if ping_results else 0,
        "latency_stats": {
            "min": min(rtts) if rtts else None,
            "max": max(rtts) if rtts else None,
            "avg": sum(rtts) / len(rtts) if rtts else None,
            "median": statistics.median(rtts) if rtts else None
        }
    }

# This function processes the result of a traceroute measurement
# It extracts the number of hops and calculates latency statistics
def process_traceroute_result(result):
    traceroute_results = result.get("result", [])
    
    # If there are no traceroute results, we return None for all stats
    # and the number of hops as the length of the traceroute results
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
def create_basic_result(result):
    return {
        "probe_id": result.get("prb_id"),
        "source_address": result.get("from"),
        "target_address": result.get("dst_addr"),
        "timestamp": datetime.utcfromtimestamp(result.get("timestamp", 0)).isoformat() if result.get("timestamp") else None,
    }
