**Mini-Sharp Parser**

- **Descrizione**: Estrattore combinazionale che decodifica i campi dell’header Mini-Sharp da un frame Ethernet ricostruito. Controlla i bound su `MINISHARP_PAYLOAD_OFFSET` ed espone i campi parsati alla logica a valle.
- **Tipo**: Combinazionale (senza registri)
- **Posizione**: repo/rtl/src/components/minisharp_parser.sv

- **Input**:
  - `frame` : byte impacchettati, larghezza = `(MAX_PACKET_BYTES*8)` bit — frame ricostruito completo.
  - `frame_len` : `uint16` — lunghezza del frame ricostruito in byte.

- **Output (nomi e larghezze)**:
  - `valid_minisharp` : `logic` — header presente e frame sufficientemente lungo.
  - `chunk_id` : `uint32` — indice del chunk (assemblato little-endian).
  - `p_size`   : `uint32` — dimensione del payload in byte.
  - `flow_id`  : `uint16` — identificatore del flow (campo nuovo, parte della chiave di contesto).
  - `operation_id` : `uint16` — `op_flags` esteso a zero (shim di compatibilità per i decoder esistenti).
  - `collective_op` : `uint8` — classe di operazione collettiva (es. REDUCE).
  - `data_type` : `uint8` — codifica dell’elemento payload (INT8/FP32/etc).
  - `collective_flags` : `uint8`.
  - `reserved` : `uint8`.
  - `expected_contributions` : `uint16` — numero di contributori per questo chunk.
  - `contribution_index` : `uint16` — indice del contributore all’interno del gruppo.
  - `is_reduce_sum_int8` : `logic` — flag di comodo usato dal switch core.

- **Semantica & note**:
  - Il parser legge `flow_id` (2 byte) e `op_flags` (1 byte). Per compatibilità con i moduli che si aspettano un `operation_id` a 16 bit, estende `op_flags` con 8 zeri a sinistra e lo espone come `operation_id`.
  - `MINISHARP_PAYLOAD_OFFSET` e gli altri offset sono definiti in `mini_sharp_pkg.sv`.
  - Il chiamante (es. `mini_sharp_switch_core`) deve verificare `valid_minisharp` prima di usare gli altri output.

- **Vicini / Uso**:
  - Instanziato da `mini_sharp_switch_core` per estrarre i campi di header utili al routing e per alimentare `collective_engine`.
