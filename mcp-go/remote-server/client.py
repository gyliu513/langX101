import requests
import sseclient
import time
import re
import json

SSE_URL = "http://localhost:8080/mcp/sse"
MESSAGE_URL = "http://localhost:8080/mcp/message"

# Step 1: Start a session
print("📨 Sending initial 'hello' message to start session...")
msg_payload = {
    "type": "message",
    "content": "Hello"
}
headers = {"Content-Type": "application/json"}
requests.post(MESSAGE_URL, json=msg_payload, headers=headers)

# Step 2: Extract sessionId from SSE
print("👂 Waiting for sessionId via SSE...")
response = requests.get(SSE_URL, stream=True)
client = sseclient.SSEClient(response)

session_id = None
for event in client.events():
    print("📨 Raw SSE:", event.data)
    match = re.search(r"sessionId=([\w\-]+)", event.data)
    if match:
        session_id = match.group(1)
        print(f"✅ Got sessionId: {session_id}")
        break

if not session_id:
    print("❌ Failed to get sessionId")
    exit(1)

# Step 3: Send tool call with sessionId
tool_payload = {
    "jsonrpc": "2.0",
    "method": "tools/call",
    "id": "1",
    "params": {
        "sessionId": session_id,  # still needed for internal routing
        "name": "calculate",
        "arguments": {
            "operation": "divide",
            "x": 1,
            "y": 2
        }
    }
}

tool_headers = {
    "Content-Type": "application/json",
    "X-Session-ID": session_id  # ✅ this is what jsonrpc.go validates
}


print("📨 Sending tool call with sessionId...")
res = requests.post(MESSAGE_URL, json=tool_payload, headers=tool_headers)
print("🔍 tool call status:", res.status_code)
print("🔍 tool call response:", res.text)


# Step 4: Wait for result
for event in client.events():
    print("📨 Raw SSE:", event.data)
    if "Tool Result" in event.data:
        print("✅ Got tool result:", event.data)
        break
