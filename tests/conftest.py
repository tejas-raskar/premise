from uuid import uuid4

import pytest

from premise.demo import create_demo
from premise.memory import Memory


@pytest.fixture
def memory(tmp_path):
    project = create_demo(tmp_path / "jobs")
    instance = Memory([project], graph_prefix="test_" + uuid4().hex)
    yield instance, project
    for graph in instance._graphs.values():
        graph.delete()
