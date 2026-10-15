# 4. Risultati

La valutazione affronta tre domande: quanto rapidamente il nodo SINGLE esegue
una collettiva, quanto traffico richiede un risultato esatto e quante risorse
FPGA occupa il core attuale. Queste pagine raccolgono le misure e le figure del
capitolo di valutazione della tesi.

<div class="results-highlights" markdown="1">

<div class="results-highlight" markdown="1">

<span class="results-highlight__label">Simulazione RTL</span>
<span class="results-highlight__value">110,5 Gbit/s</span>

Throughput aggregato dei frame RESULT con ingressi FP32 e uscita AUTO, su due
porte con periodo simulato di 4 ns.

[Prestazioni →](performance.md)

</div>

<div class="results-highlight" markdown="1">

<span class="results-highlight__label">Stima software</span>
<span class="results-highlight__value">87,2–93,4%</span>

Riduzione dei byte dei frame RESULT con AUTO + compressione adattiva rispetto
al Kulisch uniforme, nei quattro vettori valutati.

[Traffico →](traffic.md)

</div>

<div class="results-highlight" markdown="1">

<span class="results-highlight__label">Implementazione FPGA</span>
<span class="results-highlight__value">40,64% LUT</span>

Occupazione post-route della build a una porta per la scheda U280, che rispetta
i vincoli di timing a 250 MHz; il profilo esclude il percorso FP32 di arrivo.

[Risorse →](resources.md)

</div>

</div>

## Come leggere i risultati

| Sezione | Contenuto |
| --- | --- |
| [Prestazioni](performance.md) | Throughput DATA e RESULT, tempo di risposta AllReduce e latenza dell'ultimo contributo. |
| [Traffico](traffic.md) | Risparmio di pacchetti con AUTO e compressione dei superaccumulatori nei diversi carichi. |
| [Risorse](resources.md) | Occupazione post-route della build per la scheda U280 e configurazione del suo profilo. |

Le prestazioni provengono dalla simulazione RTL. La compressione è uno studio
software di un'estensione proposta per il protocollo. Le risorse provengono dai
report di implementazione FPGA. Throughput sulla scheda, potenza e funzionamento
multi-switch rientrano negli [sviluppi hardware](../5-future-works/hardware.md).

I sei grafici sono quelli della tesi, disponibili qui in formato vettoriale
ingrandibile in italiano e inglese. Accanto a ogni figura sono riportate la
configurazione e le convenzioni di misura.
