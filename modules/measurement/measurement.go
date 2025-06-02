package measurement

import (
	"fmt"

	"github.com/kathiravelulab/sintra/modules/measurement/client"
	"github.com/kathiravelulab/sintra/types"
)

func Start(definitions []types.MeasurementDefinition, apiKey string) error {
	if apiKey == "" {
		return fmt.Errorf("API key cannot be empty")
	}

	atlasClient := client.NewAtlasClient(apiKey)

	for _, def := range definitions {
		fmt.Printf("Processing measurement for target(s): %v\n", def.TargetIPsOrHostnames)

		for _, target := range def.TargetIPsOrHostnames {
			measurementID, err := atlasClient.CreateMeasurement(target, def)
			if err != nil {
				return fmt.Errorf("error creating measurement for target %s: %w", target, err)
			}

			fmt.Printf("Successfully created measurement for %s. ID: %d\n", target, measurementID)
		}
	}
	return nil
}

func FetchMeasurement(measurementID int, apiKey string) (*client.MeasurementResult, error) {
	if apiKey == "" {
		return nil, fmt.Errorf("API key cannot be empty")
	}

	atlasClient := client.NewAtlasClient(apiKey)
	return atlasClient.FetchMeasurement(measurementID)
}
