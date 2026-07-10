from __future__ import annotations

import re
import unittest
from pathlib import Path

from prism_protocol.constants import (
    AccumulatorMode,
    AllocationKey,
    CapabilityKey,
    CollectiveSemantic,
    ControlCommand,
    NextHopType,
    NodeRole,
    Opcode,
    ProgressPeerKind,
    ProgressReason,
    ReductionOperator,
    ResourceKey,
    SecurityProfile,
    Status,
    TlvType,
    WireFormat,
)


ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_DOCS = (
    ROOT / "docs/chapters/3-architecture/protocol.md",
    ROOT / "docs/chapters/3-architecture/protocol.it.md",
)


class DocumentationConsistencyTests(unittest.TestCase):
    def test_canonical_wire_enums_are_documented_bilingually(self) -> None:
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
            (AccumulatorMode, 2, ""),
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

    def test_capability_resource_and_allocation_keys_are_documented_bilingually(self) -> None:
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
            blocks = [block for block in mermaid_blocks if re.search(r"^packet\s*$", block, re.MULTILINE)]
            self.assertGreaterEqual(len(blocks), 7)
            for block in blocks:
                widths = [int(width) for width in re.findall(r"^\s*\+(\d+):", block, re.MULTILINE)]
                self.assertTrue(widths, f"empty packet diagram in {path.name}: {block}")
                self.assertIn(sum(widths), {16, 64, 192, 320, 512})

    def test_no_stale_normative_identifiers(self) -> None:
        all_docs = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "docs").rglob("*.md")
        )
        self.assertNotRegex(
            all_docs,
            r"\bMiniSharp\b|\bMS_[A-Z0-9_]+\b|PM_SETUP_CONTEXT|PM_OP_COL_SETUP|Context ID",
        )

    def test_reduce_storyboard_is_complete_bilingual_and_uniform(self) -> None:
        expected = (
            "01-host-collective-request.png",
            "02-target-specific-switch-setup.png",
            "03-global-start-grant.png",
            "04-rank-contributions.png",
            "05-local-reduction.png",
            "06-root-reduction.png",
            "07-result-and-acks.png",
            "08-operation-complete.png",
            "09-operation-release.png",
        )
        for path in PROTOCOL_DOCS:
            referenced = tuple(
                re.findall(r"reduce-lifecycle/([^\s)]+\.png)", path.read_text(encoding="utf-8"))
            )
            self.assertEqual(referenced, expected, f"unexpected storyboard sequence in {path.name}")

        asset_dir = ROOT / "docs/assets/images/protocol/reduce-lifecycle"
        self.assertEqual(tuple(path.name for path in sorted(asset_dir.glob("*.png"))), expected)
        for filename in expected:
            header = (asset_dir / filename).read_bytes()[:24]
            self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n", filename)
            width = int.from_bytes(header[16:20], "big")
            height = int.from_bytes(header[20:24], "big")
            self.assertEqual((width, height), (1536, 1024), filename)


if __name__ == "__main__":
    unittest.main()
