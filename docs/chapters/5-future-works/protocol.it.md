# 5.1 Protocollo

I punti seguenti sono intenzionalmente fuori dall'ambito della prima versione
del protocollo MiniSharp sviluppata per la tesi.

## Completamento affidabile e interruzione

MiniSharp v0.1 non definisce `COL_ABORT`, acknowledgement positivi o negativi,
ritrasmissione oppure pacchetti di recovery attivati da timeout. Pacchetti non
validi, contributi duplicati, route mancanti, opcode non supportati e altre
condizioni di errore vengono segnalati mediante contatori visibili in debug o
tramite registri.

Un protocollo di produzione potrebbe aggiungere:

- acknowledgement o risposte di stato per il setup;
- messaggi espliciti di interruzione della collettiva;
- una politica di timeout e cleanup controllato dall'AM;
- semantiche di retry o replay per fabric non lossless;
- notifiche di completamento per contesto.

## Reduce-scatter

La tabella di result route opera già su intervalli di chunk, quindi
`REDUCE_SCATTER` può essere aggiunta senza sostituire il modello di diffusione
dei risultati. L'AM installerebbe result route differenti per intervalli di
chunk diversi, inviando ciascun intervallo soltanto al ramo che lo possiede.

La prima versione del protocollo della tesi mantiene `REDUCE_SCATTER` fuori
dall'ambito per concentrarsi su `REDUCE` e `ALLREDUCE`.

## Lunghezza dinamica del vettore

Il protocollo di base ricava la lunghezza del vettore dal contesto della
collettiva installato. Una revisione futura potrebbe trasportare la dimensione
del vettore o il numero di elementi nel primo pacchetto dati di un'operazione,
ma richiederebbe regole aggiuntive per i chunk fuori ordine, l'attivazione del
contesto e il ciclo di vita dell'istanza dell'operazione.

## Trasporto del control plane

L'interfaccia logica dell'Aggregation Manager è indipendente dal trasporto. Le
implementazioni future potranno mappare gli stessi record di setup su:

- AXI-Lite;
- registri PCIe BAR;
- chiamate firmware;
- un'API software per il control plane;
- una rete di management sicura.

## Sicurezza e controllo degli accessi

Il setup in-band è utile per la simulazione e il bring-up della FPGA, ma non è
un control plane sicuro per la produzione. Un deployment di produzione
richiederebbe autenticazione, autorizzazione, filtraggio e protezione dai replay
dei record di setup.

## Profili della dimensione dei pacchetti

Il protocollo attuale assume payload Ethernet standard non jumbo. I profili per
jumbo frame e la negoziazione della MTU sono sviluppi futuri.

## Scoperta della topologia

Il primo prototipo assume che l'AM riceva le informazioni sulla topologia e sul
posizionamento dei rank. Un futuro topology explorer potrebbe scoprire identità
degli switch, porte locali, rank raggiungibili e relazioni padre/figlio prima di
installare i contesti delle collettive.
