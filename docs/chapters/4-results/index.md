# 4. Results

The evaluation asks three questions: how quickly the SINGLE node processes a
collective, how much traffic an exact result requires, and how much FPGA logic
the current core uses. These pages bring together the measurements and figures
from the thesis evaluation chapter.

<div class="results-highlights" markdown="1">

<div class="results-highlight" markdown="1">

<span class="results-highlight__label">RTL simulation</span>
<span class="results-highlight__value">110.5 Gbit/s</span>

Aggregate RESULT throughput with FP32 inputs and AUTO output, across two ports
at a simulated 4 ns period.

[Performance →](performance.md)

</div>

<div class="results-highlight" markdown="1">

<span class="results-highlight__label">Software estimate</span>
<span class="results-highlight__value">87.2–93.4%</span>

Fewer RESULT-frame bytes with AUTO + adaptive compression than uniform Kulisch,
across the four evaluated workload vectors.

[Traffic →](traffic.md)

</div>

<div class="results-highlight" markdown="1">

<span class="results-highlight__label">FPGA implementation</span>
<span class="results-highlight__value">40.64% LUTs</span>

Post-route use of the one-port U280 board build, which meets timing at 250 MHz;
the FP32 arrival path is excluded from this profile.

[Resources →](resources.md)

</div>

</div>

## Reading the results

| Section | What it establishes |
| --- | --- |
| [Performance](performance.md) | DATA and RESULT throughput, AllReduce response time, and final-contribution latency. |
| [Traffic](traffic.md) | Native AUTO packet savings and workload-dependent superaccumulator compression. |
| [Resources](resources.md) | Post-route utilization of the U280 board build and the scope of its profile. |

The performance figures come from RTL simulation. Compression is a software
study of a proposed protocol extension. Resource figures come from FPGA
implementation reports. On-board throughput, power, and multi-switch operation
remain part of the [hardware work](../5-future-works/hardware.md).

The six graphs are the thesis figures, supplied here as zoomable vectors in
English and Italian. Each page states the configuration and accounting rules
beside its figures.
