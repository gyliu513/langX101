#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""
Simple weather tool provider for demonstrating llama-stack tool runtime metrics.

This is a mock implementation that returns simulated weather data.
In production, you would integrate with a real weather API like OpenWeatherMap.
"""

import random
from typing import Any

from llama_stack_api import (
    ListToolDefsResponse,
    ToolDef,
    ToolGroup,
    ToolGroupsProtocolPrivate,
    ToolInvocationResult,
    ToolRuntime,
    URL,
)


class WeatherToolProvider(ToolGroupsProtocolPrivate, ToolRuntime):
    """A simple weather tool provider that returns mock weather data."""

    def __init__(self):
        self.tool_name = "get_weather"
        self.toolgroup_id = "weather"

    async def initialize(self):
        """Initialize the weather tool provider."""
        pass

    async def shutdown(self):
        """Shutdown the weather tool provider."""
        pass

    async def register_toolgroup(self, toolgroup: ToolGroup) -> None:
        """Register a tool group (no-op for this simple provider)."""
        pass

    async def unregister_toolgroup(self, toolgroup_id: str) -> None:
        """Unregister a tool group (no-op for this simple provider)."""
        pass

    async def list_runtime_tools(
        self,
        tool_group_id: str | None = None,
        mcp_endpoint: URL | None = None,
        authorization: str | None = None,
    ) -> ListToolDefsResponse:
        """List available tools in this provider."""
        return ListToolDefsResponse(
            data=[
                ToolDef(
                    toolgroup_id=self.toolgroup_id,
                    name=self.tool_name,
                    description="Get current weather information for a city",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "city": {
                                "type": "string",
                                "description": "The city name to get weather for (e.g., 'San Francisco', 'New York')",
                            },
                            "units": {
                                "type": "string",
                                "enum": ["celsius", "fahrenheit"],
                                "description": "Temperature unit (celsius or fahrenheit). Defaults to celsius.",
                            },
                        },
                        "required": ["city"],
                    },
                    output_schema={
                        "type": "object",
                        "properties": {
                            "city": {"type": "string"},
                            "temperature": {"type": "number"},
                            "units": {"type": "string"},
                            "condition": {"type": "string"},
                            "humidity": {"type": "integer"},
                            "wind_speed": {"type": "number"},
                        },
                    },
                )
            ]
        )

    async def invoke_tool(
        self, tool_name: str, kwargs: dict[str, Any], authorization: str | None = None
    ) -> ToolInvocationResult:
        """
        Invoke the weather tool.

        Args:
            tool_name: The name of the tool to invoke (should be "get_weather")
            kwargs: Tool arguments containing "city" and optionally "units"
            authorization: Optional authorization token (not used in this mock)

        Returns:
            ToolInvocationResult with weather data
        """
        if tool_name != self.tool_name:
            return ToolInvocationResult(
                error_message=f"Unknown tool: {tool_name}",
                error_code=404,
            )

        city = kwargs.get("city")
        if not city:
            return ToolInvocationResult(
                error_message="Missing required parameter: city",
                error_code=400,
            )

        units = kwargs.get("units", "celsius")
        if units not in ["celsius", "fahrenheit"]:
            return ToolInvocationResult(
                error_message=f"Invalid units: {units}. Must be 'celsius' or 'fahrenheit'",
                error_code=400,
            )

        # Generate mock weather data
        weather_data = self._get_mock_weather(city, units)

        return ToolInvocationResult(
            content=weather_data,
            metadata={
                "provider": "weather-tool-mock",
                "tool_name": tool_name,
            },
        )

    def _get_mock_weather(self, city: str, units: str) -> str:
        """Generate mock weather data for a city."""
        # Mock weather conditions
        conditions = ["Sunny", "Partly Cloudy", "Cloudy", "Rainy", "Stormy", "Snowy", "Foggy"]
        condition = random.choice(conditions)

        # Generate temperature based on units
        if units == "celsius":
            temp = round(random.uniform(-5, 35), 1)
            temp_unit = "°C"
        else:  # fahrenheit
            temp = round(random.uniform(23, 95), 1)
            temp_unit = "°F"

        humidity = random.randint(30, 95)
        wind_speed = round(random.uniform(0, 30), 1)

        # Format weather report
        weather_report = f"""Weather in {city}:
Temperature: {temp}{temp_unit}
Condition: {condition}
Humidity: {humidity}%
Wind Speed: {wind_speed} km/h"""

        return weather_report
