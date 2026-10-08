# AI Programming Agent

一个基于 **Ollama + Qwen** 构建的本地 AI Programming Agent，具备工具调用、项目文件操作、Python 沙箱执行和自动 Debug 能力。

该项目的目标不是简单地调用大语言模型生成代码，而是让 Agent 能够围绕真实项目文件完成：

**读取代码 → 分析问题 → 修改文件 → 执行验证 → 根据结果继续 Debug → 返回最终结果**

## 项目特点

- 基于 Ollama 运行本地大语言模型
- 支持 Qwen 等本地模型
- 支持 Function / Tool Calling
- 支持读取和修改真实项目文件
- 支持 Python 代码执行
- 使用 Docker 构建隔离的 Python 执行沙箱
- 支持项目文件直接运行与 Debug
- 限制沙箱 CPU、内存、进程数量和执行时间
- 支持最多 3 次自动 Debug 尝试
- Agent 会根据真实执行结果判断代码是否修复成功
- 支持 Web API 接口

## Agent 工作流程

```text
用户提出编程 / Debug 任务
          │
          ▼
      Ollama / Qwen
          │
          ▼
       Tool Calling
          │
     ┌────┴─────┐
     │          │
     ▼          ▼
读取项目文件   分析问题
     │          │
     └────┬─────┘
          ▼
      修改真实文件
          │
          ▼
     Docker Python
        Sandbox
          │
          ▼
      执行并验证
          │
     ┌────┴────┐
     │         │
   失败       成功
     │         │
     ▼         ▼
 继续 Debug   返回结果
```

## 核心能力

### 1. Tool Calling

Agent 可以根据任务自主选择工具，包括：

| Tool | 功能 |
| --- | --- |
| `calculator` | 数学表达式计算 |
| `get_current_time` | 获取当前时间 |
| `run_python` | Python 代码执行与项目 Debug |
| `list_project_files` | 查看项目文件结构 |
| `read_project_file` | 读取项目文件 |
| `write_project_file` | 修改项目文件 |

Agent 根据用户任务动态决定是否调用工具，而不是所有任务都直接交给模型生成文本。

---

### 2. 项目文件操作

Agent 可以直接操作项目中的真实文件。

例如：

```text
read_project_file
        ↓
读取 test_debug.py
        ↓
分析代码
        ↓
write_project_file
        ↓
修改 test_debug.py
```

为了避免 Agent 在 Debug 过程中错误修改路径，系统增加了目标文件路径一致性约束：

- 用户指定的文件路径必须保持一致
- `read_project_file`、`write_project_file` 和 `run_python` 使用相同路径
- 不允许因为 Debug 自行移动或复制目标文件
- 目标文件不存在时不会擅自寻找其他同名文件

---

### 3. Docker Python Sandbox

Python 执行工具运行在 Docker 容器中，而不是直接在宿主机执行。

当前沙箱主要限制包括：

```text
Docker Image: python:3.12-slim

CPU:          0.5
Memory:       128 MB
PIDs Limit:   64
Timeout:      10 seconds
Network:      disabled
```

项目文件可以被复制到沙箱中，并通过：

```text
PYTHONPATH=/sandbox/project
```

加载真实项目代码。

这样 Agent 可以对实际项目文件进行运行验证，同时降低直接执行模型生成代码带来的风险。

---

## 自动 Debug 示例

项目中包含一个用于验证 Agent Debug 能力的示例：

```python
def add(a, b):
    return a - b

result = add(10, 5)
print(result)
```

用户要求：

> 检查 `test_debug.py`，找出问题并修复实际文件。修改后必须使用 Python 沙箱加载真实的 `test_debug.py` 文件进行验证。

Agent 执行：

```text
1. 读取 test_debug.py
       ↓
2. 发现 a - b 存在逻辑错误
       ↓
3. 修改真实 test_debug.py
       ↓
4. 使用 Docker Python Sandbox
       ↓
5. 运行真实 test_debug.py
       ↓
6. 得到输出 15
       ↓
7. 确认修复成功
```

最终：

```text
执行成功
输出：
15
```

这个过程证明 Agent 不只是生成“看起来正确”的代码，而是能够：

**读取真实文件 → 修改真实文件 → 实际执行 → 根据执行结果验证修改。**

---

## 项目结构

```text
ai-agent/
├── app/
│   ├── __init__.py
│   ├── agent.py
│   ├── logger.py
│   └── tools/
│       ├── __init__.py
│       ├── calculator.py
│       ├── file_tool.py
│       ├── python_tool.py
│       └── time_tool.py
│
├── web/
│   ├── api.py
│   └── templates/
│       └── index.html
│
├── logs/
│
├── main.py
├── test_debug.py
├── test_ollama.py
└── README.md
```

## 技术栈

### AI / LLM

- Ollama
- Qwen
- LLM Tool Calling

### Programming

- Python
- JavaScript
- HTML / CSS

### Runtime / Infrastructure

- Linux
- Docker
- REST API

### Development

- Git
- GitHub
- VS Code Remote SSH

## 环境要求

建议环境：

```text
Python 3.x
Ollama
Docker
Git
Linux
```

并准备一个 Ollama 模型，例如：

```bash
ollama pull qwen2.5:7b
```

确认 Ollama 可以正常使用：

```bash
ollama list
```

## 安装

克隆项目：

```bash
git clone https://github.com/someb0dy1/-ai-programming-agent.git
cd -ai-programming-agent
```

创建 Python 虚拟环境：

```bash
python3 -m venv venv
source venv/bin/activate
```

安装依赖：

```bash
pip install -r requirements.txt
```

如果项目当前没有 `requirements.txt`，可以根据 `app/agent.py` 中的依赖安装所需 Python 包。

## 运行

启动 Agent：

```bash
python main.py
```

Web API：

```bash
python web/api.py
```

具体启动方式可以根据当前项目版本进行调整。

## 安全设计

项目在 Python 沙箱中加入了多项限制：

- 禁用网络访问
- 限制 CPU 使用
- 限制内存
- 限制进程数量
- 限制最大执行时间
- 限制项目文件访问范围
- 阻止访问部分敏感文件
- 阻止路径穿越
- 限制 Debug 最大执行次数

这些机制用于降低 Agent 执行 Python 代码和修改项目文件时的风险。

> 当前项目主要用于本地开发、学习和 AI Agent 实验，不应直接视为生产环境级别的代码执行隔离方案。

## 当前实现

目前已经完成：

- [x] Ollama 本地模型调用
- [x] Qwen 模型接入
- [x] Tool Calling
- [x] Calculator Tool
- [x] Time Tool
- [x] Project File Tool
- [x] Python Sandbox
- [x] Docker 隔离执行
- [x] 真实项目文件 Debug
- [x
