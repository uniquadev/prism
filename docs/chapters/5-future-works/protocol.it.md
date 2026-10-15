# 5.2 Protocollo

## Compressione degli accumulatori

**Evidenze attuali.** La tesi valuta la compressione adattiva in software:
i NumberGroup nativi mantengono la rappresentazione attuale, mentre ciascun
gruppo Kulisch può scegliere fra `RAW`, `RANGE`, `INDEX` e `MASK`.

**Interventi sul protocollo.** Il formato numerico e la codifica di trasporto
rimangono separati:

```text
NumberGroup.format   = KULISCH
NumberGroup.encoding = RAW | RANGE | INDEX | MASK
NumberGroup.count    = numero di valori
```

Occorre definire gli identificativi delle codifiche, le combinazioni supportate,
la negoziazione delle capacità e la rappresentazione degli stati speciali.
Il descrittore sul filo e il parser RTL vanno aggiornati insieme; lo schema
proposto sopra non descrive un supporto già presente nell'RTL.

**Interventi hardware.** Validare e decodificare i gruppi compressi in ingresso,
poi scegliere le codifiche e generare i frame RESULT compressi. La valutazione
deve misurare i costi di parser, buffering e packetizer e il risparmio netto di
banda, includendo descrittori e padding. In una rete multi-switch vanno misurati
anche i byte delle somme intermedie.

Lo studio software si trova nella cartella
`experiments/04-experiment-exact-accumulator-compression` del repository.

## RoCE

L'integrazione con RoCE avvicinerebbe PRISM alle pratiche di trasporto dei
datacenter. Richiede una mappatura sul trasporto e un'integrazione host
compatibile, conservando l'identità dell'operazione e la politica numerica.
Il protocollo attuale usa frame Ethernet nativi; RoCE resta un'estensione da
sviluppare.

Instradamento multi-switch e affidabilità tra nodi adiacenti sono trattati
nell'[integrazione hardware](hardware.md#multi-switch).
