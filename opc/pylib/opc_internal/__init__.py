"""内部工具共用的实现。落 /opt/opc/pylib，由 PYTHONPATH 暴露。

做成包而不是裸模块 `_audit`：PYTHONPATH 对容器里每个 python 进程都生效，
一个顶层名 `_audit` 等于往所有人的命名空间里塞东西，包括 agent 自己写的脚本。
收进 opc_internal 之后只占一个名字，且那个名字自解释。

这里不走 pip：装成分发包会出现在 `pip list` 里，而 agent 看得见它——
`rules` 那类题的前提是它认为自己在用一条公司内部命令，不是评测装置。
"""
