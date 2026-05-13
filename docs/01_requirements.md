# Requirements

Funzionalità attuali verificate:

- Flusso end-to-end: `traffic-gen` → PCAP input → `pcap_parse.sv` → RTL → `pcap_dumper.sv` → PCAP output → Cocotb checks.
- Operazione verificata: `REDUCE/SUM/INT8` con accumulo intermedio in FP32.

Requisiti funzionali principali:

- Supportare riduzione collettiva su payload INT8 con accumulo FP32.
- Interfaccia AXI-stream per ingressi e uscite (pacchetti multi-beat).
- Ambiente di verifica basato su Cocotb e Verilator.

Funzionalità future (non implementate):

- Supporto nativo per FP32 payload, BF16, FP16.
- Politiche avanzate per la tabella di contesti (eviction, reorder).
