# Configuration Guide

This guide explains how to configure Sintra's YAML configuration files for network measurements.

## Overview

Sintra uses two main configuration files:

- **`create_config.yaml`** - Defines parameters for creating new measurements
- **`fetch_config.yaml`** - Specifies which measurement results to retrieve

## Create Configuration (`create_config.yaml`)

This file defines the measurements you want to create on the RIPE Atlas platform.

### Basic Structure

```yaml
measurements:
  - type: ping
    target: example.com
    description: "Description of your measurement"
    interval: 300
    duration_hours: 1
    af: 4
    probes:
      country: "JP"
      count: 10
```

### Configuration Parameters

#### Measurement Types

| Type | Description | Supported Protocols |
|------|-------------|-------------------|
| `ping` | ICMP ping measurements | ICMP |
| `traceroute` | Network path tracing | ICMP, UDP, TCP |

#### Common Parameters

| Parameter | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `type` | string | Yes | Type of measurement | `ping`, `traceroute` |
| `target` | string | Yes | Target hostname or IP | `discord.com`, `8.8.8.8` |
| `description` | string | Yes | Human-readable description | `"Ping to Discord servers"` |
| `interval` | integer | Yes | Seconds between measurements | `300` (5 minutes) |
| `duration_hours` | integer | Yes | How long to run (hours) | `1`, `24`, `168` |
| `af` | integer | Yes | IP version (4 or 6) | `4` (IPv4), `6` (IPv6) |

#### Probe Configuration

The `probes` section defines which RIPE Atlas probes to use. You can select probes by geographical area or by specific country:

| Parameter | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `area` | string | Yes* | Geographical area | `"North America"`, `"Europe"`, `"Asia"` |
| `country` | string | Yes* | Country code (ISO 3166-1 alpha-2) | `"US"`, `"DE"`, `"JP"`, `"IN"` |
| `count` | integer | Yes | Number of probes | `10`, `50`, `100` |

*Either `area` or `country` must be specified, but not both.

#### Traceroute-Specific Parameters

| Parameter | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `protocol` | string | Optional | Protocol to use | `"ICMP"`, `"UDP"`, `"TCP"` |

### Example Configurations

#### Simple Ping Measurement

```yaml
measurements:
  - type: ping
    target: google.com
    description: "Basic ping to Google"
    interval: 300  # 5 minutes
    duration_hours: 1
    af: 4
    probes:
      country: "US"
      count: 5
```

#### Multiple Measurements

```yaml
measurements:
  # Ping measurement using country selection
  - type: ping
    target: discord.com
    description: "Ping measurement to Discord DNS from Japan"
    interval: 300
    duration_hours: 1
    af: 4
    probes:
      country: "JP"  # Japan
      count: 10

  # Traceroute measurement using country selection
  - type: traceroute
    target: discord.com
    description: "Traceroute to Discord from India"
    protocol: "ICMP"
    interval: 900  # 15 minutes
    duration_hours: 2
    af: 4
    probes:
      country: "IN"  # India
      count: 10

  # Area-based selection (original functionality)
  - type: ping
    target: facebook.com
    description: "Ping measurement using area selection"
    interval: 240
    duration_hours: 1
    af: 4
    probes:
      country: "JP"
      count: 6
```

#### IPv6 Measurement

```yaml
measurements:
  - type: ping
    target: ipv6.google.com
    description: "IPv6 ping to Google"
    interval: 600
    duration_hours: 2
    af: 6  # IPv6
    probes:
      area: "Europe"
      count: 15
```

### Geographical Areas

Common geographical areas supported by RIPE Atlas:

- `"North America"`
- `"South America"`
- `"Europe"`
- `"Asia"`
- `"Africa"`
- `"Oceania"`
- `"South-Central"`
- `"South-East"`
- `"North-East"`
- `"West"`
- `"East"`

### Country Codes

Use ISO 3166-1 alpha-2 country codes for country-based probe selection. Common examples:

