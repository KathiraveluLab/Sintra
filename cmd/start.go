package cmd

import (
	"fmt"
	"io/ioutil"
	"os"
	"github.com/kathiravelulab/sintra/modules/measurement"
	"github.com/kathiravelulab/sintra/types"
	"github.com/spf13/cobra"
	"gopkg.in/yaml.v2"
)

var startCmd = &cobra.Command{
	Use:   "start",
	Short: "Start creating RIPE Atlas measurements from the config file",
	Long: `Reads the SintraConfig.yml file and initiates the RIPE Atlas
measurements as defined within it.`,
	Run: func(cmd *cobra.Command, args []string) {
		apiKey := os.Getenv("RIPE_ATLAS_API_KEY")
		if apiKey == "" {
			fmt.Println("Error: RIPE_ATLAS_API_KEY environment variable not set.")
			os.Exit(1)
		}

		yamlFile, err := ioutil.ReadFile("SintraConfig.yml")
		if err != nil {
			fmt.Printf("Error reading SintraConfig.yml: %v\n", err)
			os.Exit(1)
		}

		var sintraConfig types.SintraConfig
		err = yaml.Unmarshal(yamlFile, &sintraConfig)
		if err != nil {
			fmt.Printf("Error unmarshaling SintraConfig.yml: %v\n", err)
			os.Exit(1)
		}

		fmt.Println("Starting measurement creation process...")
		err = measurement.Start(sintraConfig.MeasurementDefinitions, apiKey)
		if err != nil {
			fmt.Printf("An error occurred during measurement creation: %v\n", err)
			os.Exit(1)
		}

		fmt.Println("Measurement processing finished.")
	},
}

func init() {
	rootCmd.AddCommand(startCmd)
}