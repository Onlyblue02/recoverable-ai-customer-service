from importlib.metadata import version

from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import BaseModel


def test_langgraph_postgres_checkpointer_and_pydantic_import_together() -> None:
    assert PostgresSaver is not None
    assert BaseModel is not None
    assert version("langgraph")
    assert version("langgraph-checkpoint-postgres")
    assert version("pydantic")
