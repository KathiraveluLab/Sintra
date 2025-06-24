from datetime import datetime

def process_ping_result(result):
    ping_results = result.get("result", [])
    rtts = []
    
    for ping in ping_results:
        if ping.get("rtt") is not None:
            rtts.append(ping["rtt"])
    
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

def process_traceroute_result(result):
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

def create_basic_result(result):
    return {
        "probe_id": result.get("prb_id"),
        "source_address": result.get("from"),
        "target_address": result.get("dst_addr"),
        "timestamp": datetime.utcfromtimestamp(result.get("timestamp", 0)).isoformat() if result.get("timestamp") else None,
    }
