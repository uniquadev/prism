# 4.3 Resources

The figures come from the **Vivado 2022.1 post-route** implementation of the
U280 board build (`make u280`, RS-FEC on): the SINGLE core with **one port and
four 280-bit Kulisch banks**, without the FP32 arrival path, behind the CMAC
subsystem and packet adapter of the OpenNIC shell. The design meets timing at
250 MHz (WNS +0.005 ns, WHS 0.000 ns).

## U280 utilization

| Resource | Board build | Core | Share of device |
| --- | ---: | ---: | ---: |
| CLB LUTs | 529,840 | 519,855 | 40.64% |
| CLB registers | 542,583 | 508,849 | 20.81% |
| BRAM tiles | 281 | 263.5 | 13.94% |
| DSPs | 2 | 2 | 0.02% |

The CMAC subsystem and the packet adapter take about 10,000 LUTs; the rest is
the core. The core is split over two SLRs, 62.95% of the LUTs of SLR1 and
59.70% of SLR2 (see [`prism_u280_top`](../3-architecture/4-modules/components/prism_u280_top.md)).
Vivado's vectorless estimate of on-chip power is 13.6 W, 10.2 W of it dynamic.

These figures describe the board build; the
[two-port performance simulations](performance.md) use a different
configuration. The 280-bit arithmetic-bank width also differs from the 320-bit
serialized Kulisch representation used in the [traffic comparison](traffic.md).
The thesis reports an earlier revision of the standalone core, at 682,704 LUTs
(52.37%).

## Implementation scope

Throughput, response time and power on the card itself are part of the
[hardware work](../5-future-works/hardware.md).

??? info "Report provenance"

    `post_route_physopt/utilization.rpt` in the output directory of the build
    that produced the published RS-FEC-on bitstream, dated 15 October 2026.

    Report SHA-256:
    `0071bef0b4fd6ee179a55f3f5ba67ec26861b72179dfd45d1b7e7d37eeadf066`.
