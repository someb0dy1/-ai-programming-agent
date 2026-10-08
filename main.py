from app.agent import run_agent


print("AI Agent 已启动")
print("输入 exit 退出")
print()

while True:
    user_input = input("你：").strip()

    if user_input.lower() == "exit":
        break

    if not user_input:
        continue

    try:
        answer = run_agent(user_input)
        print(f"AI：{answer}")
    except Exception as e:
        print(f"错误：{e}")
