# 3.4 Register Map

This page reserves the canonical register-map location for the thesis site.

| Register | Offset | Access | Description |
| --- | ---: | --- | --- |
| `CONTROL` | `0x00` | RW | Enables or resets the Mini-Sharp datapath. |
| `STATUS` | `0x04` | RO | Reports ready, busy, and error state. |
| `ACTIVE_COLLECTIVES` | `0x08` | RO | Counts currently tracked collectives. |
| `ERROR_CODE` | `0x0C` | RO | Captures the most recent protocol or buffer error. |

!!! note

    These entries are scaffolding. Replace them with RTL-backed addresses once
    the control interface is finalized.
