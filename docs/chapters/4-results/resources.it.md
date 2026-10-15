# 4.3 Risorse

I dati provengono dall'implementazione **post-route con Vivado 2022.1** della
build per la scheda U280 (`make u280`, RS-FEC attivo): il core SINGLE con
**una porta e quattro banchi Kulisch a 280 bit**, senza il percorso FP32 di
arrivo, dietro il sottosistema CMAC e il packet adapter della shell OpenNIC. Il
progetto rispetta i vincoli di timing a 250 MHz (WNS +0,005 ns, WHS 0,000 ns).

## Occupazione su U280

| Risorsa | Build della scheda | Core | Quota del dispositivo |
| --- | ---: | ---: | ---: |
| CLB LUT | 529.840 | 519.855 | 40,64% |
| Registri CLB | 542.583 | 508.849 | 20,81% |
| Tile BRAM | 281 | 263,5 | 13,94% |
| DSP | 2 | 2 | 0,02% |

Il sottosistema CMAC e il packet adapter occupano circa 10.000 LUT; il resto è
il core. Il core è diviso su due SLR, il 62,95% delle LUT di SLR1 e il 59,70% di
SLR2 (vedi [`prism_u280_top`](../3-architecture/4-modules/components/prism_u280_top.md)).
La stima vectorless di Vivado della potenza on-chip è 13,6 W, di cui 10,2 W
dinamici.

I dati riguardano la build della scheda; le
[simulazioni di prestazioni a due porte](performance.md) usano una configurazione
diversa. Anche la larghezza di 280 bit dei banchi aritmetici differisce dalla
rappresentazione Kulisch serializzata a 320 bit usata nel
[confronto del traffico](traffic.md). La tesi riporta una revisione precedente
del core standalone, con 682.704 LUT (52,37%).

## Ambito dell'implementazione

Throughput, tempo di risposta e potenza sulla scheda rientrano negli
[sviluppi hardware](../5-future-works/hardware.md).

??? info "Provenienza del report"

    `post_route_physopt/utilization.rpt` nella cartella di uscita della build che
    ha prodotto il bitstream pubblicato con RS-FEC attivo, del 15 ottobre 2026.

    SHA-256 del report:
    `0071bef0b4fd6ee179a55f3f5ba67ec26861b72179dfd45d1b7e7d37eeadf066`.
