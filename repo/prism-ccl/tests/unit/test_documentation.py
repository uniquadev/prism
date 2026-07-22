from __future__ import annotations

import re
import unittest
from pathlib import Path

from prism_ccl.protocol.constants import (
    AccumulatorProfile,
    AllocationKey,
    CapabilityKey,
    CollectiveSemantic,
    ControlCommand,
    NextHopType,
    NodeRole,
    Opcode,
    PartialWireFormat,
    ProgressPeerKind,
    ProgressReason,
    ReductionOperator,
    ResourceKey,
    SecurityProfile,
    Status,
    TlvType,
    WireFormat,
)

ROOT = Path(__file__).resolve().parents[4]
PROTOCOL_DOCS = (ROOT / "docs/chapters/3-architecture/1.protocol.md",)


class DocumentationConsistencyTests(unittest.TestCase):
    def test_canonical_wire_enums_are_documented(self) -> None:
        enum_specs = (
            (Opcode, 2, "PM_OP_"),
            (ControlCommand, 4, ""),
            (Status, 2, ""),
            (TlvType, 4, ""),
            (NodeRole, 2, ""),
            (NextHopType, 2, ""),
            (CollectiveSemantic, 2, ""),
            (ReductionOperator, 2, ""),
            (WireFormat, 2, ""),
            (PartialWireFormat, 2, ""),
            (AccumulatorProfile, 2, ""),
            (ProgressPeerKind, 2, ""),
            (ProgressReason, 2, ""),
            (SecurityProfile, 2, ""),
        )
        for path in PROTOCOL_DOCS:
            lines = path.read_text(encoding="utf-8").splitlines()
            for enum_type, width, prefix in enum_specs:
                for member in enum_type:
                    value = f"0x{int(member):0{width}X}"
                    name = prefix + member.name
                    self.assertTrue(
                        any(value in line and name in line for line in lines),
                        f"{path.name} does not pair {name} with {value}",
                    )

    def test_capability_resource_and_allocation_keys_are_documented(self) -> None:
        for path in PROTOCOL_DOCS:
            lines = path.read_text(encoding="utf-8").splitlines()
            for enum_type in (CapabilityKey, ResourceKey, AllocationKey):
                for member in enum_type:
                    if member.name == "INVALID":
                        continue
                    value = f"0x{int(member):04X}"
                    self.assertTrue(
                        any(value in line and member.name in line for line in lines),
                        f"{path.name} does not pair {member.name} with {value}",
                    )

    def test_packet_diagram_widths_match_their_headers(self) -> None:
        for path in PROTOCOL_DOCS:
            text = path.read_text(encoding="utf-8")
            mermaid_blocks = re.findall(r"```mermaid\s+(.*?)```", text, re.DOTALL)
            blocks = [
                block for block in mermaid_blocks if re.search(r"^packet\s*$", block, re.MULTILINE)
            ]
            self.assertGreaterEqual(len(blocks), 7)
            for block in blocks:
                widths = [int(width) for width in re.findall(r"^\s*\+(\d+):", block, re.MULTILINE)]
                self.assertTrue(widths, f"empty packet diagram in {path.name}: {block}")
                self.assertIn(sum(widths), {16, 64, 192, 320, 512})

    def test_no_stale_normative_identifiers(self) -> None:
        all_docs = "\n".join(
            path.read_text(encoding="utf-8") for path in (ROOT / "docs").rglob("*.md")
        )
        self.assertNotRegex(
            all_docs,
            r"\bMiniSharp\b|\bMS_[A-Z0-9_]+\b|PM_SETUP_CONTEXT|PM_OP_COL_SETUP|Context ID",
        )

    def test_byte_order_rule_separates_headers_from_numeric_elements(self) -> None:
        text = PROTOCOL_DOCS[0].read_text(encoding="utf-8")
        self.assertIn("scalar TLV integers use network byte order", text)
        self.assertIn("numeric DATA and RES elements", text)
        self.assertIn("are little", text)
        self.assertNotIn("multibyte integers and numeric elements use network byte order", text)

    def test_protocol_flow_matches_the_implemented_single_node(self) -> None:
        text = PROTOCOL_DOCS[0].read_text(encoding="utf-8")
        self.assertIn("## Single-node collective flow", text)
        for step in (
            "### 1. Configure the node",
            "### 2. Submit endpoint contributions",
            "### 3. Reduce each range",
            "### 4. Deliver results",
        ):
            self.assertIn(step, text)
        self.assertNotIn("reduce-lifecycle/", text)

    def test_production_module_pages_match_implemented_rtl(self) -> None:
        module_root = ROOT / "docs/chapters/3-architecture/4-interfaces"
        index = (module_root / "index.md").read_text(encoding="utf-8")
        expected_pages = {
            "prism_open_nic_250mhz": "top/prism_open_nic_250mhz.md",
            "prism_collective_core": "core/prism_collective_core.md",
            "prism_ingress_port": "ingress/prism_ingress_port.md",
            "prism_control_reassembler": "control/prism_control_reassembler.md",
            "prism_control_executor": "control/prism_control_executor.md",
            "prism_data_depacketizer": "collective/prism_data_depacketizer.md",
            "prism_input_conversion_stage": "conversion/prism_input_conversion_stage.md",
            "prism_range_scheduler": "collective/prism_range_scheduler.md",
            "prism_result_chunk_store": "collective/prism_result_chunk_store.md",
            "prism_result_router": "collective/prism_result_router.md",
            "prism_result_packetizer": "egress/prism_result_packetizer.md",
        }
        implemented = set()
        for source in (ROOT / "repo/prism-hdl/src").rglob("*.sv"):
            match = re.search(
                r"^module\s+(prism_[A-Za-z0-9_]+)",
                source.read_text(encoding="utf-8"),
                re.MULTILINE,
            )
            if match:
                implemented.add(match.group(1))

        for module, relative_page in expected_pages.items():
            self.assertIn(module, implemented)
            self.assertIn(f"[`{module}`]({relative_page})", index)
            page = module_root / relative_page
            self.assertTrue(page.is_file(), f"missing module page: {relative_page}")
            text = page.read_text(encoding="utf-8")
            self.assertIn(f"# `{module}`", text)
            for heading in (
                "## Contracts",
                "## Contract behavior",
                "## Related modules and concepts",
            ):
                self.assertIn(heading, text)

        documented = set(re.findall(r"\[`(prism_[a-z0-9_]+)`\]\(([^)]+\.md)\)", index))
        self.assertEqual(documented, set(expected_pages.items()))
        architecture_text = "\n".join(
            path.read_text(encoding="utf-8") for path in module_root.rglob("*.md")
        )
        self.assertNotRegex(architecture_text, r"prism_sim_top|prism_reduce_harness")

    def test_documentation_has_no_mvp_or_historical_proposal_language(self) -> None:
        all_docs = "\n".join(
            path.read_text(encoding="utf-8") for path in (ROOT / "docs").rglob("*.md")
        )
        self.assertNotRegex(all_docs, r"(?i)\bMVP\b|pre-MVP|Historical proposal")


if __name__ == "__main__":
    unittest.main()
