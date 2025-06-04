package types

type MeasurementDefinition struct {
	ProbeIDs             []int    `yaml:"probe_ids"`
	TargetIPsOrHostnames []string `yaml:"target_ips_or_hostnames"`
	MeasurementType      string   `yaml:"measurement_type"`
	IntervalSeconds      int      `yaml:"interval_seconds"`
	PacketSize           int      `yaml:"packet_size,omitempty"`
}

type SintraConfig struct {
	MeasurementDefinitions []MeasurementDefinition `yaml:"measurement_definitions"`
}