"""Logical collective tree and explicit Ethernet path binding."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from .model import CollectiveKind, OperationConfig


@dataclass(frozen=True, slots=True)
class PhysicalNode:
    name: str
    mac: bytes
    forwarding_only: bool = False

    def __post_init__(self) -> None:
        if not self.name or len(self.mac) != 6:
            raise ValueError("physical node needs a name and six-byte MAC")


@dataclass(frozen=True, slots=True)
class PhysicalLink:
    left: str
    left_port: int
    right: str
    right_port: int
    mtu: int

    def __post_init__(self) -> None:
        if self.left == self.right or min(self.left_port, self.right_port) < 0:
            raise ValueError("invalid physical link endpoints")
        if not 576 <= self.mtu <= 9216:
            raise ValueError("physical MTU is outside the negotiated range")

    def port_at(self, node: str) -> int:
        if node == self.left:
            return self.left_port
        if node == self.right:
            return self.right_port
        raise ValueError("node is not incident to physical link")


@dataclass(frozen=True, slots=True)
class PrismCapacity:
    max_children: int
    max_endpoints: int
    window_intervals: int
    window_bytes: int
    shared_port_demux: bool
    multi_node_roles: bool

    def __post_init__(self) -> None:
        if (
            min(
                self.max_children,
                self.max_endpoints,
                self.window_intervals,
                self.window_bytes,
            )
            <= 0
        ):
            raise ValueError("PRISM capacities must be positive")


@dataclass(frozen=True, slots=True)
class LogicalNode:
    name: str
    rank_id: int | None = None

    @property
    def is_rank(self) -> bool:
        return self.rank_id is not None


@dataclass(frozen=True, slots=True)
class LogicalEdge:
    child: str
    parent: str
    child_endpoint: int
    parent_endpoint: int
    physical_path: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.child == self.parent or len(self.physical_path) < 2:
            raise ValueError("logical edge needs distinct nodes and a physical path")
        if self.physical_path[0] != self.child or self.physical_path[-1] != self.parent:
            raise ValueError("physical path must connect logical edge endpoints")
        if any(
            not 0 <= endpoint < 0xFFFF
            for endpoint in (
                self.child_endpoint,
                self.parent_endpoint,
            )
        ):
            raise ValueError("logical endpoint ID exceeds 16 bits")


@dataclass(frozen=True, slots=True)
class CompiledContext:
    node: str
    role: str
    children: tuple[str, ...]
    parent: str | None
    result_destinations: tuple[str, ...]
    original_terms: int
    reserved_intervals: int
    reserved_bytes: int


class PhysicalNetwork:
    def __init__(self) -> None:
        self.nodes: dict[str, PhysicalNode] = {}
        self.links: dict[frozenset[str], PhysicalLink] = {}
        self.capacities: dict[str, PrismCapacity] = {}

    def add_node(self, node: PhysicalNode, capacity: PrismCapacity | None = None) -> None:
        if node.name in self.nodes or any(
            existing.mac == node.mac for existing in self.nodes.values()
        ):
            raise ValueError("duplicate physical node name or MAC")
        if node.forwarding_only and capacity is not None:
            raise ValueError("forwarding-only node cannot own PRISM state")
        self.nodes[node.name] = node
        if capacity is not None:
            self.capacities[node.name] = capacity

    def add_link(self, link: PhysicalLink) -> None:
        if link.left not in self.nodes or link.right not in self.nodes:
            raise ValueError("physical link references an absent node")
        key = frozenset((link.left, link.right))
        if key in self.links:
            raise ValueError("duplicate physical link")
        for existing in self.links.values():
            if (
                (link.left == existing.left and link.left_port == existing.left_port)
                or (link.left == existing.right and link.left_port == existing.right_port)
                or (link.right == existing.left and link.right_port == existing.left_port)
                or (link.right == existing.right and link.right_port == existing.right_port)
            ):
                raise ValueError("physical port is already bound")
        self.links[key] = link

    def validate_path(self, path: tuple[str, ...], mtu: int) -> tuple[int, int]:
        if len(path) != len(set(path)):
            raise ValueError("physical path contains a forwarding loop")
        if any(node not in self.nodes for node in path):
            raise ValueError("physical path references an absent node")
        if any(not self.nodes[node].forwarding_only for node in path[1:-1]):
            raise ValueError("intermediate physical hops must advertise ordinary forwarding")
        links: list[PhysicalLink] = []
        for left, right in pairwise(path):
            link = self.links.get(frozenset((left, right)))
            if link is None or link.mtu < mtu:
                raise ValueError("logical edge lacks a viable MTU-qualified physical path")
            links.append(link)
        if not links:
            raise ValueError("physical path is empty")
        return links[0].port_at(path[0]), links[-1].port_at(path[-1])


@dataclass(frozen=True, slots=True)
class CollectiveTree:
    root: str
    nodes: tuple[LogicalNode, ...]
    edges: tuple[LogicalEdge, ...]

    def compile(
        self, network: PhysicalNetwork, config: OperationConfig
    ) -> tuple[CompiledContext, ...]:
        by_name = {node.name: node for node in self.nodes}
        if len(by_name) != len(self.nodes) or self.root not in by_name:
            raise ValueError("tree nodes must be unique and contain the root")
        if by_name[self.root].is_rank or self.root not in network.capacities:
            raise ValueError("aggregation root must be a PRISM node")
        ranks = [node.rank_id for node in self.nodes if node.is_rank]
        if len(ranks) != len(set(ranks)) or set(ranks) != set(config.ranks):
            raise ValueError("tree ranks must match operation membership exactly")
        if any(node.name not in network.nodes for node in self.nodes):
            raise ValueError("logical node is absent from physical network")
        parents: dict[str, str] = {}
        children: dict[str, list[str]] = {name: [] for name in by_name}
        endpoints: set[tuple[str, int]] = set()
        port_use: dict[tuple[str, int], int] = {}
        for edge in self.edges:
            if edge.child not in by_name or edge.parent not in by_name:
                raise ValueError("edge references an absent logical node")
            if edge.parent not in network.capacities:
                raise ValueError("rank or forwarding node cannot aggregate")
            if edge.child in parents:
                raise ValueError("logical child has multiple parents")
            parents[edge.child] = edge.parent
            children[edge.parent].append(edge.child)
            first_port, last_port = network.validate_path(edge.physical_path, config.mtu)
            for endpoint in (
                (edge.child, edge.child_endpoint),
                (edge.parent, edge.parent_endpoint),
            ):
                if endpoint in endpoints:
                    raise ValueError("logical endpoints must be distinct at each node")
                endpoints.add(endpoint)
            for point in ((edge.child, first_port), (edge.parent, last_port)):
                port_use[point] = port_use.get(point, 0) + 1
        if self.root in parents or set(parents) != set(by_name) - {self.root}:
            raise ValueError("tree needs exactly one rooted parent for every other node")
        if any(by_name[name].is_rank and outgoing for name, outgoing in children.items()):
            raise ValueError("rank must be a leaf of the logical tree")
        visited: set[str] = set()

        def descendants(node: str) -> int:
            if node in visited:
                raise ValueError("logical collective tree contains a cycle")
            visited.add(node)
            if by_name[node].is_rank:
                return 1
            return sum(descendants(child) for child in children[node])

        if descendants(self.root) != len(config.ranks) or visited != set(by_name):
            raise ValueError("tree does not reach each rank exactly once")
        contexts: list[CompiledContext] = []
        for node in self.nodes:
            if node.is_rank:
                continue
            capacity = network.capacities.get(node.name)
            if capacity is None:
                raise ValueError("collective node lacks PRISM capacity")
            own_children = children[node.name]
            if not own_children or len(own_children) > capacity.max_children:
                raise ValueError("child count exceeds PRISM capacity")
            if sum(point[0] == node.name for point in endpoints) > capacity.max_endpoints:
                raise ValueError("logical endpoint count exceeds PRISM capacity")
            if (
                any(count > 1 and point[0] == node.name for point, count in port_use.items())
                and not capacity.shared_port_demux
            ):
                raise ValueError("shared physical port lacks endpoint demultiplexing")
            parent = parents.get(node.name)
            role = (
                "SINGLE"
                if parent is None and all(by_name[child].is_rank for child in own_children)
                else "ROOT"
                if parent is None
                else "LEAF"
                if all(by_name[child].is_rank for child in own_children)
                else "INTERNAL"
            )
            if role != "SINGLE" and not capacity.multi_node_roles:
                raise ValueError("node advertises only current SINGLE capability")
            if config.kind == CollectiveKind.ALLREDUCE:
                destinations = tuple(own_children)
            else:
                target_name = next(
                    item.name for item in self.nodes if item.rank_id == config.reduce_destination
                )
                destinations = tuple(
                    child
                    for child in own_children
                    if target_name == child or target_name in self._subtree_names(child, children)
                )
            contexts.append(
                CompiledContext(
                    node.name,
                    role,
                    tuple(own_children),
                    parent,
                    destinations,
                    self._subtree_rank_count(node.name, children, by_name),
                    capacity.window_intervals,
                    capacity.window_bytes,
                )
            )
        return tuple(contexts)

    @staticmethod
    def _subtree_names(root: str, children: dict[str, list[str]]) -> set[str]:
        names = {root}
        for child in children[root]:
            names |= CollectiveTree._subtree_names(child, children)
        return names

    @staticmethod
    def _subtree_rank_count(
        root: str, children: dict[str, list[str]], nodes: dict[str, LogicalNode]
    ) -> int:
        return sum(nodes[name].is_rank for name in CollectiveTree._subtree_names(root, children))
