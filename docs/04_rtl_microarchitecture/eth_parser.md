**Parser Ethernet (eth_parser)**

- **Descrizione**: Estrattore combinazionale dell’header Ethernet. Restituisce MAC di destinazione/sorgente, EtherType e un flag di validità. Usato come filtro veloce per il traffico di riduzione.
- **Tipo**: Combinazionale
- **Posizione**: repo/rtl/src/components/eth_parser.sv

- **Ingressi**:
	- `frame` : byte del frame impacchettati.
	- `frame_len` : `uint16` — lunghezza del frame ricostruito in byte.

- **Uscite**:
	- `dst_mac` : `uint48` — MAC di destinazione dall’header Ethernet.
	- `src_mac` : `uint48` — MAC di sorgente.
	- `ethertype` : `uint16`.
	- `is_reduction_ethertype` : `logic` — alto se `ethertype == ETHERTYPE_REDUCTION`.
	- `valid_eth_frame` : `logic` — vero quando `frame_len >= ETH_HDR_BYTES`.

- **Uso**:
	- Instanziato da `mini_sharp_switch_core` come filtro di primo stadio; se `is_reduction_ethertype` è falso lo switch di solito bypassa il parser Mini-Sharp e inoltra il frame.
