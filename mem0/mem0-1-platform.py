import os
from mem0 import MemoryClient
from dotenv import load_dotenv
load_dotenv()

os.environ["MEM0_API_KEY"] = os.getenv("MEM0_API_KEY")

client = MemoryClient()

messages = [
    {"role": "user", "content": "Thinking of making a sandwich. What do you recommend?"},
    {"role": "assistant", "content": "How about adding some cheese for extra flavor?"},
    {"role": "user", "content": "Actually, I don't like cheese."},
    {"role": "assistant", "content": "I'll remember that you don't like cheese for future recommendations."}
]
client.add(messages, user_id="alex")

# Example showing location and preference-aware recommendations
query = "I'm craving some pizza. Any recommendations?"
filters = {
    "AND": [
        {
            "user_id": "alex"
        }
    ]
}
user_memories = client.search(query, version="v2", filters=filters)
print("Search Results:")
print(user_memories)
print("\n" + "="*50 + "\n")

filters = {
   "AND": [
      {
         "user_id": "alex"
      }
   ]
}

all_memories = client.get_all(version="v2", filters=filters, page=1, page_size=50)

print("All Memories:")
print(all_memories)