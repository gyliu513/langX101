#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""
Test script to call real llama-stack Tool Runtime API and generate metrics.

This script can work in two modes:
1. HTTP Client Mode: Connect to a running llama-stack server (recommended)
2. Library Mode: Use llama-stack as a library (no server needed)
"""

import asyncio
import json
import os
import random
import time
from typing import Optional

# Check if running against a server or as library
LLAMA_STACK_URL = os.getenv("LLAMA_STACK_URL", "http://localhost:5001")
USE_SERVER_MODE = os.getenv("USE_SERVER_MODE", "true").lower() == "true"


class ToolRuntimeTester:
    """Test real tool runtime API calls."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or LLAMA_STACK_URL
        self.client = None
        self.available_tools = []

    async def initialize(self):
        """Initialize the client."""
        if USE_SERVER_MODE:
            await self._init_http_client()
        else:
            await self._init_library_client()

        # List available tools
        await self._list_tools()

    async def _init_http_client(self):
        """Initialize HTTP client for server mode."""
        print(f"📡 Connecting to llama-stack server at {self.base_url}")

        try:
            from llama_stack_client import LlamaStackClient

            self.client = LlamaStackClient(base_url=self.base_url)

            # Test connection
            health = self.client.health()
            if health.status == "ok":
                print(f"✅ Connected to server successfully")
            else:
                print(f"⚠️  Server health check returned: {health.status}")

        except Exception as e:
            print(f"❌ Failed to connect to server: {e}")
            print(f"\n💡 Make sure llama-stack server is running:")
            print(f"   llama stack run <your-config>")
            print(f"   Or set USE_SERVER_MODE=false to use library mode")
            raise

    async def _init_library_client(self):
        """Initialize library client (direct API usage without server)."""
        print("📚 Using llama-stack as a library (no server needed)")

        try:
            from llama_stack.core.library_client import LlamaStackAsLibraryClient
            from llama_stack.core.stack import run_config_from_adhoc_config_spec

            # Create a minimal config with tool runtime
            config_spec = {
                "providers": {
                    "tool_runtime": {
                        "brave-search": {
                            "provider_type": "remote::brave-search",
                            "config": {
                                "api_key": "${env.BRAVE_SEARCH_API_KEY:}",
                            }
                        }
                    }
                }
            }

            config = await run_config_from_adhoc_config_spec(config_spec)
            self.client = LlamaStackAsLibraryClient(config)
            await self.client.initialize()

            print("✅ Library client initialized")

        except Exception as e:
            print(f"❌ Failed to initialize library client: {e}")
            raise

    async def _list_tools(self):
        """List all available tools."""
        try:
            if USE_SERVER_MODE:
                # HTTP client
                response = self.client.tool_runtime.list_tools()
                self.available_tools = response.data if hasattr(response, 'data') else response
            else:
                # Library client
                response = await self.client.tool_runtime.list_runtime_tools()
                self.available_tools = response.data

            print(f"\n📋 Available tools: {len(self.available_tools)}")
            for tool in self.available_tools:
                print(f"   - {tool.name} ({tool.toolgroup_id})")

        except Exception as e:
            print(f"⚠️  Could not list tools: {e}")
            self.available_tools = []

    async def invoke_tool(self, tool_name: str, kwargs: dict) -> dict:
        """Invoke a tool and return the result."""
        try:
            start_time = time.time()

            if USE_SERVER_MODE:
                # HTTP client (synchronous)
                result = self.client.tool_runtime.invoke_tool(
                    tool_name=tool_name,
                    kwargs=kwargs
                )
            else:
                # Library client (async)
                result = await self.client.tool_runtime.invoke_tool(
                    tool_name=tool_name,
                    kwargs=kwargs
                )

            duration = time.time() - start_time

            return {
                "success": True,
                "tool_name": tool_name,
                "duration": duration,
                "result": result,
            }

        except Exception as e:
            duration = time.time() - start_time
            return {
                "success": False,
                "tool_name": tool_name,
                "duration": duration,
                "error": str(e),
            }

    async def run_tool_tests(self, duration_seconds: int = 60, requests_per_second: float = 1.0):
        """Run continuous tool tests to generate metrics."""
        print(f"\n{'='*60}")
        print(f"🚀 Starting tool invocation tests")
        print(f"{'='*60}")
        print(f"Duration: {duration_seconds} seconds")
        print(f"Rate: {requests_per_second} requests/second")
        print(f"Total expected requests: ~{int(duration_seconds * requests_per_second)}")
        print()

        if not self.available_tools:
            print("❌ No tools available to test!")
            print("\n💡 Make sure you have tools configured:")
            print("   - brave-search (requires BRAVE_SEARCH_API_KEY)")
            print("   - tavily-search (requires TAVILY_SEARCH_API_KEY)")
            print("   - wolfram-alpha (requires WOLFRAM_ALPHA_API_KEY)")
            return

        # Prepare test queries for different tools
        test_queries = {
            "web_search": [
                "latest AI developments",
                "quantum computing news",
                "climate change solutions",
                "space exploration updates",
                "renewable energy technology",
            ],
            "brave_search": [
                "machine learning breakthroughs",
                "blockchain technology",
                "artificial general intelligence",
            ],
            "tavily_search": [
                "tech industry trends",
                "cybersecurity threats",
            ],
            "wolfram_alpha": [
                "integrate x^2",
                "population of USA",
                "weather in New York",
            ],
        }

        start_time = time.time()
        end_time = start_time + duration_seconds

        total_requests = 0
        successful_requests = 0
        failed_requests = 0
        iteration = 0

        while time.time() < end_time:
            iteration_start = time.time()

            # Select a random available tool
            tool = random.choice(self.available_tools)
            tool_name = tool.name

            # Get appropriate test query
            queries = test_queries.get(tool_name, ["test query"])
            query = random.choice(queries)

            # Invoke the tool
            result = await self.invoke_tool(tool_name, {"query": query})

            total_requests += 1
            if result["success"]:
                successful_requests += 1
                print(f"✅ {tool_name}: {result['duration']:.2f}s")
            else:
                failed_requests += 1
                print(f"❌ {tool_name}: {result.get('error', 'Unknown error')}")

            # Progress update every 10 seconds
            elapsed = time.time() - start_time
            if int(elapsed) % 10 == 0 and int(elapsed) != iteration:
                iteration = int(elapsed)
                success_rate = (successful_requests / total_requests * 100) if total_requests > 0 else 0
                print(f"\n⏱️  {int(elapsed)}s | Requests: {total_requests} | Success: {successful_requests} | Failed: {failed_requests} | Rate: {success_rate:.1f}%\n")

            # Sleep to maintain target rate
            iteration_duration = time.time() - iteration_start
            sleep_time = max(0, 1.0 / requests_per_second - iteration_duration)
            await asyncio.sleep(sleep_time)

        # Final summary
        total_duration = time.time() - start_time
        actual_rps = total_requests / total_duration
        success_rate = (successful_requests / total_requests * 100) if total_requests > 0 else 0

        print()
        print("=" * 60)
        print("✅ Tool Invocation Tests Complete!")
        print("=" * 60)
        print(f"Duration: {total_duration:.1f} seconds")
        print(f"Total Requests: {total_requests}")
        print(f"Successful: {successful_requests} ({success_rate:.1f}%)")
        print(f"Failed: {failed_requests} ({100 - success_rate:.1f}%)")
        print(f"Actual Rate: {actual_rps:.2f} requests/second")
        print()
        print("📊 View metrics at:")
        print("   - Prometheus: http://localhost:9090")
        print("   - Grafana: http://localhost:3000")
        print("=" * 60)


