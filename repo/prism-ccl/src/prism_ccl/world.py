"""Scenario-facing PRISM world with runtime-neutral backend contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, TypeVar

from .application.reordering import ReorderPlan
from .application.software import FaultPlan, Scenario, SoftwareBackend, SoftwareResult
from .domain.capabilities import CapabilityCatalog, software_capabilities
from .domain.model import (
    AccumulatorPolicy,
    CollectiveKind,
    OperationConfig,
    OperationKey,
    PartialWirePolicy,
    ResultWirePolicy,
    TypedVector,
)
from .domain.numbers import required_kulisch_bits
from .domain.topology import (
    CollectiveTree,
    PhysicalLink,
    PhysicalNetwork,
    PhysicalNode,
    PrismCapacity,
)

ResultT = TypeVar("ResultT", covariant=True)


class AsyncWorldBackend(Protocol[ResultT]):
    async def run(self, network: PhysicalNetwork, scenario: Scenario) -> ResultT: ...


class SoftwareWorldBackend:
    """Adapt the packet model to the same async scenario contract as RTL backends."""

    def __init__(
        self,
        capabilities: CapabilityCatalog,
        *,
        fault: FaultPlan | None = None,
        reorder: ReorderPlan | None = None,
    ) -> None:
        self.capabilities = capabilities
        self.fault = fault
        self.reorder = reorder

    async def run(self, network: PhysicalNetwork, scenario: Scenario) -> SoftwareResult:
        return SoftwareBackend(network, self.capabilities).run(scenario, self.fault, self.reorder)


class PrismWorld:
    """Defines physical binding and immutable scenarios, then runs real frame codecs.

    Runtime-specific backends bind names to compiled or physical devices; the
    facade itself owns neither simulator tasks nor transport queues.
    """

    def __init__(self, *, manager: str, capabilities: CapabilityCatalog | None = None) -> None:
        self.manager = manager
        self.network = PhysicalNetwork()
        self.capabilities = capabilities or software_capabilities()
        self._scenarios: dict[str, Scenario] = {}
        self._attempted: set[str] = set()
        self._running = False

    def _ensure_idle(self) -> None:
        if self._running:
            raise ValueError("world topology and scenarios cannot mutate during an operation")

    def add_node(self, name: str, mac: bytes, *, forwarding_only: bool = False) -> None:
        self._ensure_idle()
        self.network.add_node(PhysicalNode(name, mac, forwarding_only))

    def add_prism(
        self,
        name: str,
        mac: bytes,
        *,
        capacity: PrismCapacity | None = None,
    ) -> None:
        self._ensure_idle()
        self.network.add_node(
            PhysicalNode(name, mac),
            capacity or PrismCapacity(8, 16, 32, 65536, True, True),
        )

    def connect(
        self, left: str, left_port: int, right: str, right_port: int, *, mtu: int = 1500
    ) -> None:
        self._ensure_idle()
        self.network.add_link(PhysicalLink(left, left_port, right, right_port, mtu))

    def register_reduce(
        self,
        name: str,
        *,
        tree: CollectiveTree,
        vectors: Mapping[int, TypedVector],
        destination_rank: int,
        management_paths: Mapping[str, tuple[str, ...]],
        accumulator: AccumulatorPolicy = AccumulatorPolicy.KULISCH_FIXED,
        partial_wire: PartialWirePolicy = PartialWirePolicy.AUTO,
        output_format: ResultWirePolicy = ResultWirePolicy.FP32,
        mtu: int = 1500,
        key: OperationKey | None = None,
        maximum_original_terms: int | None = None,
        kulisch_bits: int | None = None,
    ) -> None:
        self._register(
            name,
            CollectiveKind.REDUCE,
            tree,
            vectors,
            management_paths,
            destination_rank,
            accumulator,
            partial_wire,
            output_format,
            mtu,
            key,
            maximum_original_terms,
            kulisch_bits,
        )

    def register_allreduce(
        self,
        name: str,
        *,
        tree: CollectiveTree,
        vectors: Mapping[int, TypedVector],
        management_paths: Mapping[str, tuple[str, ...]],
        accumulator: AccumulatorPolicy = AccumulatorPolicy.KULISCH_FIXED,
        partial_wire: PartialWirePolicy = PartialWirePolicy.AUTO,
        output_format: ResultWirePolicy = ResultWirePolicy.FP32,
        mtu: int = 1500,
        key: OperationKey | None = None,
        maximum_original_terms: int | None = None,
        kulisch_bits: int | None = None,
    ) -> None:
        self._register(
            name,
            CollectiveKind.ALLREDUCE,
            tree,
            vectors,
            management_paths,
            None,
            accumulator,
            partial_wire,
            output_format,
            mtu,
            key,
            maximum_original_terms,
            kulisch_bits,
        )

    def _register(
        self,
        name: str,
        kind: CollectiveKind,
        tree: CollectiveTree,
        vectors: Mapping[int, TypedVector],
        management_paths: Mapping[str, tuple[str, ...]],
        destination_rank: int | None,
        accumulator: AccumulatorPolicy,
        partial_wire: PartialWirePolicy,
        output_format: ResultWirePolicy,
        mtu: int,
        key: OperationKey | None,
        maximum_original_terms: int | None,
        kulisch_bits: int | None,
    ) -> None:
        self._ensure_idle()
        if not name or name in self._scenarios or not vectors:
            raise ValueError("scenario name must be new and vectors non-empty")
        ranks = tuple(sorted(vectors))
        element_count = len(next(iter(vectors.values())).bits)
        bound = len(ranks) if maximum_original_terms is None else maximum_original_terms
        config = OperationConfig(
            key or OperationKey(1, 1, 0, len(self._scenarios) + 1, 0),
            kind,
            ranks,
            element_count,
            accumulator,
            partial_wire,
            output_format,
            destination_rank,
            bound,
            required_kulisch_bits(bound) if kulisch_bits is None else kulisch_bits,
            mtu,
        )
        for existing in self._scenarios.values():
            old, new = existing.config.key, config.key
            if (
                old.job_id,
                old.group_id,
                old.group_generation,
                old.operation_id,
            ) == (
                new.job_id,
                new.group_id,
                new.group_generation,
                new.operation_id,
            ) and new.operation_generation <= old.operation_generation:
                raise ValueError("operation ID reuse requires a higher generation")
        self._scenarios[name] = Scenario(
            config, tree, dict(vectors), self.manager, dict(management_paths)
        )

    def run(
        self,
        name: str,
        *,
        fault: FaultPlan | None = None,
        reorder: ReorderPlan | None = None,
    ) -> SoftwareResult:
        self._ensure_idle()
        try:
            scenario = self._scenarios[name]
        except KeyError as error:
            raise ValueError("unknown PRISM scenario") from error
        if name in self._attempted:
            raise ValueError("scenario already attempted; register a new generation")
        self._attempted.add(name)
        self._running = True
        try:
            return SoftwareBackend(self.network, self.capabilities).run(scenario, fault, reorder)
        finally:
            self._running = False

    def scenario(self, name: str) -> Scenario:
        """The registered scenario of that name, for a caller that runs it itself."""
        return self._scenarios[name]

    async def run_async(self, name: str, *, backend: AsyncWorldBackend[ResultT]) -> ResultT:
        """Run one immutable scenario through a runtime-owned asynchronous backend."""
        self._ensure_idle()
        try:
            scenario = self._scenarios[name]
        except KeyError as error:
            raise ValueError("unknown PRISM scenario") from error
        if name in self._attempted:
            raise ValueError("scenario already attempted; register a new generation")
        self._attempted.add(name)
        self._running = True
        try:
            return await backend.run(self.network, scenario)
        finally:
            self._running = False
