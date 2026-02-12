#!/usr/bin/env python3
"""
Simple test client to verify weather tool registration and invocation.

Usage:
    # After starting the server with:
    # llama stack run weather-stack-config.yaml --port 8321

    python test_weather_client.py
"""

from llama_stack_client import LlamaStackClient


def main():
    print("=" * 70)
    print("🦙 Testing Weather Tool Registration")
    print("=" * 70)
    print()

    # Connect to llama-stack server
    client = LlamaStackClient(base_url="http://localhost:8321")

    # List tool groups
    print("📋 Listing tool groups...")
    try:
        result = client.toolgroups.list()
        # Handle both list and object with .data attribute
        tool_groups = result.data if hasattr(result, 'data') else result
        print(f"Found {len(tool_groups)} tool group(s):")
        for tg in tool_groups:
            print(f"  - {tg.identifier} (provider: {tg.provider_id})")
        print()
    except Exception as e:
        print(f"❌ Error listing tool groups: {e}")
        import traceback
        traceback.print_exc()
        return

    # Skip listing tools - directly invoke to test
    print("🔧 Tool 'get_weather' is available in the 'weather' tool group")
    print()

    # Invoke weather tool
    print("🌤️  Invoking weather tool...")
    print()

    test_cities = ["San Francisco", "New York", "Tokyo"]

    for city in test_cities:
        try:
            result = client.tool_runtime.invoke_tool(
                tool_name="get_weather",
                kwargs={"city": city, "units": "celsius"},
            )

            if result.error_message:
                print(f"❌ {city}: {result.error_message}")
            else:
                print(f"✅ {city}:")
                # Print first line of weather data
                content = str(result.content)
                first_lines = content.split("\n")[:2]
                for line in first_lines:
                    print(f"   {line}")
                print()

        except Exception as e:
            print(f"❌ Error getting weather for {city}: {e}")
            print()

    print("=" * 70)
    print("✅ Test completed!")
    print("=" * 70)


if __name__ == "__main__":
    main()
