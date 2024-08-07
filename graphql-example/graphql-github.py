from dotenv import load_dotenv
load_dotenv()
import os

from graphqlclient import GraphQLClient

# 创建一个 GraphQL 客户端实例
client = GraphQLClient('https://api.github.com/graphql')

# 设置你的 GitHub 个人访问令牌
client.inject_token('Bearer ' + os.getenv("GITHUB_API_TOKEN"))

# 定义一个 GraphQL 查询
query = '''
{
  viewer {
    login
    name
  }
  rateLimit {
    limit
    cost
    remaining
    resetAt
  }
}
'''

# 发送查询请求
response = client.execute(query)

# 打印响应
print(response)
