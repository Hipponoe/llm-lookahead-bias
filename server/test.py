from openai import OpenAI
import os

# 从环境变量中获取您的API KEY，配置方法见：https://www.volcengine.com/docs/82379/1399008
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
client = OpenAI(
    base_url='https://ark.cn-beijing.volces.com/api/v3',
    api_key=OPENAI_API_KEY
)

tools = [{
    "type": "web_search",
    "max_keyword": 2,
}]

# 创建一个对话请求
response = client.responses.create(
    model="deepseek-v4-flash-260425",
    input=[{"role": "user", "content": "北京的天气怎么样？"}],
    tools=tools,
)

print(response)