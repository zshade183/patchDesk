# PatchDesk

PatchDesk 是一个 Windows 桌面编程助手。打开本地 Python Git 仓库后，可以询问项目用途、在同一个会话中追问、提出代码修改需求，并查看每轮生成的补丁、测试结果和工具记录。

## 启动

需要 Windows、Python 3.10 或更高版本、Git和 Node.js 22。界面由 pywebview 的 Qt WebEngine 后端渲染，随 Python 依赖安装。在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
.\PatchDesk.cmd
```

左下角的「运行离线示例」可以直接验证桌面界面、Git 副本、测试和补丁展示。修改前端源码后，重新执行构建命令并重启应用。

## 使用模型

将 `.env.example` 复制为 `.env`，为使用的服务填写 `MODEL_ID` 和 `ANTHROPIC_API_KEY`。使用兼容 Anthropic Messages API 的服务时，填写 `ANTHROPIC_BASE_URL`。同名环境变量优先于 `.env`。输入框下方的模型栏支持直接输入模型 ID。

1. 点击项目列表旁的文件夹按钮，添加本地 Git 项目。
2. 输入问题或修改需求，点击「发送」，也可使用 `Ctrl+Enter`。
3. 点击左侧会话，在底部继续提问。任务失败时，界面会显示原因，可调整模型后重试。
4. 在右侧查看该轮的逐文件补丁、验证输出和工具记录。

每轮以项目当前 Git HEAD 创建独立任务副本。原仓库的未提交改动和上一轮未应用的补丁不会出现在新副本中。续问会带上最近 8 轮文本上下文。桌面任务可以读取已跟踪的 Python 文件和根目录 README，允许修改已读取的非测试 Python 文件。验证使用 `tests/` 下的 `unittest`。测试进程以当前用户权限运行，请选择可信仓库。使用在线模型时，任务需求和模型读取的源码会发送给配置的服务。

## 项目结构

| 路径 | 职责 |
| --- | --- |
| `frontend/` | React、TypeScript 和 Vite 前端，负责项目选择、会话、模型输入和结果展示。 |
| `patchdesk/desktop.py` | pywebview 窗口和仅绑定本机回环地址的界面接口。 |
| `patchdesk/workspace.py` | 项目与模型偏好、会话历史、重试和错误状态。 |
| `patchdesk/engine.py` | 创建 Git 副本、启动任务子进程、运行验证并保存报告。 |
| `patchdesk/worker.py` | 在任务副本内运行 Agent，限制模型可用工具和文件范围。 |
| `patchdesk/benchmark.py` | 离线演示与真实模型评测入口。 |
| `agent/` | 模型调用、Agent 主循环、工具注册和执行。 |
| `docs/` | 设计资料。 |
| `PatchDesk.cmd` | Windows 启动入口。 |

本地偏好保存在 `.runs/desktop.json`。每轮任务的报告和 Git 副本保存在 `.runs/<任务编号>/`，已有报告可在新界面打开。

## 运行评测

```powershell
.\.venv\Scripts\python.exe -m patchdesk.benchmark --jobs 3
.\.venv\Scripts\python.exe -m patchdesk.benchmark --live --jobs 3
```

两种模式使用相同的 40 道合成题，其中 6 道涉及跨文件接口。题目覆盖排序、解析、图搜索、数值计算、状态更新和缓存。每次运行都会创建新的 Git 仓库，先确认原有测试通过，并核对独立验收触发预期缺陷。离线模式使用固定工具动作。在线模式从配置读取模型，也可通过 `--model` 覆盖。`--jobs` 设置并发任务数，`--repeat` 设置每道题的运行次数。

一题计为解决需同时满足正常结束、有补丁、原有测试通过和独立验收通过。两种模式的汇总及逐次结果写入 `.runs/benchmark-scripted.json` 与 `.runs/benchmark-model.json`。

样本说明、指标口径和逐题结果见 [40 题评测报告](docs/evaluation-v3.md)。历史数据见 [12 题评测报告](docs/evaluation-v2.md)和 [6 题评测报告](docs/evaluation.md)。

真实模型评测额外记录主 Agent 每次调用的输入、缓存读取、缓存写入和输出 token。逐题及汇总用量存于同一份 JSON 的 usage 字段，每次调用的原始计数存于任务目录下的 usage.jsonl。离线脚本没有模型用量。
