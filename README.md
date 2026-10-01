# prompt2article

根据一句提示词生成一整篇文章的命令行工具。

**零依赖**：只用 Python 标准库，不需要 `pip install` 任何东西。

## 它和"一次性让模型写一篇"有什么不同

直接把"写一篇 2000 字的文章"丢给模型，长文常见三个毛病：**跑题、车轱辘话、前后重复**。
这个工具把过程拆成四步，每一步只让模型干一件事：

```
提示词
  │
  ├─ 1. 拟标题
  ├─ 2. 出大纲        （模型先想清楚要写哪几节）
  ├─ 3. 逐节写作      （每次只写一节，带上完整大纲避免跑题）
  └─ 4. 逐节润色      （可选，--polish 打开）
        │
        └─ 组装成 Markdown（带 front matter 元数据）
```

每一节都拿到完整大纲和"这是第 N 节、前后由别人写、不要写衔接语"的约束，
所以节与节之间不会重复，也不会出现"综上所述"出现在第一节。

## 快速开始

```powershell
# 1. 进入项目目录
## 怎么用：四种方式

### 方式一：网页版（浏览器里用，推荐）

**双击本目录里的 `启动网页.bat`** —— 会自动起一个本地服务并打开浏览器：

```
http://127.0.0.1:8756/
```

页面左边填主题、选风格（8 种，带说明）、设字数和读者，右边**实时**显示进度
（拟定标题 → 生成大纲 → 写作 1/4 → …），完成后直接渲染成排版好的文章，
可以一键复制或下载 `.md`。点「最近生成」里的任何一篇都能重新载入。

- 只监听 `127.0.0.1`，**不对外网开放**；API Key 留在服务端，页面拿不到
- 关掉那个黑窗口就是停止服务
- 端口被占用的话：`启动网页.bat --port 8757`
- 没配 API Key 时页面会自动勾上「离线模拟」，先让你看到流程

### 方式二：双击 `生成文章.bat`（命令行，不需要记命令）

1. **双击本目录里的 `生成文章.bat`**
2. 按提示输入**文章主题** → 选**风格**序号 → 输入**字数** → 问要不要润色
3. 生成的文件在 **`output` 文件夹**里（自动帮你打开看）

没有配置 API Key 时，它会自动用**离线模拟模式**跑一遍，让你先看到流程长什么样。

> 为什么用 `.bat`：它是双击就能跑的入口，并且会自动找 Python
> （`python` → `py` → DSH 自带的 Python）并设好中文编码，省得你配环境。

### 方式三：在终端里用（更灵活，能接脚本）

打开终端：按 **Win + X** → 选「终端」或「Windows PowerShell」，然后：

```powershell
cd "$env:USERPROFILE\Desktop\新建文件夹"

# 1. 配置 API Key（二选一）
copy .env.example .env      # 然后编辑 .env 填入 P2A_API_KEY
# 或者只在当前窗口临时用：
$env:P2A_API_KEY = "sk-你的key"

# 2. 先离线跑通流程（不需要 Key、不需要联网）
python -m prompt2article "写一篇介绍世界线收束的科普文章" --offline

