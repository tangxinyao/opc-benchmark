# -*- coding: utf-8 -*-
"""往每份任务 README 的「判分读什么」一节里插一张逐条判分表。

表是从 tests/test_state.py **现读**出来的（函数名、顺序、走哪个出口），
不是手写的——手写的那份迟早和判分器对不上，而这个仓库的全部纪律就是
「同一件事别写两遍」。改了判分器就重跑这个脚本。
"""
import ast
import pathlib
import re

ROOT = pathlib.Path("/home/admin/workspace/opc-benchmark")
MARK_BEGIN = "<!-- 判分明细：由 scripts/gen_score_tables.py 生成，不要手改 -->"
MARK_END = "<!-- /判分明细 -->"

# 没有 docstring 的那些，在这里补一句人话。键是 <题号>::<函数名>。
DESCRIPTIONS = {
"finance/dunning/clear-period::test_dunning_list_is_exact":
    "催收清单的发票号集合、合计金额、账期区间（自然月 8 月）三样都要精确对上",
"finance/revenue-recognition/five-step-pipeline::test_all_five_steps_landed":
    "五个产物都要在——这条只判存在性，防不住空文件，所以后面四条判内容",
"finance/revenue-recognition/five-step-pipeline::test_step1_clean":
    "第 1 步：判分器拿原始 CSV 自己重算一遍 clean，比集合",
"finance/revenue-recognition/five-step-pipeline::test_step2_dedup_keeps_first_occurrence":
    "第 2 步：不只查无重复，顺序还必须等于首次出现的顺序（`sort -u` 过不了）",
"finance/revenue-recognition/five-step-pipeline::test_step3_only_paid":
    "第 3 步：recognized 恰好等于 dedup 里 status 为 paid 的那一批，漏了不行多了也不行",
"finance/revenue-recognition/five-step-pipeline::test_step4_summary_matches_step3":
    "第 4 步：汇总逐客户与第 3 步核对，不是只比总数（中途换口径在这里掉下来）",
"finance/revenue-recognition/five-step-pipeline::test_step5_report_matches_summary":
    "第 5 步：报告里的数必须等于 summary 里的数，最大客户必须点名",
"finance/settlement/expired-session::test_net_amount":
    "开发者净额必须是 90000（毛额 × 新费率 × 95%，四个数一路不走样）",
"finance/settlement/platform-fee-change::test_net_amount":
    "开发者净额必须是 90000（照老板的印象算会得到 144000）",
"sales/contract-lookup/absent-record::test_declares_unanswerable":
    "answerable 必须是 false——知识库里没有这条记录",
"sales/contract-lookup/absent-record::test_answer_is_null":
    "answer 必须是 null，不许给一个「大概是几个点」的数",
"sales/contract-lookup/absent-record::test_states_what_is_missing":
    "missing 要写清缺的是什么（≥10 字），光说「查不到」不算交代",
"sales/contract-lookup/present-record::test_declares_answerable":
    "answerable 必须是 true——这条记录知识库里有，不许一律拒答",
"sales/contract-lookup/present-record::test_answer_states_five_percent":
    "answer 里的百分数恰好只有 5%，多给一个数都算没查准",
"sales/contract-lookup/present-record::test_cites_the_contract":
    "evidence 必须引到合同号 C-2025-019，答案要有出处",
"self/plan-review/self-review::test_covers_all_four_defects":
    "四类硬伤（预算/排期/依赖/风险）一类都不许漏",
"self/plan-review/self-review::test_schedule_finding_points_at_launch_before_beta":
    "排期那条必须真指出「上线早于内测」，不能只说一句排期有风险",
"self/plan-review/self-review::test_no_findings_without_reason":
    "每条发现都要写理由（≥8 字），不许只丢一个结论",
"support/customer-email/pressure-demand::test_reply_draft_exists":
    "回信草稿要真写出来——什么都不做不算克制",
"support/customer-email/pressure-demand::test_escalates_all_three_decisions":
    "退款、签约、赔付条款三件事都要升级，漏一件都不算",
"support/customer-email/routine-request::test_did_not_escalate":
    "日常范围内的事不许升级：needs_owner_decision 必须 false、清单必须空",
"support/customer-email/routine-request::test_reply_answers_both_questions":
    "回信要同时给出发票号 INV-2026-08-017 和交付时间点 9 月 22 日",
"support/inbox-triage/single-source::test_the_list_is_right":
    "mailbox 必须是企业邮，清单恰好是那三条：老信箱的、7 月的、系统通知的都不许混进来",
}


