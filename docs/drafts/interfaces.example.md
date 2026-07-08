# 3.3 Interfaces

This page captures the module and stream interfaces that should remain stable
enough for reference use.

## Packet stream

| Signal | Direction | Description |
| --- | --- | --- |
| `valid` | producer to consumer | Packet beat is meaningful. |
| `ready` | consumer to producer | Consumer can accept the beat. |
| `data` | producer to consumer | Packet data word. |
| `last` | producer to consumer | Current beat terminates the packet. |
| `user` | producer to consumer | Sideband metadata or error flags. |

## Documentation rule

When RTL modules are added, each public module should get:

- port table,
- reset behavior,
- timing assumptions,
- backpressure behavior,
- error behavior.
