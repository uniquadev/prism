# Riproducibilità in virgola mobile

L'addizione floating-point arrotonda dopo ogni operazione e non è associativa.
Ordini di arrivo diversi possono quindi produrre bit diversi. PRISM confronta
tre strategie per misurare il compromesso tra costo hardware, throughput e
riproducibilità.

## Concetti e profili

| Termine | Significato |
|---|---|
| Elemento | Un numero del vettore, per esempio `a[7]` |
| Lane | Una posizione di calcolo parallela |
| Tile | Un blocco di elementi consecutivi con maschera e metadati |
| Range | Le posizioni globali coperte dalla tile |
| Accumulator bank | Stato e percorso di calcolo indipendenti per più range |

Con 16 lane, le tile `[a0,...,a15]` e `[b0,...,b15]` vengono combinate in
parallelo: la lane \(i\) calcola la posizione \(i\).

| Profilo | Regola | Proprietà |
|---|---|---|
| `FP32_ARRIVAL` | Applica ogni contributo all'arrivo | Streaming, ma dipendente dall'ordine |
| `FP32_ORDERED` | Applica Contributor ID crescenti | Riproducibile, con reorder buffer |
| `KULISCH_FP32` | Deposita esattamente e arrotonda alla fine | Streaming e indipendente dall'ordine se la larghezza basta |

Qui **streaming** significa che ogni contributo può essere usato subito.
`FP32_ORDERED` può usare soltanto il prossimo Contributor ID e conserva quelli
arrivati in anticipo. Nel prototipo a due rank conserva la coppia; con più rank
l'RTL corrente aspetta tutti i contributi del range e poi li ripiega in ordine.
Quest'ultimo comportamento è corretto, ma batch.

La garanzia Kulisch è locale al nodo. Un parziale serializzato in FP32 introduce
un arrotondamento; una riduzione multi-switch esatta richiederebbe un formato
parziale lossless, non ancora assegnato dal protocollo.

## Parallelismo per 100 Gbit/s

Con \(b_d\) bit per elemento, \(L_d\) lane, frequenza \(f\) e initiation
interval \(II_d\):

\[
T_d=\frac{L_d b_d f}{II_d},
\qquad
L_{min}(d)=\left\lceil\frac{T_{goal}II_d}{b_d f}\right\rceil.
\]

A 250 MHz, con \(II=1\) e target 100 Gbit/s:

| Datatype | Lane minime | Lane per 512 bit/ciclo | Prototipo con 16 lane |
|---|---:|---:|---:|
| FP32 | 13 | 16 | 128 Gbit/s |
| FP16 | 25 | 32 | 64 Gbit/s |
| BF16 | 25 | 32 | 64 Gbit/s |
| INT8 | 50 | 64 | 32 Gbit/s |

Oggi `LANES=16` indica sia gli elementi della tile sia il parallelismo fisico.
FP16, BF16 e INT8 usano gli stessi 16 contenitori da 32 bit, quindi non
raddoppiano automaticamente le lane.

Una parametrizzazione più pulita separerebbe:

- `TILE_ELEMENTS=16`, granularità logica del range;
- issue slice FP32, numero di tile FP32 per ciclo;
- issue slice Kulisch per ogni larghezza compilata.

Un beat da 512 bit contiene una tile FP32, due tile FP16/BF16 o quattro tile
INT8. Processarlo in un ciclo richiede quindi molteplicità 1, 2 o 4.

Con \(N\) contributor e \(L_d\) risultati per ciclo servono \(NL_d\) operandi
per ciclo. Una riduzione binaria richiede capacità equivalente a:

\[
A_{binary}=(N-1)L_d.
\]

Kulisch deve invece accettare \(NL_d\) deposit per ciclo. ALLREDUCE replica il
risultato senza ripetere la riduzione.

Anche l'uscita può limitare il sistema: 64 input INT8 convertiti in FP32
producono \(64\cdot32=2048\) bit. Una porta da 512 bit richiede quattro cicli o
backpressure.

## Accumulazione Kulisch

Un valore finito può essere scritto come:

\[
x=(-1)^sM2^{e-(p-1)}.
\]

Kulisch allinea \(M\) in un accumulatore fixed-point, somma senza arrotondamenti
intermedi e converte in floating point una sola volta alla fine. NaN, infiniti
e zeri con segno sono tracciati separatamente.

Nel RTL corrente FP32 e Kulisch usano le stesse 16 lane. Le larghezze 64, 288 e
320 selezionano la capacità numerica, ma lo scheduler conserva ogni lane usando
lo stato fisico massimo `WIDTH_2=320`. Non sono tre memorie di accumulatori
indipendenti.

Il costo del solo stato numerico è circa:

\[
S_{Kulisch}\approx B R_b L_K W_K,
\]

con \(B\) bank, \(R_b\) range per bank, \(L_K\) lane e \(W_K\) bit per lane.
Per questo il parallelismo Kulisch deve essere configurabile separatamente da
quello FP32.

## Larghezza dell'accumulatore

Per una somma scalare di \(R\) valori, inclusi i subnormali:

\[
W_{signed}=E_{max}-E_{min}+p+\lceil\log_2R\rceil+1.
\]

| Input | Larghezza richiesta |
|---|---:|
| INT8 | \(8+\lceil\log_2R\rceil\) |
| FP16 | \(41+\lceil\log_2R\rceil\) |
| BF16 | \(262+\lceil\log_2R\rceil\) |
| FP32 | \(278+\lceil\log_2R\rceil\) |

Con \(R=256\), FP32 richiede \(278+8=286\) bit per lane. Il backend da 288 bit
è quindi sufficiente. Se nessuna larghezza compilata basta, PRISM usa la più
grande, satura e propaga `ACCUMULATION_INEXACT`.

Questa formula riguarda \(\sum_i x_i\). Un prodotto scalare
\(\sum_i a_i b_i\) richiede un accumulatore più largo ed è fuori ambito.

SHARP e SwitchML mostrano l'interesse per le riduzioni in-network
[^sharp-overview][^switchml]; FPISA evidenzia il costo del floating point nei
datapath programmabili[^fpisa]. PRISM usa un prototipo FPGA per misurare questo
compromesso, senza assumere che Kulisch sia sempre la scelta migliore.

[^sharp-overview]: NVIDIA, *Scalable Hierarchical Aggregation and Reduction
    Protocol (SHARP)*. https://docs.nvidia.com/networking/display/sharpv300

[^switchml]: Sapio et al., *Scaling Distributed Machine Learning with In-Network
    Aggregation*, NSDI 2021.
    https://www.usenix.org/conference/nsdi21/presentation/sapio

[^fpisa]: Yuan et al., *Unlocking the Power of Inline Floating-Point Operations
    on Programmable Switches*, NSDI 2022.
    https://www.usenix.org/system/files/nsdi22-paper-yuan.pdf
