"""NumberGroup SINGLE experiment entry point.

Use ``collect`` to run RTL, ``plot`` for a saved run, and ``summarize`` for
cross-run CSV indexes. Implementations live in ``src/numbergroup_single``.
"""

from src.numbergroup_single.experiment_tools import collect, main, plot, summarize

__all__ = ("collect", "main", "plot", "summarize")


if __name__ == "__main__":
    main()