# 3. 真实生成
python -m prompt2article "写一篇介绍世界线收束的科普文章"
```

生成结果默认写到 `output/<标题>-<时间>.md`。

> **中文显示**：你的控制台代码页是 936，Python 默认输出也是 gbk，两者匹配，中文正常。
> 如果手动把代码页改成过 65001（UTF-8），记得同时设 `$env:PYTHONUTF8=1`，否则会乱码。

### 方式四：在 PyCharm 里

1. **打开项目**：PyCharm → `File` → `Open` → 选 `桌面\新建文件夹`
2. **配解释器**：`File` → `Settings` → `Project` → `Python Interpreter` →
   `Add Interpreter` → `Add Local Interpreter` → `System Interpreter` →
   选 `C:\Users\zzm28\AppData\Local\Programs\Python\Python313\python.exe`

   本项目**零依赖，不需要装任何包**，选完解释器就能跑。
3. **运行**：在项目树里右键根目录的 **`run.py`** → **Run 'run'**

   Run 控制台会依次问你主题、风格、字数、是否润色 —— 和双击 `.bat` 一样。
   没配 Key 时它会自动落到离线模式，不会走到最后一步才报错。

> ⚠️ **不要直接右键运行 `prompt2article/__main__.py`**。单个文件没有包上下文，
> 它的 `from .cli import main` 会报
> `attempted relative import with no known parent package`。
> 用根目录的 `run.py`：它会把项目根加进 `sys.path`，并把工作目录锚定到项目根，
> 所以 `.env` 找得到、`output/` 也一定落在项目里。

**想固定参数、不每次手输**：`Run` → `Edit Configurations` → `+` → `Python` →
`Script path` 选 `run.py`，`Parameters` 填：

```
"量子计算的现状" --style tech --words 2000 --polish
```

**跑测试**：右键 `tests` 文件夹 → `Run 'Unittests in tests'`（35 项，全部离线，秒级）。

**中文乱码的话**：在 Run Configuration 的 `Environment variables` 里加
`PYTHONUTF8=1`。PyCharm 控制台的编码和系统代码页（936）不一致时会出现，
命令行里是正常的。

**为什么要起服务，不能只做个静态网页？** 静态页面要调用模型 API，就必须把 Key 写进
JavaScript（页面能读到，也能被 F12 看到），而且 DeepSeek 等接口不给浏览器发 CORS 头，
直接被拦。服务端代理同时解决这两件事，还能把已有的风格/大纲/逐节写作整套流水线直接复用，
不用在 JavaScript 里重写一遍。

## 常用命令

```powershell
# 换个风格、指定字数并润色
python -m prompt2article "量子计算的机会与泡沫" --style opinion --words 2000 --polish

# 提示词太长，从文件读
python -m prompt2article --file topic.txt --style tech --out output/tech.md

# 只要正文打到屏幕，不写文件
python -m prompt2article "给团队讲讲为什么写文档" --stdout

# 额外导出一份 JSON（含每节标题与字数），方便二次处理
python -m prompt2article "短视频对注意力的影响" --style essay --json

# 看有哪些风格
python -m prompt2article --list-styles

# 指定目标读者
python -m prompt2article "解释傅里叶变换" --audience "大一新生" --style science
```

## 写作风格

| key | 名称 | 特点 |
| --- | --- | --- |
| `science` | 科普 | 概念准确、用好类比，面向非专业读者（默认） |
| `opinion` | 评论 | 观点鲜明、有论证和反驳，不骑墙 |
| `tutorial` | 教程 | 步骤可复现，含前置条件与排错 |
| `essay` | 叙事散文 | 场景与细节，节奏舒缓 |
| `academic` | 学术 | 结构规范、措辞克制，区分事实与推测 |
| `wechat` | 公众号 | 开头抓人、短段落、金句收尾 |
| `tech` | 技术博客 | 面向同行，重原理、权衡与坑 |
| `speech` | 演讲稿 | 口语化、有节奏，适合朗读 |

## 参数

| 参数 | 说明 |
| --- | --- |
| `prompt` | 文章主题/提示词（位置参数） |
| `--file PATH` | 从文件读取提示词（与位置参数二选一） |
| `-i` / `--interactive` | 交互式询问主题/风格/字数（`生成文章.bat` 用的就是这个） |
| `--style KEY` | 写作风格，默认 `science` |
| `--words N` | 目标字数，默认取风格预设（多为 1200） |
| `--audience TEXT` | 目标读者，会写进提示词 |
| `--language {zh,en,ja}` | 输出语言，默认 `zh` |
| `--title TEXT` | 直接指定标题，跳过标题生成 |
| `--sections N` | 最多保留几个小节，默认 8 |
| `--polish` | 生成后逐节润色，更慢但更稳 |
| `--out PATH` | 输出路径，默认 `output/<标题>-<时间>.md` |
| `--stdout` | 打到标准输出，不写文件 |
| `--json` | 额外输出同名 `.json` 元数据 |
| `--offline` | 用内置模拟模型，不需要 Key 和网络 |
| `--model` / `--base-url` / `--api-key` | 覆盖配置 |
| `--temperature` / `--timeout` | 覆盖采样温度 / 超时 |
| `--quiet` | 不打印进度 |

进度信息一律走 **stderr**，正文走 **stdout**，所以 `--stdout` 的结果可以直接 `>` 重定向或管道。

## 配置

优先级从高到低：**命令行参数 → 环境变量 → `.env` 文件 → 内置默认值**。

真实环境变量总是压过 `.env`，这样临时 `export` 一个 Key 调试时不会被旧文件盖住。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `P2A_API_KEY` | 无 | 也接受 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` |
| `P2A_BASE_URL` | `https://api.deepseek.com/v1` | 任何 OpenAI 兼容地址 |
| `P2A_MODEL` | `deepseek-chat` | 模型名 |
| `P2A_TIMEOUT` | `120` | 单次请求超时秒数 |
| `P2A_MAX_RETRIES` | `3` | 针对限流/超时/5xx 的重试次数 |
| `P2A_TEMPERATURE` | `0.7` | 采样温度 |

