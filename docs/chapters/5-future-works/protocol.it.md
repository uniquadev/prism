# 5.1 Protocollo

Protocol 1.0 congela identità degli oggetti, transazioni di management,
ammissione a due fasi, bitmap di fase e consegna affidabile hop-by-hop. Le
revisioni future dovranno estendere questi contratti senza indebolire la
sicurezza delle generazioni né interpretare la perdita Ethernet come successo.

## Parziali esatti in un albero

L'estensione aritmetica principale è un formato lossless per lo stato parziale
dell'accumulatore. Serializzare in FP32 un accumulatore locale esatto introduce
un arrotondamento a ogni livello e non garantisce una riduzione globale esatta e
indipendente dall'albero. Un futuro profilo `EXACT_PARTIAL_WIRE` dovrà definire
ampiezza, normalizzazione, flag per valori speciali, overflow, merge, geometria
del payload e negoziazione prima di pubblicare una tupla esatta multilivello.

## Memoria di completamento scalabile

La bitmap di fase completa rende la deduplicazione indipendente dalla finestra
degli Aggregation Slot. Si possono studiare BRAM/URAM a banchi, memoria esterna,
mappe sparse compresse, sommari gerarchici o allocazione a pagine. Ogni
ottimizzazione deve conservare tombstone esatti per chunk, contatori di
completamento efficienti e accounting atomico visibile in `OP_PREPARE`.

## Affidabilità consapevole della congestione

Il profilo obbligatorio `PM_OP_COL_PROGRESS` fornisce ACK, selective ACK,
finestra e retry. Un profilo successivo potrà aggiungere suggerimenti di rate,
integrazione ECN, timer adattivi ed equità tra operazioni concorrenti. La policy
deve restare separata dal payload del risultato e trattenere ogni replica fino
all'ACK di tutti i Result Path.

## Profili di autenticazione

La versione 1.0 negozia canali esterni autenticati o autenticazione in-protocol
senza scegliere una primitiva non implementata nell'RTL. Lavori futuri potranno
congelare tag, derivazione delle chiavi, sequenza anti-replay, rekey e
autenticazione dei dati. L'analisi dovrà coprire contributor falsificati,
generazioni stale, replay del management, takeover del lease e recovery da reset.

## Altre collettive e routing

`ALLREDUCE` e `REDUCE_SCATTER` hanno codici assegnati, ma uno switch pubblica
soltanto semantiche implementate. Profili futuri possono definire proprietà
dello scatter, tensori segmentati, placement non contiguo, variazioni di
topologia e altri operatori associativi. Restano necessari geometria invariabile,
ACK esplicito per path e ammissione atomica.

## Recovery distribuito e osservabilità

Un AM di produzione richiederà journal durevoli, takeover tra repliche del
manager, rilevamento di gap negli eventi, telemetria della replay pressure e
reinstallazione coordinata dopo una variazione del Device Boot ID. `OP_STATUS`
resta la fonte autorevole; gli eventi sono un'ottimizzazione. Uno schema futuro
potrà standardizzare contatori e trace senza esporre indirizzi privati delle
tabelle hardware.

## Relazione con sistemi precedenti

SHARP motiva la separazione concettuale tra job, gruppo collettivo riutilizzabile,
singola richiesta e risorse limitate di aggregazione. PRISM usa questa lezione
architetturale, ma non dichiara compatibilità di protocollo, wire, API,
management o trasporto con NVIDIA SHARP o NVLink SHARP.
