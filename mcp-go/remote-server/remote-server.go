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
	// Create a new MCP server
	s := server.NewMCPServer(
		"Calculator Demo",
		"1.0.0",
		server.WithResourceCapabilities(true, true),
		server.WithLogging(),
	)

	// Add a calculator tool
	calculatorTool := mcp.NewTool("calculate",
		mcp.WithDescription("Perform basic arithmetic operations"),
		mcp.WithString("operation",
			mcp.Required(),
			mcp.Description("The operation to perform (add, subtract, multiply, divide)"),
			mcp.Enum("add", "subtract", "multiply", "divide"),
		),
		mcp.WithNumber("x",
			mcp.Required(),
			mcp.Description("First number"),
		),
		mcp.WithNumber("y",
			mcp.Required(),
			mcp.Description("Second number"),
		),
	)

	// Add the calculator handler
	s.AddTool(calculatorTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		op := request.Params.Arguments["operation"].(string)
		x := request.Params.Arguments["x"].(float64)
		y := request.Params.Arguments["y"].(float64)

		var result float64
		switch op {
		case "add":
			result = x + y
		case "subtract":
			result = x - y
		case "multiply":
			result = x * y
		case "divide":
			if y == 0 {
				return nil, errors.New("Cannot divide by zero")
			}
			result = x / y
		}

		return mcp.NewToolResultText(fmt.Sprintf("%.2f", result)), nil
	})

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
