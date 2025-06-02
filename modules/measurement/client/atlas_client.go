package client

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/kathiravelulab/sintra/types"
)

const (
	baseURL = "https://atlas.ripe.net/api/v2"
)

type AtlasClient struct {
	apiKey     string
	httpClient *http.Client
}

type MeasurementDefinition struct {
	Target      string `json:"target"`
	Description string `json:"description"`
	Type        string `json:"type"`
	AF          int    `json:"af"`
	Interval    int    `json:"interval"`
	PacketSize  int    `json:"packet_size,omitempty"`
}

type ProbeSet struct {
	Type      string `json:"type"`
	Value     string `json:"value"`
	Requested int    `json:"requested"`
}

type CreateMeasurementRequest struct {
	Definitions []MeasurementDefinition `json:"definitions"`
	Probes      []ProbeSet              `json:"probes"`
}

type CreateMeasurementResponse struct {
	Measurements []int `json:"measurements"`
}

type MeasurementResult struct {
	ID          int                      `json:"id"`
	Type        string                   `json:"type"`
	Status      string                   `json:"status"`
	Target      string                   `json:"target"`
	Description string                   `json:"description"`
	Results     []map[string]interface{} `json:"results,omitempty"`
}

func NewAtlasClient(apiKey string) *AtlasClient {
	return &AtlasClient{
		apiKey: apiKey,
		httpClient: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

func (c *AtlasClient) CreateMeasurement(target string, def types.MeasurementDefinition) (int, error) {
	measurementDef := MeasurementDefinition{
		Target:      target,
		Description: fmt.Sprintf("Sintra measurement for %s", target),
		Type:        def.MeasurementType,
		AF:          4, // IPv4
		Interval:    def.IntervalSeconds,
		PacketSize:  def.PacketSize,
	}

	probeSet := ProbeSet{
		Type:      "probes",
		Value:     c.probesToString(def.ProbeIDs),
		Requested: len(def.ProbeIDs),
	}

	request := CreateMeasurementRequest{
		Definitions: []MeasurementDefinition{measurementDef},
		Probes:      []ProbeSet{probeSet},
	}

	jsonData, err := json.Marshal(request)
	if err != nil {
		return 0, fmt.Errorf("failed to marshal request: %w", err)
	}

	req, err := http.NewRequest("POST", baseURL+"/measurements/", bytes.NewBuffer(jsonData))
	if err != nil {
		return 0, fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Key "+c.apiKey)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return 0, fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return 0, fmt.Errorf("failed to read response: %w", err)
	}

	if resp.StatusCode != http.StatusCreated {
		return 0, fmt.Errorf("API request failed with status %d: %s", resp.StatusCode, string(body))
	}

	var response CreateMeasurementResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return 0, fmt.Errorf("failed to unmarshal response: %w", err)
	}

	if len(response.Measurements) == 0 {
		return 0, fmt.Errorf("no measurement ID returned")
	}

	return response.Measurements[0], nil
}

func (c *AtlasClient) FetchMeasurement(measurementID int) (*MeasurementResult, error) {
	url := fmt.Sprintf("%s/measurements/%d/", baseURL, measurementID)

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Authorization", "Key "+c.apiKey)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("API request failed with status %d: %s", resp.StatusCode, string(body))
	}

	var result MeasurementResult
	if err := json.Unmarshal(body, &result); err != nil {
		return nil, fmt.Errorf("failed to unmarshal response: %w", err)
	}

	return &result, nil
}

func (c *AtlasClient) probesToString(probeIDs []int) string {
	var strIDs []string
	for _, id := range probeIDs {
		strIDs = append(strIDs, strconv.Itoa(id))
	}
	return strings.Join(strIDs, ",")
}
