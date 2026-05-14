# Requirements

Funzionalità attuali verificate:

- Flusso end-to-end: `traffic-gen` → PCAP input → `pcap_parse.sv` → RTL → `pcap_dumper.sv` → PCAP output → Cocotb checks.
- Operazione verificata: `REDUCE/SUM/INT8` con accumulo intermedio in FP32.

Requisiti funzionali principali:

- Supportare riduzione collettiva BF16, FP16
- Interfaccia AXI-stream per ingressi e uscite (pacchetti multi-beat).