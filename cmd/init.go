package cmd

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
	"gopkg.in/yaml.v2"
)

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

var initCmd = &cobra.Command{
	Use:   "init",
	Short: "Initialize a new Sintra configuration file",
	Long: `Initialize a new SintraConfig.yml file with default measurement definitions.
This creates a template configuration file that you can customize for your
RIPE Atlas measurements including probe IDs, target hosts, and measurement parameters.`,
	Run: func(cmd *cobra.Command, args []string) {
		config := SintraConfig{
			MeasurementDefinitions: []MeasurementDefinition{
				{
					ProbeIDs:             []int{},
					TargetIPsOrHostnames: []string{},
					MeasurementType:      "ping",
					IntervalSeconds:      300,
					PacketSize:           64,
				},
			},
		}

		yamlData, err := yaml.Marshal(&config)
		if err != nil {
			fmt.Printf("Error marshaling config: %v\n", err)
			return
		}

		err = os.WriteFile("SintraConfig.yml", yamlData, 0644)
		if err != nil {
			fmt.Printf("Error writing config file: %v\n", err)
			return
		}

		fmt.Println("SintraConfig.yml created successfully with default measurement definitions.")
	},
}

func init() {
	rootCmd.AddCommand(initCmd)
}
