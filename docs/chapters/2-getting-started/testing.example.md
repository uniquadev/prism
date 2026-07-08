# 2.2 Testing

Testing should grow from small deterministic packet cases toward reproducible
traffic scenarios.

## Test layers

1. **Parser tests** check field extraction and malformed headers.
2. **Operation tests** check each primitive operation independently.
3. **Sequencing tests** check rank, collective, and fragment ordering.
4. **Backpressure tests** check buffer behavior under stalls.
5. **Trace tests** replay generated traffic and compare expected outputs.

## Failure records

Each meaningful failure should record:

- input packet or trace identifier,
- expected output,
- observed output,
- waveform path when available,
- root cause once understood,
- regression test added after the fix.

This page should become the bridge between the verification environment and the
evidence discussed in [4. Results](../4-results/index.md).
