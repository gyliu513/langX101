# LangGraph Time Travel Example

This example demonstrates a simple LangGraph workflow that generates a topic and then writes a joke about that topic using Google's Gemini AI model.

## Setup

1. **Install dependencies using uv:**
   ```bash
   uv sync
   ```

2. **Set up your Google API key:**
   
   Create a `.env` file in this directory with your Google API key:
   ```
   GOOGLE_API_KEY=your_google_api_key_here
   ```
   
   You can get a Google API key from: https://makersuite.google.com/app/apikey

3. **Run the example:**
   ```bash
   uv run python tt.py
   ```

## What it does

The workflow consists of two nodes:
1. **generate_topic**: Uses Google Gemini to generate a funny topic for a joke
2. **write_joke**: Uses Google Gemini to write a joke based on the generated topic

The workflow will:
- Generate a topic
- Write a joke about that topic
- Display both the topic and the joke
- Create a visual representation of the workflow graph

## Requirements

- Python 3.9+
- Google AI API key
- uv package manager 