async def main():
    """Main entry point."""
    print()
    print("=" * 60)
    print("🦙 Llama Stack - Real Tool Runtime Metrics Test")
    print("=" * 60)
    print()

    # Check environment variables
    print("🔧 Configuration:")
    print(f"   Mode: {'HTTP Client (Server)' if USE_SERVER_MODE else 'Library Client'}")
    if USE_SERVER_MODE:
        print(f"   Server URL: {LLAMA_STACK_URL}")
    print()

    # Check OTLP configuration
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        print(f"✅ OTLP Export: {otlp_endpoint}")
    else:
        print("⚠️  OTLP_EXPORTER_OTLP_ENDPOINT not set - metrics will NOT be exported")
        print("   Set it with: export OTEL_EXPORTER_OTLP_ENDPOINT='http://localhost:4318'")

    print()

    # Initialize tester
    tester = ToolRuntimeTester()
    await tester.initialize()

    # Run tests
    try:
        # Run for 2 minutes at 1 request per second
        # This will create ~120 requests
        await tester.run_tool_tests(
            duration_seconds=120,  # 2 minutes
            requests_per_second=1.0
        )
    except KeyboardInterrupt:
        print()
        print("⚠️  Interrupted by user")
        print()


if __name__ == "__main__":
    asyncio.run(main())
