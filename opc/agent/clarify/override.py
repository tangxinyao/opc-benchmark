
# ---------------------------------------------------------------------------
# 本机改配：clarify 的提问走留言中继，不再等终端前的人按键。
# 中继实现见 OPC_CLARIFY_RELAY 指向的文件；它不在时原样回落到上面的实现。
# ---------------------------------------------------------------------------

_owner_relay_original_clarify_tool = clarify_tool


def _owner_relay_module():
    import importlib.util
    import os
    import sys

    cached = sys.modules.get("_owner_relay")
    if cached is not None:
        return cached
    path = os.environ.get("OPC_CLARIFY_RELAY", "/opt/opc/lib/clarify_relay.py")
    spec = importlib.util.spec_from_file_location("_owner_relay", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_owner_relay"] = module
    spec.loader.exec_module(module)
    return module


# 签名跟着 hermes 走，而不是钉死在某一版上。v0.21.3 的工具层多传了一个
# multi_select，旧签名当场 TypeError——每次提问都崩，「问老板」这条路整条断掉，
# 代理只剩死磕或瞎猜。所以这里收 **kwargs 并原样透传：hermes 以后再加参数，
# 中继不认识也不会崩，最多是不理会那个参数。
def clarify_tool(question, choices=None, callback=None, **kwargs):  # noqa: F811
    try:
        relay = _owner_relay_module()
    except Exception:
        return _owner_relay_original_clarify_tool(
            question=question, choices=choices, callback=callback, **kwargs
        )
    return relay.clarify(question, choices=choices, callback=callback, **kwargs)
