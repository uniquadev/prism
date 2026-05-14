**Convertitore di input per la riduzione**

- **Descrizione**: Piccola unità combinazionale che estrae una lane del payload dal frame di input a un dato offset in byte e la converte in una rappresentazione FP32 interna. Supporta le codifiche payload INT8 e FP32.
- **Tipo**: Combinazionale
- **Posizione**: repo/rtl/src/components/reduction_input_converter.sv

- **Ingressi**:
	- `frame` : byte del frame impacchettati (payload Mini-Sharp in ordine little-endian).
	- `byte_offset` : indice all’interno del payload (byte) in cui inizia la lane.
	- `data_type` : `uint8` — identifica larghezza e interpretazione della lane (es. `DTYPE_INT8`, `DTYPE_FP32`).

- **Uscite**:
	- `sample_fp32` : `uint32` — valore della lane convertito in rappresentazione FP32 IEEE-754 interna.
	- `lane_bytes` : intero piccolo (`3:0` o simile) — numero di byte consumati dalla lane.
	- `data_type_supported` : `logic` — alto quando il convertitore riconosce `data_type`.

- **Semantica & note**:
	- Il convertitore assume `MINISHARP_PAYLOAD_OFFSET` per calcolare l’inizio del payload; il chiamante fornisce il `byte_offset` relativo all’inizio del payload.
	- La conversione deve preservare l’ordine little-endian di Mini-Sharp quando si assembla una parola FP32 dai byte.
