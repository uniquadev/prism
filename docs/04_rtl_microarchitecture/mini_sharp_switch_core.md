**mini_sharp_switch_core**

- **Descrizione**: Modulo di livello superiore dello switch che consuma beat AXI4-Stream, ricostruisce frame Ethernet completi, analizza gli header e inoltra i frame invariati (bypass) oppure coordina la riduzione con `collective_engine`. Il modulo implementa una FSM esplicita con separazione netta tra logica di next-state, registro di stato e logica di output.
- **Tipo**: Sequenziale (FSM)
- **Posizione**: repo/rtl/src/top/mini_sharp_switch_core.sv

- **I/O di livello superiore (a grandi linee)**:
  - Ingressi:
    - `clk`, `rst_n` : clock e reset attivo basso.
    - AXI4-Stream in: `in_tdata` (larghezza = `AXIS_WIDTH`), `in_tstrb`, `in_tuser` (contiene metadata come src MAC), `in_tvalid`, `in_tlast`, `in_tready` (stretta di mano).
    - `engine_done_valid`, `engine_out_valid` (da `collective_engine`).
  - Uscite:
    - AXI4-Stream out: `out_tdata`, `out_tstrb`, `out_tuser`, `out_tvalid`, `out_tlast` e `out_tready` (retropressione del peer).

- **Istanze interne / vicini**:
  - `eth_parser` — usato per filtrare rapidamente i frame via EtherType.
  - `minisharp_parser` — estrae i campi dell’header Mini-Sharp (`flow_id`, `op_flags`, ecc.).
  - `collective_engine` — invocato quando si riconosce un pacchetto di riduzione supportato.

- **FSM (concettuale)**:
  - `STATE_RX`       : accumula i beat AXI in un buffer di frame interno finché non arriva `in_tlast`.
  - `STATE_PROCESS`  : esegue i parser (`eth_parser` + `minisharp_parser`) e decide il percorso.
  - `STATE_WAIT_ENGINE`: inoltra il frame a `collective_engine` e aspetta completamento/emissione.
  - `STATE_TX_PREPARE`: prepara il/i frame in uscita.
  - `STATE_TX_SEND`  : trasmette i frame preparati rispettando `out_tready`/`out_tlast`.

- **Note di design**:
  - Il modulo separa: logica combinazionale di next-state (calcola `next_state`), registro di stato sequenziale (`always_ff` che aggiorna `state <= next_state`) e logica di output (output combinazionali derivati da stato e ingressi). Questo schema facilita la ragionamento formale/sequenziale e aiuta a chiudere timing.
  - Un pacchetto viene inviato a `collective_engine` quando `eth_parser.is_reduction_ethertype` && `minisharp_parser.valid_minisharp` && la riduzione è supportata per i campi parsati.
  - Il core riscrive la MAC sorgente quando `collective_engine` emette un frame ridotto; `flow_id` dal header parsato viene passato al motore e riscritto nei frame emessi per mantenere la tracciabilità.
