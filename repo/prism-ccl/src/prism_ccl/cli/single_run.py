"""Run one reduction on a PRISM node from this host and check its result.

The host plays the manager and two ranks; all three reach the node's port 0
through the given interface. The ranks' vectors hold small integers that
every input format represents exactly, and the result is compared with the
reference arithmetic. Needs Linux and root (or CAP_NET_RAW).

    sudo prism-single --interface enp65s0f0np0 --input FP32 --output FP32
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from ..application.single import SingleBinding, compile_single, run_single
from ..application.software import Scenario
from ..domain.model import (
    AccumulatorPolicy,
    ConcreteFormat,
    OperationKey,
    PartialWirePolicy,
    ResultWirePolicy,
    TypedVector,
)
from ..domain.numbers import ExactValue, combine_exact, decode_native, round_native
from ..domain.topology import CollectiveTree, LogicalEdge, LogicalNode, PrismCapacity
from ..world import PrismWorld

# The addresses the U280 board top is built with.
NODE_MAC = bytes.fromhex("025052495300")
MANAGER_MAC = bytes.fromhex("0250524953ff")
RANK_MACS = (bytes.fromhex("02000000000a"), bytes.fromhex("02000000000b"))


def single_world(
    node_mac: bytes = NODE_MAC,
    manager_mac: bytes = MANAGER_MAC,
    rank_macs: tuple[bytes, bytes] = RANK_MACS,
) -> tuple[PrismWorld, CollectiveTree]:
    """The manager and two ranks reach port 0 of the node through one switch."""
    world = PrismWorld(manager="am")
    world.add_node("am", manager_mac)
    world.add_node("switch", bytes.fromhex("020000000004"), forwarding_only=True)
    world.add_prism("s", node_mac, capacity=PrismCapacity(2, 2, 2, 65536, True, False))
    world.connect("am", 1, "switch", 1)
    world.connect("switch", 2, "s", 0)
    nodes, edges = [LogicalNode("s")], []
    for rank, mac in enumerate(rank_macs):
        name = f"r{rank}"
        world.add_node(name, mac)
        world.connect(name, 1, "switch", rank + 3)
        nodes.append(LogicalNode(name, rank))
        edges.append(LogicalEdge(name, "s", 1, 10 + rank, (name, "switch", "s")))
    return world, CollectiveTree("s", tuple(nodes), tuple(edges))


def reduction(
    input_format: ConcreteFormat,
    output: ResultWirePolicy,
    elements: int,
    *,
    kulisch_bits: int = 280,
    world: tuple[PrismWorld, CollectiveTree] | None = None,
    key: OperationKey | None = None,
) -> tuple[Scenario, SingleBinding, tuple[ExactValue, ...]]:
    """A reduction of two ranks to rank 1, with its exact expected result.

    A node refuses an operation whose key it has seen before or has
    superseded (STALE_GENERATION), so each run on a node needs a new key.
    """
    source = tuple(
        round_native(decode_native(x & 255, ConcreteFormat.INT8), input_format)
        for x in (-3, 1, 2, 0, 3, -1, -2, 0)
    )
    if elements <= 0 or elements % len(source):
        raise ValueError(f"the element count must be a positive multiple of {len(source)}")
    left = source * (elements // len(source))
    right = tuple(reversed(source)) * (elements // len(source))
    prism_world, tree = world or single_world()
    prism_world.register_reduce(
        "single",
        tree=tree,
        vectors={0: TypedVector(input_format, left), 1: TypedVector(input_format, right)},
        destination_rank=1,
        management_paths={"s": ("am", "switch", "s")},
        accumulator=AccumulatorPolicy.KULISCH_FIXED,
        partial_wire=PartialWirePolicy.AUTO,
        output_format=output,
        kulisch_bits=kulisch_bits,
        maximum_original_terms=2,
        key=key,
    )
    scenario = prism_world.scenario("single")
    binding = compile_single(prism_world.network, scenario, "s", physical_ports=1)
    expected = tuple(
        combine_exact((decode_native(a, input_format), decode_native(b, input_format)))
        for a, b in zip(left, right, strict=True)
    )
    return scenario, binding, expected


def _mac(text: str) -> bytes:
    value = bytes.fromhex(text.replace(":", ""))
    if len(value) != 6:
        raise argparse.ArgumentTypeError(f"not a MAC address: {text}")
    return value


def main(argv: list[str] | None = None) -> int:
    from ..transport.raw import RawEthernetTransport

    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--interface", required=True, help="host interface cabled to port 0")
    parser.add_argument("--input", default="FP32", choices=[f.name for f in ConcreteFormat])
    parser.add_argument("--output", default="FP32", choices=[p.name for p in ResultWirePolicy])
    parser.add_argument("--elements", type=int, default=4096)
    parser.add_argument("--node-mac", type=_mac, default=NODE_MAC)
    parser.add_argument("--manager-mac", type=_mac, default=MANAGER_MAC)
    parser.add_argument("--timeout", type=float, default=5.0, help="seconds per awaited frame")
    arguments = parser.parse_args(argv)
    scenario, binding, expected = reduction(
        ConcreteFormat[arguments.input],
        ResultWirePolicy[arguments.output],
        arguments.elements,
        world=single_world(arguments.node_mac, arguments.manager_mac),
        # Each run is a job of its own, so a node never takes it for one it has seen.
        key=OperationKey(time.time_ns(), 1, 0, 1, 0),
    )
    started = time.monotonic()
    with RawEthernetTransport({0: arguments.interface}, timeout_s=arguments.timeout) as transport:
        try:
            outcome = asyncio.run(run_single(scenario, binding, transport))
        except (AssertionError, ArithmeticError, TimeoutError) as error:
            print(f"PRISM single: FAILED: {error}")
            print(
                f"PRISM single: sent {len(transport.sent)} frames, "
                f"received {len(transport.received)} PRISM frames from the node"
            )
            return 1
    seconds = time.monotonic() - started
    correct = outcome.rank_values == {1: expected}
    print(
        f"PRISM single: {arguments.elements} elements {arguments.input} -> {arguments.output}, "
        f"{len(transport.sent)} frames sent, {len(transport.received)} received, "
        f"{seconds * 1000:.1f} ms, result {'correct' if correct else 'WRONG'}"
    )
    return 0 if correct else 1


if __name__ == "__main__":
    sys.exit(main())
