# -*- coding: utf-8 -*-
"""
voice_to_sd_singleton.py —— 保证整个 model_server 进程里，voice_to_sd.py
只被动态加载(importlib)一次，返回同一个module对象。

[这一版对齐的是板子上实际部署的voice_to_sd.py("集大成版")，不是早前另一份
"真并行版"] 实际这份文件里：
    - record_audio() / transcribe_audio() / translate_zh_to_en() /
      generate_image_with_sd() 这几个函数名、签名都对得上，直接复用。
    - 但Whisper是每次transcribe_audio()调用时现场加载、用完就release()，
      不是常驻的——没有_wt_loaders_lock/start_background_loaders这些东西，
      所以这里不再需要(也没法)"提前后台预热Whisper/翻译"这一步。
    - SD走的是get_sd_pipe()这个懒加载单例(第一次调用真正加载，之后一直
      缓存在模块全局变量_sd_pipe里)，但这份文件本身【没有提供释放SD的
      办法】——一旦加载就永远占着内存，没法配合ensure_vlm_active()"先释放
      SD腾内存再加载VLM"这个需求。这里在拿到module之后，动态给它挂一个
      release_sd_pipe()函数(不修改你磁盘上的原文件)，复用它自己的_sd_pipe
      缓存变量，逐个释放text_encoder/unet/vae_decoder三个RKNN子模型的
      运行时资源，之后_sd_pipe清空，下次get_sd_pipe()会重新走一遍加载。
      [重要] 如果没有这一步，VLM/SD互斥切换形同虚设：SD一旦被用过一次，
      后续加载VLM时会跟SD同时占着NPU内存，大概率导致OOM/NPU内存分配失败。
"""
import importlib.util
import os
import threading

import config

_module = None
_lock = threading.Lock()


def _patch_release_sd_pipe(module):
    """给动态加载的voice_to_sd模块补一个release_sd_pipe()，原文件没有这个函数。"""

    def release_sd_pipe():
        pipe = getattr(module, "_sd_pipe", None)
        if pipe is None:
            return
        for sub_name in ("text_encoder", "unet", "vae_decoder"):
            sub = getattr(pipe, sub_name, None)
            if sub is not None:
                try:
                    sub.rknnlite.release()
                except Exception:
                    pass
        module._sd_pipe = None

    module.release_sd_pipe = release_sd_pipe


def get_voice_to_sd():
    global _module
    with _lock:
        if _module is not None:
            return _module
        path = config.VOICE_TO_SD_SCRIPT_PATH
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"找不到 voice_to_sd.py: {path}，请检查 config.VOICE_TO_SD_SCRIPT_PATH"
            )
        spec = importlib.util.spec_from_file_location("voice_to_sd_reused", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _patch_release_sd_pipe(module)
        _module = module
        return _module