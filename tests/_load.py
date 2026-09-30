"""Load bin/recognition (no .py extension) as the module `recognition_engine`."""
import importlib.machinery
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "bin", "recognition")


def load():
    if "recognition_engine" in sys.modules:
        return sys.modules["recognition_engine"]
    loader = importlib.machinery.SourceFileLoader("recognition_engine", ENGINE)
    spec = importlib.util.spec_from_loader("recognition_engine", loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["recognition_engine"] = module
    loader.exec_module(module)
    return module
