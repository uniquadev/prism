# 5.4 Applications

## Convergence

The next application-level question is whether more accurate reductions can
reach a prescribed solution quality in fewer iterations or less time.
PRISM's reproducible reduction results provide a starting point for this study.

[Cacciola et al.](https://arxiv.org/html/2301.01651v2) study SGD convergence in
low-precision formats and show benefits from increased accumulator precision in
logistic regression experiments. Their changes concern local computations;
the effect of improving only the reduction between ranks needs a separate test.

## Method

Insert conventional and Kulisch reductions into the complete application loop:

- **AI:** gradient aggregation during distributed training;
- **HPC:** dot-product reductions in an iterative solver.

Keep data, initialization, algorithm parameters, local computation precision,
and result precision the same. Feed each reduction result into the following
iteration. Repeat training comparisons across multiple seeds.

## Measurements

| Measure | Purpose |
| --- | --- |
| Numerical error | Compare reduction and final-solution accuracy against a common reference. |
| Iterations to the same quality threshold | Test whether the reduction changes convergence. |
| Time to the same quality threshold | Include computation, communication, and lossless compression costs. |

Use a common criterion to assess solution quality for both reduction modes.
The [software compression study](protocol.md#accumulator-compression)
estimates transport cost; convergence requires reductions inside the iterative
application, with their outputs affecting subsequent computation.
