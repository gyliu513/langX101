package main

import (
	"context"
	"errors"
	"fmt"
	"log"
	"net/http"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
)

// main initializes and starts the MCP calculator server with various arithmetic operations
func main() {
	// Create MCP server
	s := server.NewMCPServer(
		"Calculator",
		"1.0.0",
	)

	// Add addition tool
	add := mcp.NewTool("add",
		mcp.WithDescription("Add two numbers"),
		mcp.WithNumber("a",
			mcp.Required(),
			mcp.Description("First number"),
		),
		mcp.WithNumber("b",
			mcp.Required(),
			mcp.Description("Second number"),
		),
	)

	// Add subtraction tool
	subtract := mcp.NewTool("subtract",
		mcp.WithDescription("Subtract second number from first number"),
		mcp.WithNumber("a",
			mcp.Required(),
			mcp.Description("First number"),
		),
		mcp.WithNumber("b",
			mcp.Required(),
			mcp.Description("Second number"),
		),
	)

	// Add multiplication tool
	multiply := mcp.NewTool("multiply",
		mcp.WithDescription("Multiply two numbers"),
		mcp.WithNumber("a",
			mcp.Required(),
			mcp.Description("First number"),
		),
		mcp.WithNumber("b",
			mcp.Required(),
			mcp.Description("Second number"),
		),
	)

	// Add division tool
	divide := mcp.NewTool("divide",
		mcp.WithDescription("Divide first number by second number"),
		mcp.WithNumber("a",
			mcp.Required(),
			mcp.Description("Numerator"),
		),
		mcp.WithNumber("b",
			mcp.Required(),
			mcp.Description("Denominator"),
		),
	)

	// Add percentage tool
	percentage := mcp.NewTool("percentage",
		mcp.WithDescription("Calculate what percentage the first number is of the second number"),
		mcp.WithNumber("a",
			mcp.Required(),
			mcp.Description("Part value"),
		),
		mcp.WithNumber("b",
			mcp.Required(),
			mcp.Description("Total value"),
		),
	)

	// Add tool handlers
	s.AddTool(add, addHandler)
	s.AddTool(subtract, subtractHandler)
	s.AddTool(multiply, multiplyHandler)
	s.AddTool(divide, divideHandler)
	s.AddTool(percentage, percentageHandler)

	// Start the HTTP server using SSE
	port := 8080
	fmt.Printf("Starting MCP Calculator server on port %d...\n", port)

	// Create an SSE server with custom options
	sseServer := server.NewSSEServer(s,
		server.WithBasePath("/"),
		server.WithSSEEndpoint("/mcp/sse"),
		server.WithMessageEndpoint("/mcp/message"),
	)

	// Create a mux to handle different routes
	mux := http.NewServeMux()

	// Register the SSE server handler
	mux.Handle("/", sseServer)

	// Create an HTTP server
	httpServer := &http.Server{
		Addr:    fmt.Sprintf(":%d", port),
		Handler: mux,
	}

	// Print available endpoints
	fmt.Printf("SSE Endpoint: %s\n", sseServer.CompleteSsePath())
	fmt.Printf("Message Endpoint: %s\n", sseServer.CompleteMessagePath())

	// Start the server
	if err := httpServer.ListenAndServe(); err != nil {
		log.Fatalf("Server error: %v\n", err)
	}
}

// addHandler processes addition requests, adding two numbers and returning the formatted result
// Returns an error if inputs are not valid numbers
func addHandler(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	a, ok := request.Params.Arguments["a"].(float64)
	if !ok {
		return nil, errors.New("first number must be a number")
	}

	b, ok := request.Params.Arguments["b"].(float64)
	if !ok {
		return nil, errors.New("second number must be a number")
	}

	result := a + b
	return mcp.NewToolResultText(fmt.Sprintf("%.2f", result)), nil
}

// subtractHandler processes subtraction requests, subtracting the second number from the first
// Returns an error if inputs are not valid numbers
func subtractHandler(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	a, ok := request.Params.Arguments["a"].(float64)
	if !ok {
		return nil, errors.New("first number must be a number")
	}

	b, ok := request.Params.Arguments["b"].(float64)
	if !ok {
		return nil, errors.New("second number must be a number")
	}

	result := a - b
	return mcp.NewToolResultText(fmt.Sprintf("%.2f", result)), nil
}

// multiplyHandler processes multiplication requests, multiplying two numbers together
// Returns an error if inputs are not valid numbers
func multiplyHandler(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	a, ok := request.Params.Arguments["a"].(float64)
	if !ok {
		return nil, errors.New("first number must be a number")
	}

	b, ok := request.Params.Arguments["b"].(float64)
	if !ok {
		return nil, errors.New("second number must be a number")
	}

	result := a * b
	return mcp.NewToolResultText(fmt.Sprintf("%.2f", result)), nil
}

// divideHandler processes division requests, dividing the first number by the second
// Returns an error if inputs are not valid numbers or if dividing by zero
func divideHandler(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	a, ok := request.Params.Arguments["a"].(float64)
	if !ok {
		return nil, errors.New("numerator must be a number")
	}

	b, ok := request.Params.Arguments["b"].(float64)
	if !ok {
		return nil, errors.New("denominator must be a number")
	}

	if b == 0 {
		return nil, errors.New("cannot divide by zero")
	}

	result := a / b
	return mcp.NewToolResultText(fmt.Sprintf("%.2f", result)), nil
}

// percentageHandler calculates what percentage the first number is of the second number
// Returns an error if inputs are not valid numbers or if the total value is zero
func percentageHandler(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	a, ok := request.Params.Arguments["a"].(float64)
	if !ok {
		return nil, errors.New("part value must be a number")
	}

	b, ok := request.Params.Arguments["b"].(float64)
	if !ok {
		return nil, errors.New("total value must be a number")
	}

	if b == 0 {
		return nil, errors.New("total value cannot be zero")
	}

	result := (a / b) * 100
	return mcp.NewToolResultText(fmt.Sprintf("%.2f%%", result)), nil
}
