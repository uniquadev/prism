# 5.1 Protocollo

Il Protocollo 1.0 fissa identità degli oggetti, transazioni di gestione,
ammissione a due fasi, bitmap di avanzamento e consegna affidabile su ciascun
collegamento diretto. Le revisioni future dovranno estendere questi contratti
senza indebolire la sicurezza delle generazioni né interpretare una perdita
Ethernet come successo.

## Formati partial exact e Kulisch

Il Protocollo 1.0 assegna soltanto parziali FP32. Un futuro formato exact-FP32 o
Kulisch dovrà definire layout in byte, regole di fusione, valori speciali,
overflow e geometria del payload prima di ricevere un valore numerico Partial
Wire Format. Il supporto verrà dichiarato nella tupla aritmetica a quattro
campi, non tramite un bit di feature separato.

## Memoria di completamento scalabile

La bitmap completa rende la deduplicazione indipendente dalla finestra degli
Aggregation Slot attivi. Si possono studiare BRAM/URAM a banchi, memoria esterna,
mappe sparse compresse, riepiloghi gerarchici o allocazione a pagine. Ogni
ottimizzazione deve conservare marcatori esatti per chunk, contatori di
completamento efficienti e conteggio atomico delle risorse visibile durante
`OP_PREPARE`.

## Affidabilità consapevole della congestione

Il profilo obbligatorio `PM_OP_COL_PROGRESS` fornisce ACK, ACK selettivi,
finestra di ricezione e informazioni di ritrasmissione. Un profilo successivo
potrà aggiungere indicazioni esplicite sulla frequenza di invio, integrazione
ECN, timer adattivi ed equità tra operazioni concorrenti. Questa politica resta
separata dal payload del risultato e conserva ogni replica fino all'ACK di tutti
i Result Path.

Il Protocollo 1.0 affida al runtime/endpoint la deduplicazione del risultato
finale fino al rilascio. Un futuro profilo di finestra lato risultato potrà
standardizzare marcatori e ACK degli endpoint prima di dichiarare una consegna
applicativa exactly-once.

## Profili di autenticazione

La versione 1.0 negozia canali esterni autenticati o autenticazione interna al
protocollo senza scegliere una primitiva non implementata nell'RTL. I lavori
futuri potranno definire tag, derivazione delle chiavi, sequenza anti-ripetizione,
rinnovo delle chiavi e autenticazione dei dati. L'analisi dovrà coprire identità
dei contributori falsificate, generazioni obsolete, ripetizione dei messaggi di
gestione, subentro nella sessione e ripristino dopo un reset.

## Altre collettive e instradamento

`REDUCE_SCATTER` possiede un codice semantico assegnato, ma uno switch pubblica
soltanto le semantiche implementate. Profili futuri potranno definire proprietà
della distribuzione, tensori segmentati, posizionamento non contiguo del
risultato, variazioni di topologia e altri operatori associativi. Restano
necessari geometria invariabile, ACK esplicito per percorso e ammissione atomica.

## Ripristino distribuito e osservabilità

Un AM di produzione richiederà registri durevoli delle operazioni, subentro tra
repliche dell'AM, rilevamento di lacune negli eventi, telemetria sulla pressione
delle memorie di ritrasmissione e reinstallazione coordinata dopo una variazione
del Device Boot ID. `OP_STATUS` resta la fonte autorevole; gli eventi sono
un'ottimizzazione. Uno schema diagnostico futuro potrà standardizzare contatori
e tracce senza esporre indirizzi privati delle tabelle hardware.

Se Host Coordinator e AM sono servizi separati, anche il loro RPC richiede
identità stabili delle richieste, regole di riconnessione e ripetizione degli
esiti ACTIVE, COMPLETE, RELEASED e degli errori terminali. Il ripristino non deve
mai creare uno start grant finché l'AM non ha ristabilito ogni destinatario come
`ACTIVE` e deve risvegliare tutti i rank in attesa con un esito coerente.

## Relazione con sistemi precedenti

SHARP motiva la separazione tra integrazione host delle collettive e Aggregation
Manager, oltre alla distinzione tra gruppo riutilizzabile, singola richiesta e
risorse limitate di aggregazione. PRISM usa queste idee soltanto come lezioni
architetturali e non dichiara compatibilità di protocollo, wire, API, gestione o
trasporto con NVIDIA SHARP o NVLink SHARP.
