
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


def clarify_tool(question, choices=None, callback=None):  # noqa: F811
    try:
        relay = _owner_relay_module()
    except Exception:
        return _owner_relay_original_clarify_tool(
            question=question, choices=choices, callback=callback
        )
    return relay.clarify(question, choices=choices, callback=callback)
