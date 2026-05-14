**Collective Engine**

- **Descrizione**: Motore di riduzione con stato che mantiene contesti per chunk, raccoglie contributi da più sender e emette un unico pacchetto ridotto quando il contesto è completo. I contesti sono identificati univocamente da `(flow_id, chunk_id)`.
- **Tipo**: Sequenziale (FSM)
- **Posizione**: repo/rtl/src/components/collective_engine.sv

- **I/O top-level (nomi e larghezze)**:
  - Input:
    - `clk`, `rst_n` : clock e reset attivo basso.
    - `in_valid` : `logic` — indica che `in_frame`/metadata sono validi.
    - `in_frame` : bit impacchettati che rappresentano il frame Ethernet completo (`(MAX_PACKET_BYTES*8)-1:0`).
    - `in_frame_len` : `uint16` — lunghezza del frame in byte.
    - `in_chunk_id` : `uint32` — identificatore del chunk.
    - `in_p_size` : `uint32` — dimensione del payload.
    - `in_operation_id` : `uint16` — op flags estesi a zero (campo di compatibilità).
    - `in_flow_id` : `uint16` — identificatore del flow (campo nuovo, usato come chiave di contesto).
    - `in_collective_op` : `uint8`.
    - `in_data_type` : `uint8`.
    - `in_collective_flags` : `uint8`.
    - `in_expected_contributions` : `uint16`.
    - `in_contribution_index` : `uint16`.
  - Output:
    - `done_valid` : `logic` — indica che l’aggiornamento del contesto è avvenuto.
    - `out_valid` : `logic` — indica che `out_frame` contiene un frame ridotto valido.
    - `out_frame` : bit impacchettati (`(MAX_PACKET_BYTES*8)-1:0`) — il frame Ethernet emesso.
    - `out_frame_len` : `uint16` — lunghezza di `out_frame`.

- **Comportamento interno / FSM**:
  - `STATE_IDLE`       : aspetta `in_valid`. Se accetta, cerca o alloca un contesto chiave `(`in_flow_id`, `in_chunk_id`)`.
  - `STATE_LANE_READ`  : legge una singola lane del payload e prepara sample + accumulatore per l’ALU.
  - `STATE_LANE_EXEC`  : applica `fp32_alu` usando l’operazione decodificata.
  - `STATE_LANE_WRITE` : salva l’accumulatore aggiornato; quando tutte le lane sono processate per il contributo/contenitore, aggiorna il contatore dei contributori e imposta l’emissione se il contesto è completo.
  - `STATE_EMIT`       : finalizza il payload ridotto (es. AVG) ed emette un frame Ethernet ridotto.

- **Note di design & invarianti**:
  - I contesti sono tracciati in array: `ctx_valid[]`, `ctx_chunk_id[]`, `ctx_flow_id[]`, `ctx_operation_id[]`, contatori dei contributori e accumulatori.
  - Il motore riscrive `flow_id` nell’header emesso per mantenere la tracciabilità.
  - La logica combinazionale di next-state è separata dal registro di stato (flip-flop) e dalla logica di output, come previsto dalle linee guida FSM del progetto.

- **Vicini / Connessioni**:
  - Input: guidato da `mini_sharp_switch_core` quando viene identificato un pacchetto di riduzione supportato.
  - Usa `reduction_input_converter`, `reduction_op_decoder`, `reduction_output_converter` e `fp32_alu`.