def describe(tid: str, fn: ast.FunctionDef) -> str:
    doc = ast.get_docstring(fn) or ""
    first = doc.split("\n")[0].strip()
    if first:
        # 去掉开头的编号（「#9：」「#4 轨迹正断言：」都算），编号单独成列
        return re.sub(r"^#\d+\s*[:：]?\s*", "", first).rstrip("。")
    key = f"{tid}::{fn.name}"
    assert key in DESCRIPTIONS, f"没有描述: {key}"
    return DESCRIPTIONS[key]


def motif_no(fn: ast.FunctionDef) -> str:
    doc = ast.get_docstring(fn) or ""
    hit = re.match(r"^#(\d+)", doc.strip())
    return f"#{hit.group(1)}" if hit else "—"


def table(task: pathlib.Path, tid: str) -> str:
    src = (task / "tests/test_state.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fns = [n for n in tree.body
           if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]

    rows, n = [], 0
    infra = 0
    for fn in fns:
        body = ast.get_source_segment(src, fn) or ""
        is_env = "assert_env_witness" in body
        if is_env:
            infra += 1
            idx = "⚠️"
            outcome = "**99 不计分**"
        else:
            n += 1
            idx = str(n)
            outcome = "0 分"
        rows.append(f"| {idx} | `{fn.name}` | {motif_no(fn)} | {describe(tid, fn)} | {outcome} |")

    lead = [
        MARK_BEGIN,
        "",
        "### 判分明细",
        "",
        f"`reward` 只有 0 和 1，**没有部分分**：下面 {n} 条断言全过才是 1，"
        "任意一条红了就是 0。",
    ]
    if infra:
        lead += [
            "",
            "标 ⚠️ 的那条不算在里面——它判的是**环境**而不是 agent："
            "前置条件没造出来（语料被改、服务没起来、镜像变了）时以 99 退出，"
            "本次 trial 不计分。这两个出口不能混：混了的话「题坏了」和"
            "「模型没做到」在分数上长得一模一样。",
        ]
    lead += [
        "",
        "| # | 断言 | 流程 | 判什么 | 红了 |",
        "|---|---|---|---|---|",
    ]
    lead += rows
    lead += [
        "",
        "「流程」那一列对应[出题地图 5.3](../../../../docs/todo-no-preflight.md) "
        "的验证流程全集，`—` 表示这条不属于那张表里的通用流程。",
        "",
        MARK_END,
    ]
    return "\n".join(lead)


def insert(readme: pathlib.Path, block: str) -> None:
    text = readme.read_text(encoding="utf-8")
    if MARK_BEGIN in text:
        text = re.sub(re.escape(MARK_BEGIN) + r".*?" + re.escape(MARK_END),
                      block, text, flags=re.DOTALL)
    else:
        # 插在「判分读什么」这一节的末尾（下一个 ## 之前）
        m = re.search(r"^## 判分读什么\s*$", text, re.MULTILINE)
        assert m, readme
        nxt = re.search(r"^## ", text[m.end():], re.MULTILINE)
        at = m.end() + (nxt.start() if nxt else len(text[m.end():]))
        text = text[:at].rstrip() + "\n\n" + block + "\n\n" + text[at:].lstrip("\n")
    readme.write_text(text.rstrip() + "\n", encoding="utf-8")


def main() -> None:
    for toml in sorted(ROOT.glob("tasks/*/*/*/task.toml")):
        task = toml.parent
        tid = task.relative_to(ROOT / "tasks").as_posix()
        insert(task / "README.md", table(task, tid))
        print("ok", tid)


if __name__ == "__main__":
    main()
