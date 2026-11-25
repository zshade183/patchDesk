"""
hook.py 是一个 事件回调机制 的骨架，思路借鉴 Claude Code 的 hooks：
在 agent 循环的关键节点"插钩子"，让外部逻辑在不动主流程代码的前提下介入。
"""
from agent.permissions import permission_hook
from agent.config import WORKDIR

# 注册钩子
HOOKS = {
    "UserPromptSubmit": [],
    "PreToolUse": [],
    "PostToolUse": [],
    "Stop": [],
}

def log_hook(block):
    """
    记录工具调用的参数预览。
    只记录前两个参数，超过60个字符的用省略号表示。
    如果参数为空，记录"()"。
    """
    args_preview = str(list(block.input.values())[:2])[:60]
    print(f"\033[90m[HOOK] {block.name}({args_preview})\033[0m")
    return None

def register_hook(event: str, callback):
    """注册钩子。
    用于在指定事件触发时调用回调函数。
    Args:
        event: 事件名称。
        callback: 回调函数。
    """
    HOOKS[event].append(callback)

def trigger_hooks(event: str, *args):
    """
    触发指定事件的所有钩子。
    如果有钩子返回非None值，立即返回该值。
    如果所有钩子都返回None，返回None。
    Args:
        event: 事件名称。
        args: 回调函数的参数。
    Returns:
        第一个非None值，或None。
    """
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:
            return result
    return None

def large_output_hook(block, output):
    """
    检查工具调用的输出是否超过100000个字符。
    如果超过，记录警告信息。
    """
    if len(str(output)) > 100000:
        print(
            f"\033[33m[HOOK] Large output from {block.name}: "
            f"{len(str(output))} chars\033[0m"
        )
    return None

def context_inject_hook(query: str):
    """
    在用户提示中注入上下文。
    """
    print(
        f"\033[90m[HOOK] UserPromptSubmit: "
        f"working in {WORKDIR}\033[0m"
    )
    return None


def summary_hook(messages: list):
    """
    记录会话结束时的工具调用统计。
    """
    tool_count = sum(
        1
        for message in messages
        for block in (
            message.get("content")
            if isinstance(message.get("content"), list)
            else []
        )
        if isinstance(block, dict)
        and block.get("type") == "tool_result"
    )

    print(
        f"\033[90m[HOOK] Stop: session used "
        f"{tool_count} tool calls\033[0m"
    )
    return None

# 注册钩子 ：在用户提示中注入上下文
register_hook("UserPromptSubmit", context_inject_hook)
# 注册钩子 ：在工具调用前检查权限
register_hook("PreToolUse", permission_hook)
# 注册钩子 ：在工具调用前记录参数预览
register_hook("PreToolUse", log_hook)
# 注册钩子 ：在工具调用后检查输出大小
register_hook("PostToolUse", large_output_hook)
# 注册钩子 ：在会话结束时记录统计信息
register_hook("Stop", summary_hook)