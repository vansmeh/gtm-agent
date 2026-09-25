"""Graph state is the serialized run. Nodes replace it; they do not loop without a cycle cap."""

from typing import TypedDict

from app.domain.models import RunModel


class GraphState(TypedDict):
    run_json: str


def load_run(state: GraphState) -> RunModel:
    return RunModel.model_validate_json(state["run_json"])


def dump_run(run: RunModel) -> GraphState:
    return {"run_json": run.model_dump_json()}
