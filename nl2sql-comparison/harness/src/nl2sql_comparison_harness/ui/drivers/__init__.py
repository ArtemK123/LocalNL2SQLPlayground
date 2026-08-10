from nl2sql_comparison_harness.ui.drivers.base import FRAMEWORK_URLS, UI_FRAMEWORKS, normalize_framework
from nl2sql_comparison_harness.ui.drivers.chat2db import Chat2dbDriver
from nl2sql_comparison_harness.ui.drivers.dbgpt import DbgptDriver
from nl2sql_comparison_harness.ui.drivers.langchain import LangchainDriver
from nl2sql_comparison_harness.ui.drivers.premsql import PremsqlDriver
from nl2sql_comparison_harness.ui.drivers.vanna import VannaDriver
from nl2sql_comparison_harness.ui.drivers.wrenai import WrenaiDriver

DRIVER_CLASSES = {
    "langchain": LangchainDriver,
    "dbgpt": DbgptDriver,
    "premsql": PremsqlDriver,
    "vanna": VannaDriver,
    "wrenai": WrenaiDriver,
    "chat2db": Chat2dbDriver,
}

__all__ = [
    "DRIVER_CLASSES",
    "FRAMEWORK_URLS",
    "UI_FRAMEWORKS",
    "normalize_framework",
]