**Americas:**
- `"US"` - United States
- `"CA"` - Canada
- `"BR"` - Brazil
- `"MX"` - Mexico

**Europe:**
- `"DE"` - Germany
- `"GB"` - United Kingdom
- `"FR"` - France
- `"NL"` - Netherlands
- `"IT"` - Italy
- `"ES"` - Spain

**Asia-Pacific:**
- `"JP"` - Japan
- `"CN"` - China
- `"IN"` - India
- `"KR"` - South Korea
- `"AU"` - Australia
- `"SG"` - Singapore

**Other Regions:**
- `"ZA"` - South Africa
- `"EG"` - Egypt
- `"RU"` - Russia

For a complete list of country codes, refer to the [ISO 3166-1 alpha-2 standard](https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2).

### Best Practices

1. **Interval Selection**: Choose intervals based on your monitoring needs:
   - Real-time monitoring: 60-300 seconds
   - Regular monitoring: 300-900 seconds
   - Long-term studies: 1800+ seconds

2. **Probe Count**: Balance between data accuracy and resource usage:
   - Quick tests: 5-10 probes
   - Standard monitoring: 10-25 probes
   - Comprehensive analysis: 25+ probes

3. **Duration**: Set appropriate measurement duration:
   - Testing: 1-2 hours
   - Daily monitoring: 24 hours
   - Weekly analysis: 168 hours (1 week)

## Fetch Configuration (`fetch_config.yaml`)

This file specifies which measurement results to retrieve from RIPE Atlas.

### Basic Structure

```yaml
measurement_ids:
  - 108497348
  - 108497346

fetch_settings:
  limit: 1000
  format: "json"
```

### Configuration Parameters

#### Measurement IDs

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `measurement_ids` | list | Yes | List of measurement IDs to fetch |

#### Fetch Settings

| Parameter | Type | Required | Description | Default |
|-----------|------|----------|-------------|---------|
| `limit` | integer | Optional | Maximum number of results | `1000` |
| `format` | string | Optional | Output format | `"json"` |

### Example Configurations

#### Basic Fetch

```yaml
measurement_ids:
  - 12345678
  - 87654321

fetch_settings:
  limit: 500
  format: "json"
```

#### Large Dataset Fetch

```yaml
measurement_ids:
  - 11111111
  - 22222222
  - 33333333

fetch_settings:
  limit: 5000
  format: "json"
```

### Finding Measurement IDs

Measurement IDs are returned when you create measurements using the create configuration. They can also be found:

1. In the application logs after creating measurements
2. In the `created_measurements/` results directory
3. On the RIPE Atlas web interface

## Environment Variables

### Required Environment Variables

Create a `.env` file in the project root:

```bash
RIPE_ATLAS_API_KEY=your_api_key_here
```

### Getting a RIPE Atlas API Key

1. Visit [RIPE Atlas](https://atlas.ripe.net/)
2. Create an account or log in
3. Navigate to your profile settings
4. Generate an API key
5. Copy the key to your `.env` file

## Troubleshooting

### Common Issues

1. **Invalid API Key**
   - Verify your API key in the `.env` file
   - Check that the key has appropriate permissions

2. **Invalid Target**
   - Ensure target domains/IPs are reachable
   - Verify DNS resolution for domain names

3. **Probe Availability**
   - Some geographical areas may have limited probes
   - Try adjusting probe count or area

4. **Configuration Syntax**
   - Validate YAML syntax using an online YAML validator
   - Check indentation (YAML is whitespace-sensitive)

### Validation

Before running measurements, validate your configuration:

1. Check YAML syntax
2. Verify all required parameters are present
3. Ensure measurement IDs exist for fetch operations
4. Test with a small probe count first

## Advanced Configuration

### Batch Operations

You can define multiple measurements in a single configuration file for batch processing.

### Integration with Other Tools

The JSON output format makes it easy to integrate with other network analysis tools and monitoring systems.


