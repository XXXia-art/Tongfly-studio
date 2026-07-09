# -*- coding: utf-8 -*-
"""
prompt_utils.py —— 从 flight_prompt.md 里解析出 system prompt + few-shot 示例。

搬自 run_qwen2vl.py(v2) 里同名逻辑，抽出来做成独立小工具，这样 voice_vlm.py
就不再需要依赖/动态加载整个 run_qwen2vl.py 文件了(那个文件会自己再init一份
rkllm实例，跟 vlm_engine.py 里已有的那份重复，是之前设计里的一个坑，见README)。
"""
import ast
import os
import re

DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."


def _extract_fenced_block(markdown: str, language: str) -> str:
    pattern = rf"```{re.escape(language)}\s*(.*?)```"
    match = re.search(pattern, markdown, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def load_prompt_messages(prompt_path: str):
    """读取prompt.md，返回 (system_prompt, few_shot_messages)。"""
    if not os.path.exists(prompt_path):
        print(f"[prompt_utils] 未找到 {prompt_path}，使用默认 system prompt")
        return DEFAULT_SYSTEM_PROMPT, []

    with open(prompt_path, "r", encoding="utf-8") as f:
        markdown = f.read()

    system_prompt = _extract_fenced_block(markdown, "text") or DEFAULT_SYSTEM_PROMPT
    python_block = _extract_fenced_block(markdown, "python")
    few_shot_messages = []

    if python_block:
        try:
            module = ast.parse(python_block)
            for node in module.body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "FEW_SHOT_MESSAGES":
                            few_shot_messages = ast.literal_eval(node.value)
                            break
        except Exception as exc:
            print(f"[prompt_utils] few-shot 解析失败，跳过示例: {exc}")

    print(
        f"[prompt_utils] 已加载 {os.path.basename(prompt_path)}: "
        f"system={len(system_prompt)} 字符, few-shot={len(few_shot_messages)} 条"
    )
    return system_prompt, few_shot_messages
