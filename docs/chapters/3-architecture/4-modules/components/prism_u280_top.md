# `prism_u280_top`

`prism_u280_top` places `prism_collective_core` on an Alveo U280 with one 100G
port and no host interface. It reuses two modules of the OpenNIC shell as they
are, the CMAC subsystem and the packet adapter, and supplies what the shell
otherwise takes from its PCIe side: clocks, reset and the register writes that
enable the MAC.

```text
QSFP28 port 0 <-> cmac_subsystem <-> packet_adapter <-> prism_collective_core
                  (MAC clock)        (clock crossing)   (250 MHz)
```

## Contracts

- **Clocks:** `prism_u280_clocks` derives the 250 MHz core clock and the
  125 MHz register clock from the 100 MHz board oscillator with one MMCM, so
  the two are phase aligned, and releases the power-on reset after the MMCM
  locks.
- **MAC bring-up:** `prism_cmac_bringup` resets the CMAC subsystem and writes
  its registers in the order of the OpenNIC driver: RS-FEC (when built with
  `RS_FEC=1`), receiver, and the transmitter once the receiver reports
  alignment. It keeps polling the receiver and falls back to remote fault
  indication when alignment is lost.
- **Frames:** the adapter drops frames not addressed to its port and gives the
  core whole frames at 250 MHz; the core's frames leave with their length in
  bytes.
- **Addresses:** port 0 answers at `LOCAL_MAC_BASE` (`02:50:52:49:53:00`) and
  accepts only operations whose context names `MANAGER_MAC`
  (`02:50:52:49:53:ff`) as their manager.

## Contract behavior

- The core is built with one port, Kulisch accumulation at 280 bits, at most
  two original terms per element and four exact banks; FP32 arrival
  accumulation is not included.
- A frame that arrives before the link is up is lost; nothing in the design
  waits for the link.
- `hbm_cattrip` is driven low, as every U280 design must.
- Without `__synthesis__` the CMAC subsystem has no transceivers: its frames
  enter and leave through stream ports in the MAC clock, which the board
  simulation drives.

## Related modules and concepts

- [`prism_collective_core`](prism_collective_core.md)
- [Alveo U280](../../../2-getting-started/u280.md)
