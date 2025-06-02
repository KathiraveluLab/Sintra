package cmd

import (
	"fmt"
	"os"

	"github.com/kathiravelulab/sintra/types"
	"github.com/spf13/cobra"
	"gopkg.in/yaml.v2"
)

var initCmd = &cobra.Command{
	Use:   "init",
	Short: "Initialize a new Sintra configuration file",
	Long: `Initialize a new SintraConfig.yml file with default measurement definitions.
This creates a template configuration file that you can customize.`,
	Run: func(cmd *cobra.Command, args []string) {
		config := types.SintraConfig{
			MeasurementDefinitions: []types.MeasurementDefinition{
				{
					ProbeIDs:             []int{},    
					TargetIPsOrHostnames: []string{}, 
					MeasurementType:      "ping",
					IntervalSeconds:      300,
					PacketSize:           64,
				},
				{
					ProbeIDs:             []int{},    
					TargetIPsOrHostnames: []string{}, 
					MeasurementType:      "traceroute",
					IntervalSeconds:      600,
					PacketSize:           48,
				},
				{
					ProbeIDs:             []int{},    
					TargetIPsOrHostnames: []string{}, 
					MeasurementType:      "dns",
					IntervalSeconds:      900,
				},
			},
		}

		yamlData, err := yaml.Marshal(&config)
		if err != nil {
			fmt.Printf("Error marshaling config: %v\n", err)
			return
		}

		configContent := fmt.Sprintf(`# Sintra Configuration File
# This file defines RIPE Atlas measurements to be created
# 
# Example probe_ids: [1, 2, 3, 4, 5]
# Example targets: ["8.8.8.8", "1.1.1.1", "google.com"]
#
# To find probe IDs, visit: https://atlas.ripe.net/probes/


%s`, string(yamlData))

		err = os.WriteFile("SintraConfig.yml", []byte(configContent), 0644)
		if err != nil {
			fmt.Printf("Error writing config file: %v\n", err)
			return
		}
		fmt.Println("SintraConfig.yml initialized successfully! Please fill in the required fields before running 'sintra start'.")
	},
}

func init() {
	rootCmd.AddCommand(initCmd)
}
