# Sintra Network Measurement & Event Management Tool - Results Documentation

## Overview

Sintra is a software virtual router that adapts Internet traffic routing in real-time based on network measurements collected by RIPE Atlas. The system continuously monitors network performance across multiple paths and automatically selects optimal routes to improve connectivity reliability and performance, particularly in areas where stable connections are critical.


## Command Reference

### Core Commands

- **`create`** - Create new RIPE Atlas measurements based on configuration
- **`fetch`** - Retrieve measurement results from RIPE Atlas API  
- **`detect`** - Analyze fetched results for network anomalies
- **`alerts`** - Display summary of detected anomalies and events

## Measurement Creation

### Definition
The `create` command schedules new measurements on the RIPE Atlas platform using distributed probes worldwide. Measurements can be ping or traceroute tests targeting specific hosts from selected geographic regions.

### Configuration
Measurements are defined in `measurement_client/create_config.yaml` with the following parameters:

- **type**: Measurement type (`ping` or `traceroute`)
- **target**: Destination IP address or hostname
- **description**: Human-readable description of the measurement
- **interval**: Time between individual measurement rounds (seconds)
- **duration_hours**: Total measurement duration
- **af**: Address family (4 for IPv4, 6 for IPv6)
- **probes**: Probe selection criteria (country code or area)

### Example Output

```bash
python sintra.py create
[2025-07-30 22:21:19,692] INFO: Sintra Network Management Tool - Command: create
[2025-07-30 22:21:19,698] INFO: === Creating RIPE Atlas Measurements ===
[2025-07-30 22:21:19,698] INFO: SintraMeasurementClient initialized successfully
[2025-07-30 22:21:19,714] INFO: Configuration loaded successfully from measurement_client/create_config.yaml
[2025-07-30 22:21:22,476] INFO: Created ping measurement 120803586 for 77.91.138.212
[2025-07-30 22:21:23,422] INFO: Created traceroute measurement 120803587 for 103.68.48.6
[2025-07-30 22:21:23,425] INFO: Measurement creation complete: 2 successful, 0 failed
[2025-07-30 22:21:23,426] INFO: Command completed successfully
```

**Key Information:**
- **Target Addresses**: Specific IP addresses being monitored
- **Success Rate**: Number of successfully created vs. failed measurements

---

## Measurement Fetching

### Definition
The `fetch` command retrieves completed measurement results from RIPE Atlas and processes them into a structured format for analysis. Results include latency statistics, packet loss data, and routing information.

### Fetch Options
- **Specific ID**: `--measurement-id 123456` - Fetch single measurement
- **Config File**: Use `measurement_client/fetch_config.yaml` for multiple measurements
- **All Saved**: `--all` - Fetch all previously created measurements

### Example Output

```bash
python sintra.py fetch --measurement-id 120802092
[2025-07-30 22:13:07,540] INFO: === Fetching Measurement Results ===
[2025-07-30 22:13:07,540] INFO: SintraMeasurementClient initialized successfully
[2025-07-30 22:13:07,540] INFO: Fetching specific measurement: 120802092
[2025-07-30 22:13:09,281] INFO: Retrieved 474 results for measurement 120802092
[2025-07-30 22:13:09,331] INFO: Saved results for measurement 120802092
[2025-07-30 22:13:09,331] INFO: Fetch complete: 1 successful, 0 failed
```

**Key Information:**
- **Storage**: Results saved to `measurement_client/results/fetched_measurements/`
- **Processing**: Raw RIPE Atlas data converted to structured JSON format

---

## Anomaly Detection

### Definition
The `detect` command analyzes fetched measurement results to identify network anomalies using statistical analysis and threshold-based detection algorithms. It compares current performance against baselines and peer probe measurements.

### Detection Categories

#### Latency Anomalies
- **Latency Spike**: RTT exceeds static threshold (250ms) or adaptive baseline (2x normal)
- **Outlier Probe Latency**: Individual probes show significantly higher latency than peers
- **Jitter Spike**: High variation in round-trip times indicating network instability

