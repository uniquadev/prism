# Formato del pacchetto Mini-Sharp

## Politica sull’ordine dei byte

L’header Ethernet mantiene l’ordine dei byte standard di Ethernet/rete.

Tutti i campi multi-byte personalizzati Mini-Sharp sono codificati in little-endian.

Tutti gli elementi payload multi-byte Mini-Sharp sono codificati in little-endian.

I campi a singolo byte come `collective_op`, `op_flags`, `data_type`, `collective_flags`, `reserved` e gli elementi payload `DTYPE_INT8` non presentano ambiguità sull’ordine dei byte.

Header Ethernet: 14 byte.

Header Mini-Sharp (implementazione corrente, breaking change): 19 byte composti da:

- `chunk_id` (4 byte)
- `p_size` (4 byte)
- `flow_id` (2 byte)
- `collective_op` (1 byte)
- `op_flags` (1 byte)  # il significato dipende da `collective_op` (per REDUCE contiene l’operatore di riduzione)
- `data_type` (1 byte)
- `collective_flags` (1 byte)
- `reserved` (1 byte)
- `expected_contributions` (2 byte)
- `contribution_index` (2 byte)

Riepilogo offset (rispetto all’header Ethernet):

- `CHUNK_ID_OFFSET = 0`
- `P_SIZE_OFFSET = 4`
- `FLOW_ID_OFFSET = 8`
- `COLLECTIVE_OP_OFFSET = 10`
- `OP_FLAGS_OFFSET = 11`
- `DTYPE_OFFSET = 12`
- `FLAGS_OFFSET = 13`
- `RESERVED_OFFSET = 14`
- `EXPECTED_OFFSET = 15`
- `CONTRIB_OFFSET = 17`

Lunghezza del frame attualmente verificata: 14 (Ethernet) + 19 (Mini-Sharp) + dimensione del payload.
