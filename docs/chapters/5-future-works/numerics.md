# 5.3 Numerical formats

## Collectives

The current integrated datapath implements Reduce and AllReduce SUM.
Broadcast, ReduceScatter, and operators such as MIN and MAX require
implementation and verification of their operation-specific behavior.

Alternative accumulation policies, including stochastic rounding, need distinct
numerical semantics and RTL support. Their evaluation should report the
guarantees and costs associated with each policy.

## Shared scales

NVFP4 combines E2M1 values with scales shared by blocks of 16 elements and a
global scale, as described in the
[NVIDIA Transformer Engine documentation](https://docs.nvidia.com/deeplearning/transformer-engine/features/low_precision_training/nvfp4/nvfp4.html).

**Protocol and datapath work.** Define how to transmit scales, preserve block
boundaries during repacketization, and accumulate the decoded values.
Exact summation of decoded values retains the error introduced by the initial
quantization.

**Evaluation.** Compare numerical error and throughput with the currently
supported formats, including the cost of scale handling and block alignment.
