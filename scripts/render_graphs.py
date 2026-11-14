"""Render both actual graph definitions to local Mermaid sources."""

from agent.config import ROOT
from agent.graphs.bid_graph import build_bid_graph
from agent.graphs.conversation_graph import build_conversation_graph


def main():
    directory = ROOT / "docs/graphs"
    directory.mkdir(exist_ok=True)
    for name, graph in (
        ("bid", build_bid_graph()),
        ("conversation", build_conversation_graph()),
    ):
        (directory / f"{name}.mmd").write_text(graph.get_graph().draw_mermaid() + "\n")


if __name__ == "__main__":
    main()
