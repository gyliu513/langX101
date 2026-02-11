#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""
Generate sample tool runtime metrics for testing.

This script simulates tool invocations to generate metrics that can be
visualized in Prometheus and Grafana.
"""

import asyncio
import random
import time
from unittest.mock import AsyncMock, MagicMock

from llama_stack.core.routers.tool_runtime import ToolRuntimeRouter
from llama_stack_api import ToolInvocationResult


class MetricsGenerator:
    """Generates sample metrics by simulating tool invocations."""

    def __init__(self):
        self.router = self._create_mock_router()
        self.iteration = 0

    def _create_mock_router(self) -> ToolRuntimeRouter:
        """Create a mock ToolRuntimeRouter with simulated providers."""
        mock_routing_table = MagicMock()
        mock_routing_table.tool_to_toolgroup = {
            "web_search": "websearch",
            "brave_search": "websearch",
            "tavily_search": "websearch",
            "rag_query": "rag_tool",
        }

        # Create providers with different behaviors
        self.providers = {
            "brave-search::impl": self._create_provider("brave-search::impl", success_rate=0.95, latency=(0.5, 1.5)),
            "tavily-search::impl": self._create_provider("tavily-search::impl", success_rate=0.90, latency=(0.8, 2.0)),
            "rag-runtime::impl": self._create_provider("rag-runtime::impl", success_rate=0.98, latency=(0.2, 0.8)),
        }

        # Route tools to providers
        self.tool_provider_map = {
            "web_search": "brave-search::impl",
            "brave_search": "brave-search::impl",
            "tavily_search": "tavily-search::impl",
            "rag_query": "rag-runtime::impl",
        }

        async def get_provider_impl(tool_name: str):
            provider_id = self.tool_provider_map.get(tool_name, "brave-search::impl")
            return self.providers[provider_id]

        mock_routing_table.get_provider_impl = get_provider_impl

        return ToolRuntimeRouter(routing_table=mock_routing_table)

    def _create_provider(self, provider_id: str, success_rate: float, latency: tuple):
        """Create a mock provider with configurable success rate and latency."""
        provider = AsyncMock()
        provider.__provider_id__ = provider_id

        async def invoke_tool(tool_name: str, kwargs: dict, authorization: str = None):
            # Simulate latency
            min_latency, max_latency = latency
            await asyncio.sleep(random.uniform(min_latency, max_latency))

            # Simulate failures
            if random.random() > success_rate:
                raise ValueError(f"Simulated error for {tool_name}")

            return ToolInvocationResult(
                content=f"Simulated result for {tool_name} with {kwargs}"
            )

        provider.invoke_tool = invoke_tool
        return provider

    async def generate_metrics(self, duration_seconds: int = 300, requests_per_second: float = 2.0):
        """
        Generate metrics by simulating tool invocations.

        Args:
            duration_seconds: How long to generate metrics for
            requests_per_second: Target rate of tool invocations per second
        """
        print(f"🚀 Starting metrics generation for {duration_seconds} seconds")
        print(f"📊 Target rate: {requests_per_second} requests/second")
        print(f"💡 Total expected requests: ~{int(duration_seconds * requests_per_second)}")
        print()

        start_time = time.time()
        end_time = start_time + duration_seconds

        tools = ["web_search", "brave_search", "tavily_search", "rag_query"]
        total_requests = 0
        successful_requests = 0
        failed_requests = 0

        while time.time() < end_time:
            iteration_start = time.time()

            # Simulate multiple concurrent requests
            tasks = []
            for _ in range(int(requests_per_second)):
                tool_name = random.choice(tools)
                task = self._invoke_tool(tool_name)
                tasks.append(task)

            # Wait for all tasks to complete
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Count successes and failures
            for result in results:
                total_requests += 1
                if isinstance(result, Exception):
                    failed_requests += 1
                else:
                    successful_requests += 1

            # Progress update every 10 seconds
            elapsed = time.time() - start_time
            if int(elapsed) % 10 == 0 and int(elapsed) != self.iteration:
                self.iteration = int(elapsed)
                success_rate = (successful_requests / total_requests * 100) if total_requests > 0 else 0
                print(f"⏱️  {int(elapsed)}s | Requests: {total_requests} | Success: {successful_requests} | Failed: {failed_requests} | Rate: {success_rate:.1f}%")

            # Sleep to maintain target rate
            iteration_duration = time.time() - iteration_start
            sleep_time = max(0, 1.0 - iteration_duration)
            await asyncio.sleep(sleep_time)

        # Final summary
        total_duration = time.time() - start_time
        actual_rps = total_requests / total_duration
        success_rate = (successful_requests / total_requests * 100) if total_requests > 0 else 0

        print()
        print("=" * 60)
        print("✅ Metrics Generation Complete!")
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

    async def _invoke_tool(self, tool_name: str):
        """Invoke a tool and handle errors gracefully."""
        try:
            result = await self.router.invoke_tool(
                tool_name=tool_name,
                kwargs={"query": f"test query {random.randint(1, 1000)}"},
                authorization=None,
            )
            return result
        except Exception as e:
            # Errors are already recorded in metrics
            return e


async def main():
    """Main entry point."""
    print()
    print("=" * 60)
    print("🦙 Llama Stack - Tool Runtime Metrics Generator")
    print("=" * 60)
    print()
    print("This script will generate sample tool runtime metrics")
    print("by simulating tool invocations with various success rates")
    print("and latencies.")
    print()
    print("Make sure you have:")
    print("  1. Docker Compose stack running (docker-compose up -d)")
    print("  2. Environment variables configured:")
    print("     export OTEL_EXPORTER_OTLP_ENDPOINT='http://localhost:4318'")
    print("     export OTEL_EXPORTER_OTLP_PROTOCOL='http/protobuf'")
    print("     export OTEL_METRIC_EXPORT_INTERVAL='5000'")
    print()

    # Check if OTLP endpoint is configured
    import os
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        print("⚠️  Warning: OTEL_EXPORTER_OTLP_ENDPOINT not set!")
        print("   Metrics will NOT be exported to Prometheus/Grafana")
        print()
        response = input("Continue anyway? (y/N): ")
        if response.lower() != 'y':
            print("Exiting...")
            return
        print()

    generator = MetricsGenerator()

    try:
        # Generate metrics for 5 minutes at 2 requests/second
        # This will create ~600 total requests
        await generator.generate_metrics(
            duration_seconds=300,  # 5 minutes
            requests_per_second=2.0
        )
    except KeyboardInterrupt:
        print()
        print("⚠️  Interrupted by user")
        print()


if __name__ == "__main__":
    asyncio.run(main())
