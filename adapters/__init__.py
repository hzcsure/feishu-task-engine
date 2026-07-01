"""
适配器模块：管理阶段间转场的特定逻辑。

每个适配器是一个 .py 文件，由 task_engine.py 在引擎内部 import 调用。
适配器不是子进程，不走 subprocess，而是引擎内部的函数调用。

适配器接口约定：
  prepare_input(context) -> context    # 阶段执行前的输入准备
  process_output(stdout, context) -> context  # 阶段执行后的输出处理
"""
