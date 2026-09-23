"""hermes 会话导出——trajectory 唯一的来源。

整整一批跑下来 hermes-session.jsonl 全是 0 字节，包括跑通的那些。原因不在
agent 侧：`hermes sessions export` 一旦带上任何一个过滤条件（`--source cli`
也算），就改走 prune 那套候选查询，而那套查询第一条就是
``s.ended_at IS NOT NULL``——只挑已经结束的会话，免得删到活的。
`hermes chat -q … -Q` 是一次性跑，退出时不写 ended_at，于是刚跑完的这条会话
永远不在候选里：导出照样成功、照样打印 "Exported 0 sessions"、
照样把文件写成 0 字节。

（本地 hermes 上可复现：带 --source 导 0 条，不带导 1 条。）

所以这里钉两件事：导出命令不带过滤，以及导不出东西时必须吼一声——
空轨迹等于这次跑没有正式证据，不能只留一个 debug 级别的日志。
"""

import asyncio
import logging

from opc.agent.hermes import SESSION_LOG, Hermes


class FakeResult:
    def __init__(self, stdout: str):
        self.stdout = stdout
        self.return_code = 0


class FakeEnvironment:
    pass


def run_export(stdout: str, logger) -> str:
    """跑一次 _export_session，返回它下发的命令。"""
    agent = Hermes.__new__(Hermes)
    agent._native_session_id = None
    agent.logger = logger
    sent = {}

    async def exec_as_agent(environment, command, env=None, timeout_sec=None):
        sent["command"] = command
        return FakeResult(stdout)

    agent.exec_as_agent = exec_as_agent
    asyncio.run(agent._export_session(FakeEnvironment()))
    agent.sent_command = sent["command"]
    return agent


def test_export_is_not_filtered_by_source():
    agent = run_export('{"id": "20260923_092259_dbbafa", "source": "cli"}',
                       logging.getLogger("t"))
    assert "--source" not in agent.sent_command, (
        "带过滤条件的导出会走 prune 候选查询（ended_at IS NOT NULL），"
        "一次性跑的会话永远不在里面，导出的就是个 0 字节文件"
    )
    assert SESSION_LOG in agent.sent_command


def test_session_id_is_picked_up_for_resume():
    agent = run_export(
        "--- bytes: 18183\n"
        '{"id": "20260923_092259_dbbafa", "source": "cli", "messages": []}',
        logging.getLogger("t"),
    )
    assert agent._native_session_id == "20260923_092259_dbbafa"


def test_empty_export_is_loud(caplog):
    """空轨迹 = 这次跑没有正式证据。debug 级别会让它再一次悄悄溜过整批。"""
    with caplog.at_level(logging.WARNING):
        run_export("--- bytes: 0\n", logging.getLogger("opc.test.export"))
    assert any("trajectory" in r.message for r in caplog.records)
