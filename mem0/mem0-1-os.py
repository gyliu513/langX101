from mem0 import Memory
from dotenv import load_dotenv
load_dotenv()

m = Memory()

# For a user
messages = [
    {
        "role": "user",
        "content": "I like to drink coffee in the morning and go for a walk"
    }
]
result = m.add(messages, user_id="alice", metadata={"category": "preferences"})

related_memories = m.search("Should I drink coffee or tea?", user_id="alice")

print(related_memories)