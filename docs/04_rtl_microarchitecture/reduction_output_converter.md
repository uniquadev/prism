**Reduction Output Converter**

- **Descrizione**: Unità combinazionale che converte un valore FP32 interno nella rappresentazione payload on-wire a seconda di `data_type` (es. UINT8 saturato per `DTYPE_INT8`, ordine little-endian diretto per `DTYPE_FP32`).
- **Tipo**: Combinazionale
- **Posizione**: repo/rtl/src/components/reduction_output_converter.sv

- **Input**:
	- `value_fp32` : `uint32` — valore FP32 in rappresentazione interna.
	- `data_type`  : `uint8` — codifica target dell’elemento.

- **Output**:
	- `encoded_bytes` : `uint32` — fino a 4 byte che portano il valore codificato in ordine little-endian.
	- `lane_bytes` : intero piccolo (`3:0`) — numero effettivo di byte usati dalla lane.
	- `data_type_supported` : `logic` — alto quando il convertitore supporta il `data_type` richiesto.

- **Semantica & note**:
	- Per `DTYPE_INT8` il convertitore satura e scrive un singolo byte (ordine little-endian).
	- Per `DTYPE_FP32` il convertitore scrive i 4 byte FP32 in ordine little-endian.
	- I tipi non supportati impostano `data_type_supported = 0` e `lane_bytes = 0`.
