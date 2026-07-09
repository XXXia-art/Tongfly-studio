# -*- coding: utf-8 -*-
"""
real_sd_adapter.py —— 把 voice_to_sd.py 里真正在用、效果好的LCM出图pipeline
包装成跟 model_logic.py 里 ensure_sd_active()/model_memory_lock 期待的接口一致：
    .load() / .release() / .generate(prompt, width, height, steps, guidance) / .pipe / .loading / .last_error

[这一版对齐板子上实际部署的voice_to_sd.py] SD走的是它自己的get_sd_pipe()
懒加载单例(第一次调用真正加载，之后一直缓存)，release_sd_pipe()是
voice_to_sd_singleton.py动态补丁挂上去的(原文件没有)。
"""
import base64
import io
import threading

import numpy as np

from voice_to_sd_singleton import get_voice_to_sd


class RealSDAdapter:
    def __init__(self):
        self.pipe = None       # 对外字段名跟旧sd_engine.py保持一致，/health接口会读这个
        self.loading = False
        self.last_error = None
        self._lock = threading.Lock()

    def load(self):
        # [防御性] 正常情况下load()只会经ensure_sd_active()调用，外层已经被
        # model_logic.py的model_memory_lock序列化了；但load()本身是public方法，
        # 如果以后有代码绕开ensure_sd_active()直接调用，这里也不该出现竞态。
        with self._lock:
            if self.pipe is not None:
                return
            self.loading = True
            self.last_error = None
            try:
                vsd = get_voice_to_sd()
                # get_sd_pipe()是真实voice_to_sd.py里的懒加载单例：第一次调用
                # 才会真正走完整的加载流程(读scheduler配置、加载三个RKNN子模型)，
                # 之后一直缓存在它自己的模块全局变量_sd_pipe里，直接返回。
                self.pipe = vsd.get_sd_pipe()
            except Exception as exc:
                self.last_error = str(exc)
                raise
            finally:
                self.loading = False

    def generate(self, prompt, width, height, steps, guidance):
        """跟main.py的run_sd_generate()保持同样的返回契约：base64编码的PNG。
        [注] 这里直接调get_sd_pipe()（内部有缓存判断，如果已经load()过是
        幂等的），不需要重复调self.load()。"""
        vsd = get_voice_to_sd()
        pipe = vsd.get_sd_pipe()
        with self._lock:
            result = pipe(
                prompt=prompt,
                height=height, width=width,
                num_inference_steps=steps,
                guidance_scale=guidance,
                generator=np.random.RandomState(vsd.RANDOM_SEED),
            )
            buf = io.BytesIO()
            result["images"][0].save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode()

    def release(self):
        with self._lock:
            try:
                vsd = get_voice_to_sd()
                # release_sd_pipe()是voice_to_sd_singleton.py动态挂上去的，
                # 原始voice_to_sd.py文件本身没有这个函数(见该文件的说明)。
                vsd.release_sd_pipe()
            except Exception:
                pass
            self.pipe = None


sd_engine = RealSDAdapter()