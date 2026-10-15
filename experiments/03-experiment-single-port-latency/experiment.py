"""Eight-rank one-port latency experiment entry point.

The measurement runner and case matrix live in ``src/single_port_latency``;
the source-validated plotter is alongside them.
"""

from src.single_port_latency.experiment_tools import main, run_experiment
from src.single_port_latency.plot_latency import plot as draw_graph

__all__ = ("draw_graph", "main", "run_experiment")


if __name__ == "__main__":
    main()