#### Connectivity Anomalies  
- **Packet Loss**: Packet loss percentage exceeds threshold (10%)
- **Unreachable Host**: Complete connectivity failure (100% packet loss)
- **Outlier Probe Loss**: Individual probes show higher loss rates than peers

#### Routing Anomalies
- **Route Change**: Traceroute path differs from established baseline
- **Path Flapping**: Frequent changes in routing paths indicating instability
- **Geographic Anomaly**: Distant probes show better performance than nearby ones

### Configuration
Detection thresholds are configurable in `event_manager/config.json`:

```json
{
  "thresholds": {
    "latency_spike_ms": 250.0,
    "packet_loss_percentage": 10.0,
    "jitter_spike_ms": 15.0,
    "outlier_factor": 2.0
  }
}
```

### Example Output

```bash
python sintra.py detect
[2025-07-30 22:14:30,019] INFO: === Running Anomaly Detection ===
[2025-07-30 22:14:30,025] INFO: Configuration loaded from event_manager/config.json
[2025-07-30 22:14:30,025] INFO: SintraEventManager initialized
[2025-07-30 22:14:30,026] INFO: Found 1 measurement result files to analyze
[2025-07-30 22:14:33,107] INFO: Events for measurement 120802092 saved: 121 anomalies
[2025-07-30 22:14:33,108] INFO: Anomaly detection complete. Results saved to: event_manager/results/
```

**Key Information:**
- **Analysis Scope**: Number of measurement files processed
- **Anomaly Count**: Total events detected across all measurements
- **Output Location**: Events saved to `event_manager/results/`

---

## Alerts Summary

### Definition
The `alerts` command provides a comprehensive summary of detected anomalies with statistical breakdowns and severity classifications. It helps network operators prioritize response efforts.

### Alert Metrics

#### Per-Measurement Analysis
- **Total Anomalies**: Count of all detected events
- **Probes Affected**: Number of unique measurement probes experiencing issues
- **Anomaly Breakdown**: Distribution by anomaly type with descriptions

#### Global Statistics  
- **Measurements Analyzed**: Total number of measurement datasets processed
- **Average Anomalies**: Mean anomaly count per measurement
- **Percentage Distribution**: Relative frequency of each anomaly type

### Example Output

```bash
python sintra.py alerts
[2025-07-30 22:12:24,070] INFO: === Alerts Summary ===

Measurement 120802092:
  Total anomalies: 121
  Probes affected: 81
  Anomaly breakdown:
    latency_spike: 38 events - RTT exceeds threshold or spikes suddenly
    outlier_probe_latency: 80 events - Individual probes show high delay
    outlier_probe_loss: 1 events - Individual probes show high loss
    packet_loss: 1 events - Packet loss > threshold (5-10%)
    unreachable_host: 1 events - 100% packet loss, host unreachable

=== Global Summary ===
Total measurements analyzed: 1
Total anomalies detected: 121
Average anomalies per measurement: 121.0

Global anomaly breakdown:
  outlier_probe_latency: 80 events (66.1%) - Individual probe delays
  latency_spike: 38 events (31.4%) - RTT threshold violations  
  outlier_probe_loss: 1 events (0.8%) - Individual probe loss
  packet_loss: 1 events (0.8%) - General packet loss
  unreachable_host: 1 events (0.8%) - Complete connectivity failure
```

### Detailed View
Use `--detailed` flag for comprehensive event information including:
- **Probe IDs**: Specific RIPE Atlas probes experiencing issues
- **Target Addresses**: Destination hosts affected
- **Metric Values**: Actual measurements vs. thresholds
- **Severity Levels**: Event classification (warning, critical)

### Filtering Options
- **Single Measurement**: `--measurement-id 123456` - Focus on specific measurement
- **Detailed Events**: `--detailed` - Show individual event details

---
