#!/usr/bin/env python3
"""
Test script to invoke Tavily web search tool and generate metrics.

This script:
1. Calls the web_search tool (tavily-search provider)
2. Generates tool runtime metrics that can be exported to Prometheus/Grafana
3. Displays search results

Prerequisites:
- Server must be running with tavily-search tool configured
- TAVILY_SEARCH_API_KEY environment variable must be set
- OpenTelemetry configured for metrics export (optional, for metrics collection)

Usage:
    # Start server with metrics (optional):
    export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
    export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"

    # Set Tavily API key:
    export TAVILY_SEARCH_API_KEY="your-api-key"

    # Run the test:
    python test_websearch_metrics.py
"""

import json
import os
from llama_stack_client import LlamaStackClient


def main():
    print("=" * 70)
    print("🔍 Testing Tavily Web Search Tool with Metrics")
    print("=" * 70)
    print()

    # Check for API key
    api_key = os.getenv("TAVILY_SEARCH_API_KEY")
    if not api_key:
        print("❌ Error: TAVILY_SEARCH_API_KEY environment variable not set")
        print()
        print("Please set your Tavily API key:")
        print("   export TAVILY_SEARCH_API_KEY='your-api-key-here'")
        print()
        print("Get a free API key at: https://tavily.com")
        return

    # Connect to llama-stack server
    client = LlamaStackClient(base_url="http://localhost:8321")

    # List tool groups to verify web search is available
    print("📋 Listing tool groups...")
    try:
        result = client.toolgroups.list()
        tool_groups = result.data if hasattr(result, 'data') else result
        print(f"Found {len(tool_groups)} tool group(s):")

        websearch_found = False
        for tg in tool_groups:
            print(f"  - {tg.identifier} (provider: {tg.provider_id})")
            if tg.identifier in ["builtin::websearch", "websearch", "tavily-search"]:
                websearch_found = True

        if not websearch_found:
            print()
            print("⚠️  Warning: Web search tool group not found!")
            print("   Make sure your server config includes tavily-search provider")
        print()
    except Exception as e:
        print(f"❌ Error listing tool groups: {e}")
        import traceback
        traceback.print_exc()
        return

    # Define test queries
    test_queries = [
        "latest news about artificial intelligence",
        "python programming best practices 2025",
        "what is llama stack framework",
    ]

    print("🔎 Invoking web_search tool...")
    print()

    for i, query in enumerate(test_queries, 1):
        print(f"Query {i}: {query}")
        print("-" * 70)

        try:
            # Invoke the web_search tool
            # Note: tool_name is "web_search" (from tavily_search.py:59)
            result = client.tool_runtime.invoke_tool(
                tool_name="web_search",
                kwargs={"query": query},
            )

            if result.error_message:
                print(f"❌ Error: {result.error_message}")
            else:
                # Parse and display results
                try:
                    content = json.loads(str(result.content))
                    print(f"✅ Search successful!")
                    print(f"   Query: {content.get('query', 'N/A')}")

                    results = content.get('top_k', [])
                    print(f"   Found {len(results)} results:")

                    for idx, res in enumerate(results[:3], 1):  # Show top 3
                        title = res.get('title', 'No title')
                        url = res.get('url', 'No URL')
                        print(f"   {idx}. {title}")
                        print(f"      URL: {url}")
                except (json.JSONDecodeError, AttributeError) as e:
                    print(f"✅ Search successful (raw response):")
                    print(f"   {str(result.content)[:200]}...")

        except Exception as e:
            print(f"❌ Error during search: {e}")
            import traceback
            traceback.print_exc()

        print()

    print("=" * 70)
    print("✅ Test completed!")
    print("=" * 70)
    print()
    print("📊 Metrics Information:")
    print("   Tool invocations have been recorded with the following labels:")
    print("   - tool_group: builtin::websearch (or websearch)")
    print("   - tool_name: web_search")
    print("   - provider: tavily-search provider ID")
    print("   - status: success/error")
    print()
    print("   If OpenTelemetry is configured, metrics are exported to:")
    print("   - Prometheus: http://localhost:9090")
    print("   - Grafana: http://localhost:3000")
    print()
    print("   Sample PromQL queries:")
    print('   - llama_stack_tool_runtime_invocations_total{tool_name="web_search"}')
    print('   - rate(llama_stack_tool_runtime_invocations_total{tool_name="web_search"}[5m])')
    print('   - llama_stack_tool_runtime_duration_bucket{tool_name="web_search"}')
    print()


