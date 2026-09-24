"""Compile the V1 graph. Research loops at most three times, then the decision path runs once."""

from collections.abc import Callable
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

from app.graph.nodes import (
    PipelineDeps,
    assess,
    detect_function_node,
    detect_signal_node,
    intake,
    laya_node,
    map_redis,
    match_people,
    plan_search,
    recommend,
    research_people,
    route_after_assess,
    search_and_extract,
    select_templates,
    why_now_node,
    write_sheets,
)
from app.graph.state import GraphState


def build_graph(deps: PipelineDeps) -> Callable[[GraphState, dict[str, int]], GraphState]:
    graph: StateGraph = StateGraph(GraphState)
    graph.add_node("intake", intake)
    graph.add_node("plan_search", plan_search)
    graph.add_node("search_and_extract", search_and_extract(deps))
    graph.add_node("assess", assess)
    graph.add_node("detect_signals", detect_signal_node)
    graph.add_node("detect_functions", detect_function_node)
    graph.add_node("research_people", research_people(deps))
    graph.add_node("match_people", match_people)
    graph.add_node("why_now", why_now_node)
    graph.add_node("map_redis", map_redis)
    graph.add_node("select_templates", select_templates(deps))
    graph.add_node("laya_shadow", laya_node(deps))
    graph.add_node("recommend", recommend(deps))
    graph.add_node("write_sheets", write_sheets(deps))

    graph.set_entry_point("intake")
    graph.add_edge("intake", "plan_search")
    graph.add_edge("plan_search", "search_and_extract")
    graph.add_edge("search_and_extract", "assess")
    graph.add_conditional_edges(
        "assess",
        route_after_assess,
        {"plan_search": "plan_search", "detect_signals": "detect_signals"},
    )
    graph.add_edge("detect_signals", "detect_functions")
    graph.add_edge("detect_functions", "research_people")
    graph.add_edge("research_people", "match_people")
    graph.add_edge("match_people", "why_now")
    graph.add_edge("why_now", "map_redis")
    graph.add_edge("map_redis", "select_templates")
    graph.add_edge("select_templates", "laya_shadow")
    graph.add_edge("laya_shadow", "recommend")
    graph.add_edge("recommend", "write_sheets")
    graph.add_edge("write_sheets", END)
    compiled = graph.compile()

    def invoke(state: GraphState, config: dict[str, int]) -> GraphState:
        return cast(GraphState, compiled.invoke(state, cast(RunnableConfig, config)))

    return invoke
