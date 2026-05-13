**Reduction Operation Decoder**

- **Description**: Decodes the protocol-level reduce identifier into a primitive FP32 ALU operation and control signals that indicate whether accumulation and/or finalization are required (e.g., `AVG` requires post-scaling).
- **Type**: Combinational
- **Location**: repo/rtl/src/components/reduction_op_decoder.sv

- **Inputs**:
	- `operation_id` : `uint16` — protocol field carrying the operation (parser zero-extends `op_flags` into this field for compatibility).

- **Outputs**:
	- `alu_op` : enumeration indicating the FP32 ALU primitive (SUM, MIN, MAX, etc.).
	- `accumulation_supported` : `logic` — whether the operation supports accumulation semantics.
	- `needs_finalization` : `logic` — whether a finalization step (e.g., divide by N for AVG) is required before emitting the reduced value.

- **Notes**:
	- Current implementation supports common ops: `SUM`, `MIN`, `MAX`, `AVG`. Additions should ensure the decoder stays purely combinational.
	- Because `operation_id` is a compatibility shim (parser zero-extends the `op_flags` byte), consider a future refactor to pass `op_flags` explicitly and remove the zero-extension once all modules are updated.
