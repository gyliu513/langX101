#!/usr/bin/env python3
"""
Example script demonstrating the use of top_logprobs and logprobs
in OpenAI-compatible Responses API.

This script shows how to:
1. Create a response with top_logprobs to get token probabilities
2. Use include parameter to enable logprobs in the response
3. Handle both streaming and non-streaming responses
"""

import asyncio
from openai import OpenAI

# Initialize the OpenAI client
# For llama-stack, you would use the base_url pointing to your llama-stack server
# Example: client = OpenAI(base_url="http://localhost:8000/v1", api_key="dummy")
client = OpenAI()


def example_basic_response_with_top_logprobs():
    """
    Basic example: Create a response with top_logprobs.

    The top_logprobs parameter (0-20) specifies how many of the most likely
    tokens to return at each position along with their log probabilities.

    Note: For OpenAI Responses API, just setting top_logprobs is enough.
          For Llama Stack, you also need include=["message.output_text.logprobs"]
    """
    print("=== Example 1: Basic Response with top_logprobs ===")

    response = client.responses.create(
        model="gpt-4o-mini",  # or your llama model
        input="What is machine learning?",
        top_logprobs=5,  # Get top 5 most likely tokens at each position
        logprobs=True,
        # For Llama Stack, also add:
        # include=["message.output_text.logprobs"],
        store=True,
    )

    print(f"Response ID: {response.id}")
    print(f"Status: {response.status}")
    print(f"top_logprobs setting: {response.top_logprobs}")

    # Print the actual response content
    for output_item in response.output:
        if output_item.type == "message":
            for content in output_item.content:
                if hasattr(content, 'text'):
                    print(f"\nResponse text: {content.text}")
                    # Check if logprobs are included
                    if hasattr(content, 'logprobs') and content.logprobs:
                        print(f"Logprobs available: {len(content.logprobs)} tokens")
                        # Print first few logprobs
                        for i, logprob in enumerate(content.logprobs[:3]):
                            print(f"  Token {i}: {logprob}")

    print("\n")
    return response


def example_response_with_logprobs_include():
    """
    Advanced example: Use the include parameter to explicitly request logprobs.

    According to the PR, you need to include "message.output_text.logprobs"
    in the include list to get logprobs in the response.
    """
    print("=== Example 2: Response with include parameter for logprobs ===")

    response = client.responses.create(
        model="gpt-4o-mini",
        input="Explain quantum computing in one sentence.",
        top_logprobs=10,  # Get top 10 token alternatives
        include=["message.output_text.logprobs"],  # Explicitly request logprobs
        store=True,
    )

    print(f"Response ID: {response.id}")
    print(f"top_logprobs: {response.top_logprobs}")

    # Access and display logprobs
    for output_item in response.output:
        if output_item.type == "message":
            for content in output_item.content:
                if hasattr(content, 'text'):
                    print(f"\nResponse: {content.text}")

                if hasattr(content, 'logprobs') and content.logprobs:
                    print(f"\nLogprobs detail (first 2 tokens):")
                    for i, token_logprob in enumerate(content.logprobs[:2]):
                        print(f"\n  Position {i}:")
                        print(f"    Token: {token_logprob.token}")
                        print(f"    Logprob: {token_logprob.logprob}")

                        # Print top alternatives if available
                        if hasattr(token_logprob, 'top_logprobs') and token_logprob.top_logprobs:
                            print(f"    Top alternatives:")
                            for alt in token_logprob.top_logprobs[:3]:
                                print(f"      - {alt.token}: {alt.logprob}")

    print("\n")
    return response


def example_streaming_response_with_logprobs():
    """
    Streaming example: Get logprobs in streaming mode.

    When streaming, logprobs are delivered incrementally with each delta.
    """
    print("=== Example 3: Streaming Response with logprobs ===")

    stream = client.responses.create(
        model="gpt-4o-mini",
        input="Count from 1 to 5.",
        top_logprobs=3,
        include=["message.output_text.logprobs"],
        stream=True,
        store=True,
    )

    print("Streaming response with logprobs:\n")

    response_id = None
    full_text = ""

    for event in stream:
        # Track response ID
        if event.type == "response.created":
            response_id = event.response.id
            print(f"Response ID: {response_id}")

        # Handle text deltas with logprobs
        elif event.type == "response.output_text.delta":
            full_text += event.delta
            print(event.delta, end="", flush=True)

            # Logprobs come with each delta
            if hasattr(event, 'logprobs') and event.logprobs:
                # You can process logprobs here if needed
                pass

        # Response completed
        elif event.type == "response.completed":
            print(f"\n\nFinal status: {event.response.status}")
            print(f"Total output tokens: {event.response.usage.output_tokens if event.response.usage else 'N/A'}")

    print("\n")


def example_boundary_values():
    """
    Test boundary values for top_logprobs (0 and 20).

    Based on the PR tests, top_logprobs accepts values from 0 to 20.
    """
    print("=== Example 4: Boundary Values ===")

    # Minimum value
    print("Testing top_logprobs=0:")
    response_min = client.responses.create(
        model="gpt-4o-mini",
        input="Hello",
        top_logprobs=0,
        include=["message.output_text.logprobs"],
        store=True,
    )
    print(f"  top_logprobs: {response_min.top_logprobs}")

    # Maximum value
    print("\nTesting top_logprobs=20:")
    response_max = client.responses.create(
        model="gpt-4o-mini",
        input="Hello",
        top_logprobs=20,
        include=["message.output_text.logprobs"],
        store=True,
    )
    print(f"  top_logprobs: {response_max.top_logprobs}")

    print("\n")


def example_conversation_with_logprobs():
    """
    Multi-turn conversation with logprobs tracking.
    """
    print("=== Example 5: Multi-turn Conversation ===")

    # First turn
    response1 = client.responses.create(
        model="gpt-4o-mini",
        input="What is the capital of France?",
        top_logprobs=5,
        include=["message.output_text.logprobs"],
        store=True,
    )

    print(f"Turn 1 - Response ID: {response1.id}")
    for item in response1.output:
        if item.type == "message" and hasattr(item.content[0], 'text'):
            print(f"  Answer: {item.content[0].text}")

    # Second turn - reference previous response
    response2 = client.responses.create(
        model="gpt-4o-mini",
        input="What is its population?",
        previous_response_id=response1.id,  # Continue conversation
        top_logprobs=5,
        include=["message.output_text.logprobs"],
        store=True,
    )

    print(f"\nTurn 2 - Response ID: {response2.id}")
    for item in response2.output:
        if item.type == "message" and hasattr(item.content[0], 'text'):
            print(f"  Answer: {item.content[0].text}")

    print("\n")


def main():
    """Run all examples."""
    print("OpenAI Responses API - top_logprobs and logprobs Examples\n")
    print("=" * 60)
    print()

    try:
        # Run examples
        example_basic_response_with_top_logprobs()
        # example_response_with_logprobs_include()
        # example_streaming_response_with_logprobs()
        # example_boundary_values()
        # example_conversation_with_logprobs()

        print("=" * 60)
        print("All examples completed successfully!")

    except Exception as e:
        print(f"\nError occurred: {e}")
        print(f"Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
