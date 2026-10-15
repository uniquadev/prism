---
title: PRISM
---

# ![PRISM](assets/images/prism_logo.png){ .prism-logo .off-glb width="260" height="58" } {#prism .prism-title}

PRISM (**Precision-aware Reduction In-Switch Module**) è un prototipo RTL open
source per lo studio delle operazioni collettive in-network (INC) su FPGA. Il progetto studia
come riduzioni collettive quali `REDUCE_SUM`[^mpi-reduce] possano essere
parzialmente trasferite dallo stack di comunicazione dell'acceleratore host
(CPU/GPU) al data plane della rete con attenzione alla riproducibilità. PRISM si colloca quindi nella direzione
aperta da Mellanox/NVIDIA SHARP[^sharp]: eseguire parte della riduzione
nell'hardware di switching per diminuire il traffico agli endpoint e la latenza
delle collettive.

!!! abstract "Obiettivo"

    PRISM **non** cerca di clonare SHARP, né di riprodurre tutte le
    funzionalità di uno switch ASIC InfiniBand o Ethernet commerciale. È invece
    uno strumento hardware ispezionabile per studiare le primitive INC nei
    vincoli di una FPGA. La domanda è: **come può un datapath simile a quello di
    uno switch combinare forwarding a line rate, accumulazione streaming delle
    collettive e aritmetica floating-point riproducibile?**

Il datapath espone un'interfaccia AXI-Stream a 512 bit. La piattaforma hardware
è la AMD Alveo U280: la [build della scheda](chapters/2-getting-started/u280.md)
collega il core a una porta 100G tramite il sottosistema CMAC e il packet adapter
della shell OpenNIC, senza interfaccia host. Gli host partecipano solo via Ethernet.

Sul piano numerico, PRISM studia riduzioni in virgola mobile riproducibili.
Poiché l'addizione floating-point non è associativa, alberi di riduzione o
ordini di scheduling diversi possono produrre risultati differenti a livello di
bit. Il progetto confronta quindi il profilo di riferimento `FP32_ARRIVAL` con un
accumulatore lungo in stile Kulisch[^kulisch], misurandone area, latenza,
throughput e riproducibilità.

L'[architettura finale](chapters/3-architecture/index.md) usa un core collettivo
riutilizzabile e parametrico nel numero di porte. Implementa buffering,
backpressure, CONTROL, riduzione, routing e replica dei risultati;
`prism_u280_top` collega lo stesso RTL alla porta 100G della scheda. Forwarding,
VOQ, crossbar generale e aggregazione multi-switch restano fasi successive.

Il codice sorgente più recente è disponibile nel
[repository GitHub di PRISM](https://github.com/uniquadev/prism).

## Citazione

Se utilizzi PRISM nel tuo progetto, cita il repository e/o la tesi:

```bibtex
--8<-- "docs/assets/references.bib"
```

## Guida alla lettura

[1.1 Riproducibilità](chapters/1-introduction/reproducibility.md) presenta la
motivazione, [2. Per iniziare](chapters/2-getting-started/index.md) spiega come
eseguire test, esperimenti e la scheda, [3.1 Protocollo](chapters/3-architecture/1.protocol.md)
e [3.2 Pipeline](chapters/3-architecture/2.pipeline.md) descrivono l'hardware, e
[4. Risultati](chapters/4-results/index.md) raccoglie le misure.


[^mpi-reduce]: MPI Forum, *MPI 4.1 Standard*, `MPI_Reduce`. Lo standard osserva
    che le implementazioni possono cambiare l'ordine di riduzione sfruttando
    associatività e commutatività e che questo può modificare il risultato
    dell'addizione in virgola mobile.
    https://www.mpi-forum.org/docs/mpi-4.1/mpi41-report/node130.htm
[^sharp]: Mellanox SHARP: Scalable Hierarchical Aggregation and Reduction Protocol.
[^kulisch]: Kulisch, Ulrich W. *Computer Arithmetic and Validity: Theory,
    Implementation, and Applications.* Walter de Gruyter, 2002.
