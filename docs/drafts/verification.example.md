# 4.1 Verification Evidence

This section will document the SystemVerilog RTL and the Cocotb/Verilator
verification environment once the source tree is added.

## Verification goals

- Validate packet parsing and field extraction.
- Exercise each supported collective opcode.
- Check ordering, buffering, and completion behavior.
- Capture waveforms for failing or ambiguous traces.
- Connect measured behavior back to the thesis results.

## Expected evidence

| Evidence | Use |
| --- | --- |
| Unit tests | Prove local parser and operation behavior. |
| Integration tests | Exercise end-to-end packet flow. |
| PCAP or synthetic traces | Reproduce realistic traffic cases. |
| Waveforms | Debug temporal behavior and handshake bugs. |
| Result tables | Support thesis claims with repeatable measurements. |
