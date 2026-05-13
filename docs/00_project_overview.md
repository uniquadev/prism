# Project overview

Questo progetto è un prototipo accademico per l'esplorazione di primitive hardware per il calcolo in rete. Contiene RTL SystemVerilog per un datapath di reduction, un ambiente di verifica basato su Cocotb/Verilator che utilizza PCAP come input/output, un generatore di traffico Python, e un simulatore C++ sperimentale.

Struttura repository:

- `repo/rtl/`: codice SystemVerilog, moduli vendor per PCAP, runner e Makefile.
- `repo/traffic-gen/`: strumenti Python per generare PCAP di test.
- `repo/sim/`: simulatori C++ e codice sperimentale.
- `docs/`: documentazione tecnica e risultati.

Convenzioni di naming e licenze sono definite nella documentazione.
