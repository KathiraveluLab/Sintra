from statistics import stdev

def calculate_jitter(rtts):
    if rtts and len(rtts) > 1:
        return stdev(rtts)
    return 0.0

def is_outlier(value, values, factor=2):
    valid = [v for v in values if v is not None]
    if not valid:
        return False
    avg = sum(valid) / len(valid)
    return value is not None and value > avg * factor

def geo_anomaly_check(dist1, lat1, dist2, lat2, margin=50):
    if dist1 and dist2 and dist1 > dist2 and lat1 < lat2 - margin:
        return True
    return False
