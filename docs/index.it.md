---
title: PRISM
---

# PRISM

PRISM (**Precision-aware Reduction In-Switch Module**) è un prototipo RTL open
source per lo studio delle operazioni collettive in-network (INC) su FPGA. Il progetto studia
come riduzioni collettive quali `REDUCE_SUM`[^mpi-reduce] possano essere
parzialmente trasferite dallo stack di comunicazione dell'acceleratore host
(CPU/GPU) al data plane della rete. PRISM si colloca quindi nella direzione
aperta da Mellanox/NVIDIA SHARP[^sharp]: eseguire parte della riduzione
nell'hardware di switching per diminuire il traffico agli endpoint e la latenza
delle collettive.

!!! abstract "Obiettivo"

    PRISM **non** cerca di clonare SHARP, né di riprodurre tutte le
    funzionalità di uno switch ASIC InfiniBand o Ethernet commerciale. È invece
    uno strumento hardware ispezionabile per studiare la microarchitettura delle
    primitive INC nei vincoli di una FPGA. La domanda del primo prototipo è più
    circoscritta: **come può un datapath RTL backpressurable configurare ed
    eseguire l'accumulazione streaming di operazioni collettive rendendo
    esplicita la propria politica numerica?**

Il datapath espone un'interfaccia AXI-Stream a 512 bit. Per il primo prototipo,
**OpenNIC è la piattaforma di riferimento**: fornisce la shell entro cui
sintetizzare PRISM su FPGA e l'integrazione con la NIC, i driver e il software
host.

Sul piano numerico, PRISM studia riduzioni in virgola mobile riproducibili.
Poiché l'addizione floating-point non è associativa, alberi di riduzione o
ordini di scheduling diversi possono produrre risultati differenti a livello di
bit. Il progetto confronta quindi il profilo di riferimento `FP32_ARRIVAL` con un
accumulatore lungo in stile Kulisch[^kulisch], misurandone area, latenza,
throughput e riproducibilità.

Sul piano dell'architettura, l'RTL corrente è un nodo collettivo `SINGLE` con due
porte, non uno switch Layer-2 convenzionale. Implementa buffering per porta,
arbitraggio a livello di frame, backpressure, CONTROL, riduzione, routing bounded
dei risultati e replica. Non implementa forwarding Ethernet trasparente, VOQ,
crossbar generale, packet memory condivisa, VLAN/ACL/QoS o un datapath ad albero
multi-switch.

Il codice sorgente più recente è disponibile nel
[repository GitHub di PRISM](https://github.com/uniquadev/prism).

## Citazione

Se utilizzi PRISM nel tuo progetto, cita il repository e/o la tesi:

```bibtex
--8<-- "docs/assets/references.bib"
```

## Guida alla lettura

<div class="grid cards" markdown>

-   :material-map-marker-path: **Prima lettura**

    Inizia da [1.1 Riproducibilità](chapters/1-introduction/reproducibility.md),
    quindi passa alla panoramica [2. Per iniziare](chapters/2-getting-started/index.md).

-   :material-chip: **Vista hardware**

    Prosegui con le pagine [3.1 Protocollo](chapters/3-architecture/1.protocol.md)
    e [3.2 Pipeline](chapters/3-architecture/2.pipeline.md).

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
