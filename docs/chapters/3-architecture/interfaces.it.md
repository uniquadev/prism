# 3.3 Interfacce

!!! note "Lavori in corso"

    Questa pagina è intenzionalmente un semplice segnaposto architetturale. Le
    interfacce software e hardware non sono ancora state scelte né rese stabili.

PRISM dovrà definire in seguito questi confini di integrazione:

- **runtime dei rank ↔ Host Coordinator** — arrivo alla collettiva e consegna di
  `START`, `DONE` oppure dello stesso errore terminale;
- **Host Coordinator ↔ Aggregation Manager** — richiesta, osservazione del
  completamento e rilascio di un'operazione collettiva;
- **Aggregation Manager ↔ switch** — consegna delle transazioni di gestione
  in-band definite nel [protocollo](protocol.md);
- **datapath dello switch ↔ RTL PRISM** — flussi di pacchetti, backpressure e
  metadati;
- **ambiente di test ↔ generatore di traffico** — frame, beat AXI4-Stream e
  catture usati per la verifica.

Il capitolo sul protocollo descrive il comportamento richiesto a questi confini
senza scegliere API, meccanismi RPC, trasporti host, interfacce a registri o
porte RTL concrete. Queste decisioni verranno documentate qui quando inizierà la
relativa progettazione.