if __name__ == "__main__":
    main()


```
======================================================================
🔍 Testing Tavily Web Search Tool with Metrics
======================================================================

📋 Listing tool groups...
/Users/gualiu/go/src/github.com/llamastack/llama-stack/test_websearch_metrics.py:55: DeprecationWarning: deprecated
  result = client.toolgroups.list()
INFO:httpx:HTTP Request: GET http://localhost:8321/v1/toolgroups "HTTP/1.1 200 OK"
Found 2 tool group(s):
  - builtin::rag (provider: rag-runtime)
  - builtin::websearch (provider: tavily-search)

🔎 Invoking web_search tool...

Query 1: latest news about artificial intelligence
----------------------------------------------------------------------
/Users/gualiu/go/src/github.com/llamastack/llama-stack/test_websearch_metrics.py:93: DeprecationWarning: deprecated
  result = client.tool_runtime.invoke_tool(
INFO:httpx:HTTP Request: POST http://localhost:8321/v1/tool-runtime/invoke "HTTP/1.1 200 OK"
✅ Search successful!
   Query: latest news about artificial intelligence
   Found 5 results:
   1. Artificial Intelligence - Latest AI News and Analysis - WSJ.com
      URL: https://www.wsj.com/tech/ai?gaa_at=eafs&gaa_n=AWEtsqfSOvvYif5VFedKk-5vQ99QKMxs-68DghfTdmrohEzTlSUuxQ8hl1KX&gaa_ts=698e80b2&gaa_sig=MZjZtEh67bTo7H5wJ0ARdjQ76FVKcMDmkJK3NKR9FfGOQFwi00osQS4NOzc2XVydrAgaprnYLKAWSpkKVzv4eg%3D%3D
   2. Artificial intelligence - NBC News
      URL: https://www.nbcnews.com/artificial-intelligence
   3. AI News | Latest Headlines and Developments | Reuters
      URL: https://www.reuters.com/technology/artificial-intelligence/

Query 2: python programming best practices 2025
----------------------------------------------------------------------
INFO:httpx:HTTP Request: POST http://localhost:8321/v1/tool-runtime/invoke "HTTP/1.1 200 OK"
✅ Search successful!
   Query: python programming best practices 2025
   Found 5 results:
   1. Mastering Python in 2025: Comprehensive Tips and Best Practices ...
      URL: https://medium.com/@TheEnaModernCoder/mastering-python-in-2025-comprehensive-tips-and-best-practices-for-writing-clean-efficient-996bbc081c91
   2. 7 “Bad” Python Habits to Break in 2025 | by Aman Kardam (PhD)
      URL: https://levelup.gitconnected.com/7-bad-python-habits-to-break-in-2025-5257efbc3bef
   3. 10 Python Mistakes You Might Still Be Making in 2025
      URL: https://python.plainenglish.io/10-python-mistakes-you-might-still-be-making-in-2025-fbb6d4435373

Query 3: what is llama stack framework
----------------------------------------------------------------------
INFO:httpx:HTTP Request: POST http://localhost:8321/v1/tool-runtime/invoke "HTTP/1.1 200 OK"
✅ Search successful!
   Query: what is llama stack framework
   Found 5 results:
   1. Llama Stack: A Guide With Practical Examples
      URL: https://www.datacamp.com/tutorial/llama-stack
   2. Llama Stack: The Developer Framework for the Future of AI
      URL: https://medium.com/@juanmabareamartinez/llama-stack-the-developer-framework-for-the-future-of-ai-29855c9f97ad
   3. Getting started with Llama Stack
      URL: https://heidloff.net/article/llama-stack/

======================================================================
✅ Test completed!
======================================================================

📊 Metrics Information:
   Tool invocations have been recorded with the following labels:
   - tool_group: builtin::websearch (or websearch)
   - tool_name: web_search
   - provider: tavily-search provider ID
   - status: success/error

   If OpenTelemetry is configured, metrics are exported to:
   - Prometheus: http://localhost:9090
   - Grafana: http://localhost:3000

   Sample PromQL queries:
   - llama_stack_tool_runtime_invocations_total{tool_name="web_search"}
   - rate(llama_stack_tool_runtime_invocations_total{tool_name="web_search"}[5m])
   - llama_stack_tool_runtime_duration_bucket{tool_name="web_search"}

```
