---
title: MiniSharp
---

# MiniSharp

MiniSharp è un prototipo di ricerca RTL open source per le operazioni collettive
in-network (INC) su datapath FPGA per l'elaborazione dei pacchetti. Il progetto
studia come le operazioni collettive basate su riduzione, come l'aggregazione
`REDUCE_SUM`[^mpi-reduce], possano essere parzialmente trasferite dallo stack di
comunicazione dell'acceleratore host (CPU/GPU) al data plane della rete. In
questo senso, MiniSharp si ispira alla stessa direzione generale di
Mellanox/NVIDIA SHARP[^sharp], che ha dimostrato come l'elaborazione delle
riduzioni collettive possa essere spostata nell'hardware di switching per
ridurre il traffico di comunicazione e la latenza delle operazioni collettive.

!!! abstract "Obiettivo"

    MiniSharp **non** cerca di clonare SHARP, né di riprodurre tutte le
    funzionalità di uno switch ASIC InfiniBand o Ethernet commerciale. È invece
    uno strumento hardware compatto e ispezionabile per studiare la
    microarchitettura delle primitive INC nei vincoli di una FPGA. La domanda
    centrale è più circoscritta e sperimentale: **come può un datapath RTL simile
    a quello di uno switch supportare contemporaneamente l'inoltro dei pacchetti
    a line rate, l'accumulazione streaming delle operazioni collettive e una
    migliore riproducibilità in virgola mobile?**

Il progetto adotta un'interfaccia AXI-Stream a 512 bit ed è pensato per essere
integrato in una shell FPGA NIC/smartNIC, per esempio una piattaforma simile a
OpenNIC. Il data plane comprende parsing dei pacchetti, classificazione L2,
gestione di un EtherType personalizzato, versionamento del protocollo, Virtual
Output Queueing (VOQ), memoria condivisa per i pacchetti, arbitraggio egress a
livello di pacchetto, inoltro cut-through e un motore streaming per le operazioni
collettive.

Dal punto di vista numerico, MiniSharp si concentra sulle riduzioni in virgola
mobile riproducibili. Le riduzioni FP32 convenzionali dipendono dall'ordine degli
operandi, perché l'addizione in virgola mobile non è associativa; alberi di
riduzione o ordini di scheduling differenti possono quindi produrre risultati
diversi a livello di bit. MiniSharp confronta un percorso di accumulazione FP32
di riferimento con un accumulatore lungo in stile Kulisch[^kulisch], con
l'obiettivo di misurare i compromessi di area, latenza, throughput e
riproducibilità dell'accumulazione esatta o quasi esatta in un datapath di rete
streaming.

Dal punto di vista dello switching, MiniSharp implementa uno **scheletro di data
plane ispirato agli switch**, non uno switch di produzione completo. Include
meccanismi comuni negli switch ad alte prestazioni, come arbitraggio per uscita,
buffering in stile VOQ, memorizzazione condivisa dei pacchetti, propagazione
della backpressure e scheduling a livello di pacchetto. Funzionalità avanzate
come elaborazione VLAN, ACL, motori di replica multicast, gerarchie QoS,
controllo della congestione basato su crediti, ECN/PFC, telemetria, isolamento
dei guasti e gestione dei buffer di livello produttivo sono intenzionalmente
fuori dall'ambito iniziale.

Il codice sorgente più recente è disponibile nel
[repository GitHub di MiniSharp](https://github.com/uniquadev/mini-sharp).

## Citazione

Se utilizzi MiniSharp nel tuo progetto, cita il repository e/o la tesi:

```bibtex
--8<-- "docs/assets/references.bib"
```

## Guida alla lettura

<div class="grid cards" markdown>

-   :material-map-marker-path: **Prima lettura**

    Inizia da [1.2 Riproducibilità](chapters/1-introduction/reproducibility.md),
    quindi passa alla panoramica [2. Per iniziare](chapters/2-getting-started/index.md).

-   :material-chip: **Vista hardware**

    Prosegui con le pagine [3.1 Protocollo](chapters/3-architecture/protocol.md)
    e [3.2 Pipeline](chapters/3-architecture/pipeline.md).

-   :material-chart-line: **Evidenze della tesi**

    Segui gli esperimenti aperti in [4. Risultati](chapters/4-results/index.md) e
    mantieni visibile il piano di scrittura in
    [5. Sviluppi futuri](chapters/5-future-works/index.md).

</div>


[^mpi-reduce]: MPI Forum, *MPI 4.1 Standard*, `MPI_Reduce`. Lo standard osserva
    che le implementazioni possono cambiare l'ordine di riduzione sfruttando
    associatività e commutatività e che questo può modificare il risultato
    dell'addizione in virgola mobile.
    https://www.mpi-forum.org/docs/mpi-4.1/mpi41-report/node130.htm
[^sharp]: Mellanox SHARP: Scalable Hierarchical Aggregation and Reduction Protocol.
[^kulisch]: Kulisch, Ulrich W. *Computer Arithmetic and Validity: Theory,
    Implementation, and Applications.* Walter de Gruyter, 2002.
[^mpi-collectives]: Operazioni collettive MPI:
    https://www.mpi-forum.org/docs/mpi-4.1/mpi41-report/node90.htm
