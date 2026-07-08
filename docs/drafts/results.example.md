# 4. Results

This section will collect performance, resource, and correctness evidence as
the hardware and experiments mature.

## Planned result categories

| Category | Example metric | Notes |
| --- | --- | --- |
| Correctness | Passing trace count | Tie failures to regression tests. |
| Latency | Cycles per pipeline stage | Separate fixed and queueing latency. |
| Throughput | Packets or bytes per cycle | Report conditions and packet sizes. |
| Resources | LUTs, registers, memory blocks | Record tool version and target device. |
| Scalability | Active collectives or ranks | Show the point where buffering dominates. |

## Reporting style

Use small tables for raw evidence and short interpretation paragraphs for thesis
claims. A result is ready for the thesis only when the command, input data, and
environment are reproducible from the repository.
