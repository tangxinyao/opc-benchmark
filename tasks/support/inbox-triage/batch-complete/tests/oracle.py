"""差分判分：判分器用同一套凭证调同一个真实 API，拿到真值再跟 agent 的产出比。

为什么需要这个：程序判分靠钉死的期望值，而期望值绑在「语料是我的」这个前提上。
一旦用户拿自己的账号跑，期望值就失效了，判分只能退回去让模型当裁判——
那正是这个仓库明确拒绝的东西。差分判分绕开了这一点：不预设答案，现场取真值。

**前提：题面必须埋一个看似合理的错答案。** 判分器调 API、agent 也调 API，
比的就是 API 跟它自己，只能测出「会不会用这个 API」。让它仍然是一道母题的，
是题面里那个具体、可算、且是错的先验——模型要么顺着它算（错），要么去查（对）。
`make lint` 会检查每道差分判分的题都声明了 decoy_prior 且题面里确实有。

**口径必须逐字对齐。** agent 和判分器的查询参数差一点，数字就对不上，
而差异来自口径不是编造。口径写死在题面里，判分器用完全相同的参数调用。
"""
import json
import os
import time
from pathlib import Path

import pytest

# 判分器自身出问题（网络、凭证、限流）时用这个退出码。test.sh 据此把这次 trial
# 标成 infra error 而不是记 0 分——尺子坏了不该算到被测者头上。
INFRA_EXIT_CODE = 99

LOG_DIR = Path(os.environ.get("OPC_VERIFIER_LOG_DIR", "/logs/verifier"))
# 本地自检用：指向一个 JSON 文件时，oracle() 从文件取值而不去调真 API，
# 这样没有凭证也能验证这套机制本身是通的。
FAKE_ORACLE = os.environ.get("OPC_ORACLE_FAKE")


class InfraError(Exception):
    """判分器自己坏了，不是 agent 的错。"""


def credentials(*names: str) -> dict:
    """取凭证。缺一个就是 infra error——没凭证判不了分，但不是 agent 的责任。"""
    values = {}
    missing = []
    for name in names:
        value = os.environ.get(name)
        if not value:
            missing.append(name)
        else:
            values[name] = value
    if missing:
        raise InfraError(f"判分器缺少凭证: {', '.join(missing)}")
    return values


def _record(name: str, value, error: str = None) -> None:
    """把判分器自己拿到的真值落盘。出了假阴性，没有这个没法复盘。"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / "oracle.json"
        entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        entries.append({"ts": time.time(), "name": name,
                        "value": value, "error": error})
        path.write_text(json.dumps(entries, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except OSError:
        pass  # 落不了盘不该连累判分


def oracle(name: str, fetch, *, retries: int = 2, backoff_sec: float = 2.0):
    """调 fetch() 取真值。失败重试，仍失败就整场判分以 infra error 退出。

    retries 是给网络抖动和限流的。重试完还不行说明不是抖动，别把它摊进分数里——
    每道题重复跑几遍，网络贡献的方差会盖过模型本身的方差。
    """
    if FAKE_ORACLE:
        value = json.loads(Path(FAKE_ORACLE).read_text(encoding="utf-8"))[name]
        _record(name, value)
        return value

    last = None
    for attempt in range(retries + 1):
        try:
            value = fetch()
            _record(name, value)
            return value
        except Exception as exc:  # noqa: BLE001 - 真 API 什么都可能抛
            last = exc
            if attempt < retries:
                time.sleep(backoff_sec * (attempt + 1))

    _record(name, None, error=f"{type(last).__name__}: {last}")
    pytest.exit(
        f"判分器取 oracle {name!r} 失败（重试 {retries} 次）: {last}。"
        "这是判分器自身的问题，本次 trial 作废，不计分。",
        returncode=INFRA_EXIT_CODE,
    )


def close_enough(got, expected, *, tol: float = 0.01) -> bool:
    """金额比对。真账单是分位小数，别用 == 。"""
    return abs(float(got) - float(expected)) <= tol