因为只要求 OpenAI 兼容的 `/chat/completions`，换成本地模型也只要改地址：

```powershell
python -m prompt2article "测试" --base-url http://127.0.0.1:11434/v1 --model qwen2.5:14b
```

## 输出格式

```markdown
---
title: "文章标题"
prompt: "原始提示词"
style: science
language: zh
model: deepseek-chat
generated_at: 2026-10-01 22:11:24
word_count: 1348
---

# 文章标题

## 第一节标题

正文……

## 第二节标题

正文……
```

front matter 里记的是**复现这篇文章所需的一切**（提示词、风格、模型、目标字数），
所以任何一篇产出都能回溯到它是怎么来的。

## 测试

```powershell
python -m unittest discover -v
```

31 个用例，全部用内置的 `MockClient`，**不需要 Key 也不需要联网**，秒级跑完。

## 常见问题

**报"认证失败"**：Key 无效或过期。检查 `.env` 里有没有多余空格或引号。

**报"余额不足"**：账户需要充值，和代码无关。

**报网络请求失败**：如果直连不通，设置代理再跑：

```powershell
$env:HTTPS_PROXY = "http://127.0.0.1:7890"
```

**字数总是不达标**：模型对字数只有模糊感知。可以 `--words` 调高一点，或 `--polish`
打开润色（润色会补足被压缩的表达）。反过来想压短，把 `--sections` 调小更有效。

**标题带了引号或"《》"**：`_one_line()` 已经会剥掉常见的引号和井号；
如果模型还是加了奇怪前缀，用 `--title` 直接指定。

**想让文章排版成特定模板**：改 `prompt2article/prompts.py` 里的 `system_prompt()`，
那是所有阶段共用的系统提示词。

## 项目结构

```
prompt2article/
├── prompt2article/
│   ├── __init__.py       版本与导出
│   ├── __main__.py       python -m 入口
│   ├── cli.py            参数解析、进度、写文件
│   ├── config.py         环境变量 / .env 解析与优先级
│   ├── client.py         OpenAI 兼容客户端 + 离线模拟 + 错误翻译
│   ├── prompts.py        8 种风格 + 各阶段的提示词构造
│   ├── generator.py      流水线、大纲解析、字数分配、Markdown 组装
│   ├── webapp.py         本地 Web 服务（标准库 http.server，SSE 推进度）
│   └── web/              前端单页：index.html / style.css / app.js
├── tests/
│   ├── test_core.py      纯函数与端到端（离线）
│   ├── test_cli.py       命令行行为、输出文件、退出码、交互模式
│   └── test_webapp.py    真起 HTTP 服务打接口：页面、SSE、文件、路径穿越
├── examples/prompts.md   各风格的提示词范例
├── output/               生成的文章（已 gitignore）
├── run.py                IDE 入口：右键 Run 即可
├── 生成文章.bat           双击启动器：命令行交互式
├── 启动网页.bat           双击启动器：起本地网页服务
├── .env.example          配置样板
└── pyproject.toml
```

## 设计取舍

**为什么零依赖？** 用 `urllib` 而不是 `requests`/`openai`，任何有 Python 3.10+ 的机器
克隆下来就能跑，不用先解决装包和网络问题。代价是要自己写重试和错误翻译——都在
`client.py` 里，不到 200 行。

**为什么逐节生成而不是一次生成全文？** 长文一次生成必然漂移。逐节 + 完整大纲是
"用多次短请求换一致性"，代价是请求数变多（4 节文章约 6 次请求）。

**为什么润色也逐节？** 把整篇丢回去润色，一旦输出被截断就会丢掉后半篇；
逐节润色最坏只影响一节。

**字数怎么算的？** `len(text.split())` 对中文毫无意义，`len(text)` 又会高估英文。
这里数的是"CJK 字符数 + 英文单词数"，更接近中文作者心里的那个数。

## 许可

MIT，见 [LICENSE](LICENSE)。
