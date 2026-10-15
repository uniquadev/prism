"""Two-rank SINGLE experiment entry point.

``collect`` verifies the software packet model; ``plot`` draws saved traffic
measurements without running a backend. Implementation is in ``src/single_reduce``.
"""

from src.single_reduce.experiment_tools import collect, main, plot

__all__ = ("collect", "main", "plot")


if __name__ == "__main__":
    main()
