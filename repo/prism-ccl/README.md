# PRISM CCL

This library defines the software contract and frame-level reference
implementation of the [PRISM protocol](../../docs/chapters/3-architecture/1.protocol.md).

The package is organised in layers:

- `prism_ccl.domain`: pure operation identities, typed exact input bits,
  arithmetic rules, capability tuples and logical/physical topology;
- `prism_ccl.application`: bounded Auto packing, interval/byte receive windows,
  AM orchestration, deterministic frame transport, and the driver of one
  SINGLE operation against a node (`application.single`);
- `prism_ccl.wire`: canonical CONTROL, DATA/RESULT NumberGroup, PROGRESS and
  capability-record codecs;
- `prism_ccl.transport`: frames to and from a real node over raw Ethernet
  sockets (Linux);
- `prism_ccl.world.PrismWorld`: scenario facade for the working software backend;
- `prism_ccl.cli`: the `prism-pcap` and `prism-single` commands.

The domain imports no cocotb, asyncio, sockets, Scapy or runner. Simulator
backends bind scenario nodes and ports to the compiled HDL and own their
scheduler and cycle deadlines.

Run both public scenarios:

```sh
uv run python -m prism_ccl.examples
```

The SINGLE example returns the SUM to both ranks. The hierarchical REDUCE
example has two intermediate aggregators, one root, a physical forwarding-only
node, mixed rank input formats, generated NumberGroups, a dropped DATA frame
followed by byte-identical retry, and one destination rank. The tests execute
these same examples against independent expected bits and rational partials.

Packet order is unchanged by default. A simulation can opt into reproducible,
bounded DATA reordering for every stream or selected directed edges:

```python
from prism_ccl.application.reordering import ReorderPlan

result = world.run("example", reorder=ReorderPlan.data(0.25, seed=7))

# To affect only one directed DATA edge:
plan = ReorderPlan.data(0.25, seed=7, edges=(("r0", "s"),))
```

The probability applies to each selection within a packet window, not to a
claimed real-network rate. The delivered frame sequence gives the observed
reorder rate and displacement; the window bounds packet displacement.

`prism-single` plays the manager and two ranks of one reduction against a
PRISM node on a 100 GbE link and checks the result (Linux, root):

```sh
sudo prism-single --interface <interface> --input FP32 --output AUTO
```

The node is the [U280 board build](../../docs/chapters/2-getting-started/u280.md).

Run software checks:

```sh
uv run pytest -q
uv run ruff check src tests
uv run mypy src/prism_ccl
```

Captures contain actual simulated Ethernet frames, not pre-decoded numbers.
Use `prism_ccl.analysis.write_pcap(path, result.frames)` to save one, then:

```sh
uv run prism-pcap capture.pcap --mtu 1500 --kulisch-bits 279
tshark -X lua_script:wireshark/prism.lua -r capture.pcap -V
uv run python -m prism_ccl.analysis.mtu
```

PCAP timestamps are derived from simulated ticks; they are not host wall time
or cocotb cycles. The default Ethernet payload MTU is 1500. The model also
negotiates 576 and 9000 when every bound physical path supports them; 9000 is
never assumed merely because the codec can encode it.
