# 2.1 CCL and experiments

An experiment describes a workload and collects observations. The CCL owns
protocol encoding and operation lifecycle; the backend owns execution. A device
build defines the compiled hardware. Keeping those responsibilities separate
avoids specifying the same capabilities or buffer sizes twice.

## Example

This runs a two-rank `REDUCE(SUM)` on one `SINGLE` node through the CCL software
packet model. The result goes to `rank0`.
`manager="am"` names the Aggregation Manager but does not create a physical
node for it; its MAC address and links must be supplied like those of the ranks.

```python
import asyncio
import struct

from prism_ccl.domain.model import ConcreteFormat, TypedVector
from prism_ccl.domain.topology import CollectiveTree, LogicalEdge, LogicalNode
from prism_ccl.world import PrismWorld, SoftwareWorldBackend


def fp32(values):
    return TypedVector(
        format=ConcreteFormat.FP32,
        bits=tuple(struct.unpack("<I", struct.pack("<f", value))[0] for value in values),
    )


world = PrismWorld(manager="am")
world.add_node(name="am", mac=bytes.fromhex("020000000000"))
world.add_prism(name="switch", mac=bytes.fromhex("020000000003"))
world.connect(left="am", left_port=1, right="switch", right_port=1)

nodes = [LogicalNode(name="switch")]
edges = []
for rank in range(2):
    name = f"rank{rank}"
    world.add_node(name=name, mac=bytes([2, 0, 0, 0, 0, rank + 1]))
    world.connect(left=name, left_port=1, right="switch", right_port=rank + 2)
    nodes.append(LogicalNode(name=name, rank_id=rank))
    edges.append(
        LogicalEdge(
            child=name,
            parent="switch",
            child_endpoint=1,
            parent_endpoint=10 + rank,
            physical_path=(name, "switch"),
        )
    )

world.register_reduce(
    name="example",
    tree=CollectiveTree(root="switch", nodes=tuple(nodes), edges=tuple(edges)),
    management_paths={"switch": ("am", "switch")},
    vectors={0: fp32(values=[1, 2, 3]), 1: fp32(values=[4, 5, 6])},
    destination_rank=0,
)
result = asyncio.run(
    world.run_async("example", backend=SoftwareWorldBackend(world.capabilities))
)
assert result.rank_bits == {0: fp32(values=[5, 7, 9]).bits}
```

The default policy is `KULISCH_FIXED` accumulation with `AUTO` partial transport.
The example passes the software backend explicitly to `run_async`; `world.run()`
is the synchronous software-only convenience method. The RTL tests instead
pass `CocotbSingleBackend(dut, prism_name="s")` after
constructing a topology and capability catalog matching the compiled SINGLE
device. A scenario can only be attempted once per world. See
`repo/prism-hdl/verification/ccl/examples.py` for a complete RTL binding.
The software model and RTL share the scenario contract, but only the RTL
backend produces cycle-level measurements. In
`experiments/02-experiment-numbergroup-single`, `--input-format` and
`--output-format` select native rank input and native or exact Kulisch RESULT.
Exact Kulisch results are available as `rank_values`, not FP32 `rank_bits`.
