import os  
# os 模块：用来读环境变量 

from dotenv import load_dotenv 
# python-dotenv 库：用来加载 .env 文件

load_dotenv() 
# 读取项目里的 .env，把里面的配置加载进来

api_key = os.getenv("DEEPSEEK_API_KEY")
#从环境变量中读取 DEEPSEEK_API_KEY 的值

if api_key is None: 
    raise ValueError("没有找到 DEEPSEEK_API_KEY，请检查 .env 文件。")
else:
    print("读到API key:", api_key[:6]+"...")
#验证是否成功取到API值

from langchain import messages
from langchain_openai import ChatOpenAI 
#导入模型库

model = ChatOpenAI(
    model="deepseek-chat",
    api_key=api_key,
    base_url="https://api.deepseek.com",
)
# 创建模型：告诉程序"用哪个模型、拿哪个 key、连哪个服务器"

system_prompt = "你是一个专业的 CS2 选手设置助手,只回答cs选手设置相关问题。回答简洁准确;不知道的就说不知道，不要编造。"
counter = 0
history = []
def cleanmachain(history):
    del history[:-5]
    global counter
    counter -= 1
while True:
    user_input = input("你： ").strip()
    if user_input in ("/quit","/exit"):
        break
    if user_input == "/clear":
        history.clear()
        print("已清空历史")
        continue
    messages = [{"role":"system", "content":system_prompt}]+history+[{
        "role":"user","content":user_input}]
    response = model.invoke(messages)
    answer = response.content
    print("AI:", answer)
    history.append({"role":"user","content":user_input})
    history.append({"role":"assistant","content":answer})
    counter += 1
    if counter > 5:
        cleanmachain(history) 

