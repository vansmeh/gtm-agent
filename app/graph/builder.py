"""Compile the V1 graph. Research loops at most three times, then the decision path runs once."""

from collections.abc import Callable
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

from app.graph.nodes import (
    PipelineDeps,
    assess,
    build_person_opportunities,
    decide_channel_node,
    decide_contact_node,
    detect_function_node,
    detect_signal_node,
    discover_people,
    generate_person_hypotheses,
    intake,
    laya_node,
    map_redis,
    plan_search,
    recommend,
    research_people,
    route_after_assess,
    search_and_extract,
    select_templates,
    verify_people,
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
    graph.add_node("generate_person_hypotheses", generate_person_hypotheses)
    graph.add_node("discover_people", discover_people(deps))
    graph.add_node("verify_people", verify_people(deps))
    graph.add_node("build_person_opportunities", build_person_opportunities)
    graph.add_node("decide_contact", decide_contact_node)
    graph.add_node("decide_channel", decide_channel_node)
    graph.add_edge("detect_signals", "detect_functions")
    graph.add_edge("detect_functions", "generate_person_hypotheses")
    graph.add_edge("generate_person_hypotheses", "discover_people")
    graph.add_edge("discover_people", "verify_people")
    graph.add_edge("verify_people", "research_people")
    graph.add_edge("research_people", "build_person_opportunities")
    graph.add_edge("build_person_opportunities", "why_now")
    graph.add_edge("why_now", "map_redis")
    graph.add_edge("map_redis", "decide_contact")
    graph.add_edge("decide_contact", "decide_channel")
    graph.add_edge("decide_channel", "select_templates")
    graph.add_edge("select_templates", "laya_shadow")
    graph.add_edge("laya_shadow", "recommend")
    graph.add_edge("recommend", "write_sheets")
    graph.add_edge("write_sheets", END)
    compiled = graph.compile()

    def invoke(state: GraphState, config: dict[str, int]) -> GraphState:
        return cast(GraphState, compiled.invoke(state, cast(RunnableConfig, config)))

    return invoke
