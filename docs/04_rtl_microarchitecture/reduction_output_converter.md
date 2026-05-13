**Reduction Output Converter**

- **Description**: Combinational unit that converts an internal FP32 value into the on-wire payload representation according to `data_type` (e.g., saturating UINT8 for `DTYPE_INT8`, direct 4-byte little-endian order for `DTYPE_FP32`).
- **Type**: Combinational
- **Location**: repo/rtl/src/components/reduction_output_converter.sv

- **Inputs**:
	- `value_fp32` : `uint32` — FP32 value in internal representation.
	- `data_type`  : `uint8` — target element encoding.

- **Outputs**:
	- `encoded_bytes` : `uint32` — up to 4 bytes carrying the encoded value in little-endian byte order.
	- `lane_bytes` : small integer (`3:0`) — actual number of bytes used for the lane.
	- `data_type_supported` : `logic` — asserted when the converter supports the requested `data_type`.

- **Semantics & notes**:
	- For `DTYPE_INT8` the converter saturates and writes a single byte (little-endian order).
	- For `DTYPE_FP32` the converter writes the 4 FP32 bytes in little-endian order.
	- Unsupported types set `data_type_supported = 0` and `lane_bytes = 0`.
