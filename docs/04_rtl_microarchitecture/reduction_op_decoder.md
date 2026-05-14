**Reduction Operation Decoder**

- **Descrizione**: Decodifica l’identificatore di riduzione a livello di protocollo in un’operazione ALU FP32 primitiva e in segnali di controllo che indicano se serve accumulo e/o finalizzazione (es. `AVG` richiede post-scaling).
- **Tipo**: Combinazionale
- **Posizione**: repo/rtl/src/components/reduction_op_decoder.sv

- **Input**:
	- `operation_id` : `uint16` — campo di protocollo che porta l’operazione (il parser estende a zero `op_flags` in questo campo per compatibilità).

- **Output**:
	- `alu_op` : enumerazione che indica l’operazione ALU FP32 primitiva (SUM, MIN, MAX, ecc.).
	- `accumulation_supported` : `logic` — indica se l’operazione supporta la semantica di accumulo.
	- `needs_finalization` : `logic` — indica se serve un passaggio di finalizzazione (es. dividere per N per AVG) prima di emettere il valore ridotto.

- **Note**:
	- L’implementazione corrente supporta operazioni comuni: `SUM`, `MIN`, `MAX`, `AVG`. Le estensioni devono mantenere il decoder puramente combinazionale.
	- Poiché `operation_id` è uno shim di compatibilità (il parser estende a zero il byte `op_flags`), in futuro conviene passare `op_flags` direttamente e togliere questa estensione una volta aggiornati tutti i moduli.
