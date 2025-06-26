# Sintra

**Self-adaptive Interdomain Network Transport for Real-Time Applications**

Sintra is a network measurement tool that leverages the RIPE Atlas platform to perform network latency measurements and monitoring across different geographical regions. It provides automated measurement creation, result fetching, and data processing capabilities for network analysis and real-time application optimization.

## Features

- **Multi-region Network Measurements**: Create ping and traceroute measurements across different geographical areas
- **Flexible Configuration**: YAML-based configuration for easy measurement setup
- **Organized Results**: Structured storage of measurement data with JSON output
- **Result Processing**: Built-in processors for ping and traceroute data analysis
- **RIPE Atlas Integration**: Full integration with RIPE Atlas measurement infrastructure

## Requirements

- Python 3.7+
- RIPE Atlas API Key

## Installation

1. Clone the repository:
```bash
git clone https://github.com/KathiraveluLab/Sintra.git
cd Sintra
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up your RIPE Atlas API key:
```bash
# Create a .env file in the project root
echo "RIPE_ATLAS_API_KEY=your_api_key_here" > .env
```

## Usage

### Basic Usage

Run the main application:
```bash
python sintra.py # Main file for Sintra
```

### Configuration

The application uses two main configuration files:

- `measurement_client/create_config.yaml` - For creating new measurements
- `measurement_client/fetch_config.yaml` - For fetching existing measurement results

See the [Configuration Documentation](docs/configuration.md) for detailed setup instructions.

### Command Line Interface

The measurement client supports various command-line options for different operations:

- **python sintra.py create**: Configure and start new network measurements
- **python sintra.py fetch**: Retrieve results from existing/public measurements and processed for better understanding.


## Getting Started

1. **Obtain a RIPE Atlas API Key**: Visit [RIPE Atlas](https://atlas.ripe.net/) and create an account to get your API key.

2. **Configure your first measurement**: Edit `measurement_client/create_config.yaml` to define your measurement parameters.

3. **Run your first measurement**:
```bash
python sintra.py create
```
4. **Fetch Results**:
```bash
python sintra.py fetch
```

5. **Monitor results**: Check the `measurement_client/results/fetched_measurements` directory for output files.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the terms specified in the [LICENSE](LICENSE) file.

## Support

For questions, issues, or feature requests, please create an issue in the project repository.
