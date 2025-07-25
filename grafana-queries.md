# Sintra Network Monitoring Queries

## Key Metrics

### Latency Monitoring
```promql
# Average latency by probe
sintra_ping_latency_avg_ms

# Latency by source location
avg(sintra_ping_latency_avg_ms) by (source)

# Maximum latency across all probes
max(sintra_ping_latency_max_ms)

# Latency trend over time
rate(sintra_ping_latency_avg_ms[5m])
```

### Packet Loss Analysis
```promql
# Current packet loss by probe
sintra_ping_packet_loss_percent

# Average packet loss by source
avg(sintra_ping_packet_loss_percent) by (source)

# Probes with packet loss > 1%
sintra_ping_packet_loss_percent > 1
```

### Network Quality Overview
```promql
# Total active probes per measurement
sintra_measurement_total_probes

# Probe performance comparison
sintra_ping_latency_avg_ms{source=~"212.64.160.7|154.126.223.249"}

# Network quality score (inverse of latency + packet loss)
100 - (sintra_ping_latency_avg_ms + sintra_ping_packet_loss_percent * 10)
```

### Geographic Analysis
```promql
# African probes performance
sintra_ping_latency_avg_ms{source=~"197.214.65.227|102.222.62.40|105.186.58.234"}

# Low latency probes (< 5ms)
sintra_ping_latency_avg_ms < 5

# High latency alerts (> 50ms)
sintra_ping_latency_avg_ms > 50
```

## Dashboard Panels

### Panel 1: Latency Heatmap
- Query: `sintra_ping_latency_avg_ms`
- Visualization: Time series
- Legend: `{{source}} ({{probe_id}})`

### Panel 2: Packet Loss Alert
- Query: `sintra_ping_packet_loss_percent > 0`
- Visualization: Stat
- Thresholds: Green (0), Yellow (1), Red (5)

### Panel 3: Network Map
- Query: `avg by (source) (sintra_ping_latency_avg_ms)`
- Visualization: Geomap
- Color scheme: Green-Yellow-Red based on latency
