# Ispezionare il traffico PRISM con Wireshark

PRISM include il dissector Lua `repo/prism-ccl/wireshark/prism.lua` per il
formato wire 2.0. Decodifica gli header CONTROL, DATA, RESULT e PROGRESS e i
NumberGroup di DATA/RESULT. I filtri di visualizzazione usano `prism.*`;
non serve una build personalizzata di Wireshark.

## Guida all'installazione

Copia `repo/prism-ccl/wireshark/prism.lua` nella cartella personale dei plugin
Lua, creandola se necessario.

- Windows: `%APPDATA%\Wireshark\plugins`
- Linux e macOS: `~/.local/lib/wireshark/plugins`

Ricarica il plugin con **Analizza → Ricarica plugin Lua** (`Ctrl+Shift+L`) o
riavvia Wireshark. Il percorso esatto in uso è indicato in
**Aiuto → Informazioni su Wireshark → Cartelle → Plugin Lua personali**.

## Ispezionare una cattura

L'esperimento RTL SINGLE può generarla con
`make experiment EXP=02-experiment-numbergroup-single ARGS="collect --capture-pcaps"`.
Salva PCAP per porta e `all_ports.pcapng`, ordinato per timestamp del simulatore,
nella directory `captures/<policy>/` della run. Sull'host di una U280, il
traffico della scheda si cattura con
`sudo tcpdump -i <interfaccia> -w capture.pcap ether proto 0x88b5`.

Apri una cattura PRISM e usa `prism.opcode == 0x02` per i pacchetti DATA o
`prism.group.format == 0x80` per i NumberGroup Kulisch. Il dissector legge
la larghezza Kulisch da un CONTROL `STAGE`; se quel frame manca, imposta
**Fallback Kulisch width** nelle preferenze del plugin alla larghezza configurata
per l'operazione. I valori dei gruppi sono mostrati come byte.
Usa `prism.flags.accumulation_inexact == 1` per trovare un errore aritmetico terminale.
