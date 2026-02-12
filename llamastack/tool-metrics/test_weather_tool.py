#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""
Test script for the custom weather tool that triggers llama-stack metrics.

This script:
1. Connects to llama-stack server (or uses library mode)
2. Invokes the weather tool multiple times
3. Generates metrics visible in Prometheus and Grafana

Usage:
    # Start monitoring stack first
    docker-compose up -d

    # Start llama-stack server with weather tool
    llama stack run weather-tool-config.yaml

    # Run this test
    python test_weather_tool.py
"""

import asyncio
import os
import random
import sys
import time
from datetime import datetime

# Determine which mode to use
USE_SERVER_MODE = os.environ.get("USE_SERVER_MODE", "true").lower() == "true"
LLAMA_STACK_URL = os.environ.get("LLAMA_STACK_URL", "http://localhost:5001")

# Add the project root to Python path for library mode
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, project_root)


class WeatherToolTester:
    """Test client for the weather tool."""

    def __init__(self):
        self.client = None
        self.mode = "HTTP Client (Server)" if USE_SERVER_MODE else "Library (Direct)"
        self.base_url = LLAMA_STACK_URL

    async def initialize(self):
        """Initialize the client connection."""
        if USE_SERVER_MODE:
            await self._init_http_client()
        else:
            await self._init_library_client()

    async def _init_http_client(self):
        """Initialize HTTP client to connect to llama-stack server."""
        from llama_stack_client import LlamaStackClient

        print(f"📡 Connecting to llama-stack server at {self.base_url}")
        self.client = LlamaStackClient(base_url=self.base_url)

        # Test connection
        try:
            if USE_SERVER_MODE:
                # For HTTP client, we can't easily test connection without making a call
                # Just set up the client and it will fail on first request if server is down
                print("✅ HTTP client initialized")
        except Exception as e:
            print(f"❌ Failed to connect to server: {e}")
            print(f"   Make sure llama-stack server is running at {self.base_url}")
            print("   Or set USE_SERVER_MODE=false to use library mode")
            raise

    async def _init_library_client(self):
        """Initialize library client (direct Python API)."""
        print("📚 Initializing library mode (no server needed)")

        # Import the weather tool provider
        from examples.metrics_demo.weather_tool import WeatherToolProvider

        # Create a minimal llama-stack library client with weather tool
        from llama_stack.core.library_client import LlamaStackAsLibraryClient

        # Create the weather tool provider instance
        weather_provider = WeatherToolProvider()
        await weather_provider.initialize()

        # Create library client with the weather provider
        self.client = LlamaStackAsLibraryClient(
            {
                "tool_runtime": weather_provider,
            }
        )
        print("✅ Library client initialized with weather tool")

    async def list_tools(self):
        """List available tools."""
        if USE_SERVER_MODE:
            result = self.client.tool_runtime.list_runtime_tools()
            return result.data
        else:
            result = await self.client.tool_runtime.list_runtime_tools()
            return result.data

    async def invoke_weather_tool(self, city: str, units: str = "celsius"):
        """
        Invoke the weather tool.

        Args:
            city: City name to get weather for
            units: Temperature units (celsius or fahrenheit)

        Returns:
            Tool invocation result
        """
        start_time = time.perf_counter()

        try:
            if USE_SERVER_MODE:
                result = self.client.tool_runtime.invoke_tool(
                    tool_name="get_weather",
                    kwargs={"city": city, "units": units},
                )
            else:
                result = await self.client.tool_runtime.invoke_tool(
                    tool_name="get_weather",
                    kwargs={"city": city, "units": units},
                )

            duration = time.perf_counter() - start_time

            if result.error_message:
                print(f"❌ get_weather({city}): {result.error_message} ({duration:.2f}s)")
                return False
            else:
                print(f"✅ get_weather({city}): {duration:.2f}s")
                if hasattr(result, "content") and result.content:
                    # Print first line of weather report
                    content_str = str(result.content)
                    first_line = content_str.split("\n")[0] if "\n" in content_str else content_str[:50]
                    print(f"   {first_line}")
                return True

        except Exception as e:
            duration = time.perf_counter() - start_time
            print(f"❌ get_weather({city}): {type(e).__name__}: {str(e)[:100]} ({duration:.2f}s)")
            return False

    async def run_weather_tests(
        self,
        duration_seconds: int = 120,
        requests_per_second: float = 1.0,
    ):
        """
        Run weather tool invocation tests.

        Args:
            duration_seconds: How long to run the test
            requests_per_second: Request rate
        """
        # Sample cities to test
        cities = [
            "San Francisco",
            "New York",
            "London",
            "Paris",
            "Tokyo",
            "Sydney",
            "Beijing",
            "Mumbai",
            "Cairo",
            "Rio de Janeiro",
        ]

        # Temperature units
        units_options = ["celsius", "fahrenheit"]

        total_requests = 0
        successful_requests = 0
        failed_requests = 0

        print()
        print("=" * 62)
        print("🚀 Starting weather tool invocation tests")
        print("=" * 62)
        print(f"Duration: {duration_seconds} seconds")
        print(f"Rate: {requests_per_second} requests/second")
        print(f"Total expected requests: ~{int(duration_seconds * requests_per_second)}")
        print()

        start_time = time.time()
        next_request_time = start_time
        last_status_time = start_time

        while True:
            current_time = time.time()
            elapsed = current_time - start_time

            # Check if we've exceeded the duration
            if elapsed >= duration_seconds:
                break

            # Print status every 10 seconds
            if current_time - last_status_time >= 10:
                success_rate = (successful_requests / total_requests * 100) if total_requests > 0 else 0
                print(
                    f"\n⏱️  {int(elapsed)}s | Requests: {total_requests} | "
                    f"Success: {successful_requests} | Failed: {failed_requests} | "
                    f"Rate: {success_rate:.1f}%"
                )
                last_status_time = current_time

            # Wait until it's time for the next request
            if current_time < next_request_time:
                await asyncio.sleep(0.1)
                continue

            # Schedule next request
            next_request_time += 1.0 / requests_per_second

            # Random city and units
            city = random.choice(cities)
            units = random.choice(units_options)

            # Invoke tool
            success = await self.invoke_weather_tool(city, units)

            total_requests += 1
            if success:
                successful_requests += 1
            else:
                failed_requests += 1

        # Final summary
        elapsed = time.time() - start_time
        success_rate = (successful_requests / total_requests * 100) if total_requests > 0 else 0
        avg_rate = total_requests / elapsed if elapsed > 0 else 0

        print()
        print("=" * 62)
        print("📊 Test Summary")
        print("=" * 62)
        print(f"Total time: {elapsed:.1f}s")
        print(f"Total requests: {total_requests}")
        print(f"Successful: {successful_requests}")
        print(f"Failed: {failed_requests}")
        print(f"Success rate: {success_rate:.1f}%")
        print(f"Average rate: {avg_rate:.2f} req/s")
        print()


async def main():
    """Main entry point."""
    print("=" * 62)
    print("🦙 Llama Stack - Weather Tool Metrics Test")
    print("=" * 62)
    print()

    # Check for OTLP configuration
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not otlp_endpoint:
        print("⚠️  Warning: OTEL_EXPORTER_OTLP_ENDPOINT not set")
        print("   Metrics will not be exported!")
        print()
        print("   Set environment variables:")
        print('   export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"')
        print('   export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"')
        print()
    else:
        print(f"✅ OTLP Export: {otlp_endpoint}")
        print()

    # Create tester
    tester = WeatherToolTester()

    print("🔧 Configuration:")
    print(f"   Mode: {tester.mode}")
    if USE_SERVER_MODE:
        print(f"   Server URL: {tester.base_url}")
    print()

    # Initialize
    try:
        await tester.initialize()
    except Exception as e:
        print()
        print("❌ Failed to initialize client")
        print(f"   Error: {e}")
        print()
        print("Make sure:")
        print("   1. Docker monitoring stack is running: docker-compose up -d")
        print("   2. Llama-stack server is running: llama stack run weather-tool-config.yaml")
        print("   3. Or use library mode: export USE_SERVER_MODE=false")
        sys.exit(1)

    # List tools
    print("📋 Listing available tools...")
    try:
        tools = await tester.list_tools()
        print(f"   Found {len(tools)} tool(s):")
        for tool in tools:
            print(f"   - {tool.name}: {tool.description}")
        print()
    except Exception as e:
        print(f"   ⚠️  Warning: Could not list tools: {e}")
        print()

    # Run tests
    try:
        await tester.run_weather_tests(
            duration_seconds=120,  # 2 minutes
            requests_per_second=1.0,  # 1 request per second
        )
    except KeyboardInterrupt:
        print()
        print("⏸️  Test interrupted by user")
        print()
    except Exception as e:
        print()
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    print()
    print("=" * 62)
    print("✅ Test completed!")
    print("=" * 62)
    print()
    print("View metrics at:")
    print("   📊 Prometheus: http://localhost:9090")
    print("   📈 Grafana:    http://localhost:3000 (admin/admin)")
    print()
    print("Example PromQL queries:")
    print('   - llama_stack_tool_runtime_invocations_total{tool_name="get_weather"}')
    print('   - rate(llama_stack_tool_runtime_invocations_total{tool_name="get_weather"}[1m])')
    print('   - histogram_quantile(0.95, rate(llama_stack_tool_runtime_duration_seconds_bucket{tool_name="get_weather"}[1m]))')
    print()


if __name__ == "__main__":
    asyncio.run(main())
