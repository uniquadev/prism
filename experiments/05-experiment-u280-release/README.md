# U280 release figures

Numbers and figures of the v1.0.0 board build, used in
[4.1 Performance](../../docs/chapters/4-results/performance.md) and
[4.3 Implementation](../../docs/chapters/4-results/resources.md).

- `data.json`: timing, utilization and power from the post-route reports of the
  published RS-FEC-on bitstream (`make u280`, Vivado 2022.1), and the line rates
  of the U280 profile from `make test SUITE=rtl-u280-profile` and
  `SUITE=rtl-result-wide-target`.
- `u280-placement-vivado.png`: the routed checkpoint in the Vivado device view,
  with the main blocks highlighted.
- `plot_figures.py`: draws the line-rate, placement and budget figures in
  English and Italian.

```sh
uv run --no-project --with matplotlib python experiments/05-experiment-u280-release/plot_figures.py
```

This is a record of one build, not a runnable experiment: there is no
`experiment.py`, so the launcher does not list it.
