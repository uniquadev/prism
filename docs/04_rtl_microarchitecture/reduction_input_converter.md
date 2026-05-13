**Reduction Input Converter**

- **Description**: Small combinational unit that extracts a payload lane from the input frame at a given byte offset and converts it into an internal FP32 sample representation. Supports INT8 and FP32 payload element encodings.
- **Type**: Combinational
- **Location**: repo/rtl/src/components/reduction_input_converter.sv

- **Inputs**:
	- `frame` : packed frame bytes (Mini-Sharp little-endian payload ordering).
	- `byte_offset` : index into payload (bytes) where the lane starts.
	- `data_type` : `uint8` — identifies lane width and interpretation (e.g., `DTYPE_INT8`, `DTYPE_FP32`).

- **Outputs**:
	- `sample_fp32` : `uint32` — lane value converted to IEEE-754 FP32 internal representation.
	- `lane_bytes` : small integer (`3:0` or similar) — number of bytes consumed by the lane.
	- `data_type_supported` : `logic` — asserted when converter recognizes `data_type`.

- **Semantics & notes**:
	- The converter assumes `MINISHARP_PAYLOAD_OFFSET` to compute payload start; the caller supplies `byte_offset` relative to the payload start.
	- Conversion must preserve Mini-Sharp little-endian byte order when assembling FP32 words from bytes.
