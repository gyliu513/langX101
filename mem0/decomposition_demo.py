from mem0 import Memory
from dotenv import load_dotenv
load_dotenv()

# 创建Memory实例
m = Memory()

print("=== mem0自动分解演示 ===\n")

# 测试用例1：简单偏好
print("测试1: 简单偏好")
messages1 = [{"role": "user", "content": "I like pizza"}]
result1 = m.add(messages1, user_id="demo_user")
print(f"输入: 'I like pizza'")
print(f"分解结果: {result1}")
print()

# 测试用例2：复合偏好（你的例子）
print("测试2: 复合偏好")
messages2 = [{"role": "user", "content": "I like to drink coffee in the morning and go for a walk"}]
result2 = m.add(messages2, user_id="demo_user")
print(f"输入: 'I like to drink coffee in the morning and go for a walk'")
print(f"分解结果: {result2}")
print()

# 测试用例3：复杂偏好
print("测试3: 复杂偏好")
messages3 = [{"role": "user", "content": "I enjoy reading science fiction books, playing guitar, and cooking Italian food on weekends"}]
result3 = m.add(messages3, user_id="demo_user")
print(f"输入: 'I enjoy reading science fiction books, playing guitar, and cooking Italian food on weekends'")
print(f"分解结果: {result3}")
print()

# 测试用例4：单一概念（不应该分解）
print("测试4: 单一概念")
messages4 = [{"role": "user", "content": "My favorite color is blue"}]
result4 = m.add(messages4, user_id="demo_user")
print(f"输入: 'My favorite color is blue'")
print(f"分解结果: {result4}")
print()

print("=== 搜索测试 ===")
# 测试搜索功能
search_queries = [
    "What should I drink?",
    "What activities do I enjoy?", 
    "What books should I read?",
    "What color should I choose?"
]

for query in search_queries:
    memories = m.search(query, user_id="demo_user")
    print(f"查询: '{query}'")
    print(f"相关记忆: {[mem.get('memory', '') for mem in memories]}")
    print()
