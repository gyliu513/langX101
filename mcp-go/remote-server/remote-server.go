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
		// server.WithResourceCapabilities(true, true),
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
		log.Printf("📥 Tool called with request: %+v\n", request)
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

	// Print all HTTP request header
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		log.Println("🔍 Incoming request:", r.Method, r.URL.Path)
		log.Println("🔍 Headers:", r.Header)

		// Handover to sseServer
		sseServer.ServeHTTP(w, r)
	})

	// Register the SSE server handler
	// mux.Handle("/", sseServer)

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
