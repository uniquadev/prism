# 3.3 Interfacce

Protocol 1.0 include una libreria host Python indipendente dal trasporto in
`repo/traffic-gen/src/prism_protocol`. Serializzazione, validazione e lifecycle
lato AM sono definiti senza imporre raw socket, PCIe, AXI-Lite o un particolare
canale di controllo.

## Interfaccia pubblica AM

| Funzione | Risultato |
|---|---|
| `prism_query_capabilities(...)` | Limiti statici, feature, tuple aritmetiche e Device Boot ID |
| `prism_open_session(...)` | Sessione Job con lease e cookie opaco per switch |
| `prism_query_resources(...)` | Snapshot consultivo delle risorse dinamiche |
| `prism_renew_session(...)` / `prism_close_session(...)` | Rinnovo o teardown confermato |
| `prism_create_group(...)` | Staging e commit tree-wide del gruppo riutilizzabile |
| `prism_group_status(...)` / `prism_destroy_group(...)` | Stato autorevole o distruzione confermata |
| `prism_prepare_operation(...)` | Ammissione atomica tree-wide con rollback parziale |
| `prism_commit_operation(...)` / `prism_abort_operation(...)` | Transizione idempotente |
| `prism_operation_status(...)` / `prism_wait_operation(...)` | Polling e recovery del completamento |
| `prism_release_operation(...)` | Rilascio confermato e abilitazione della generazione successiva |

`PrismManager` confronta geometria e formati sugli edge, valida i descrittori
contro le capability locali, controlla i Boot ID, persiste le generazioni quando
`GenerationStore` riceve un path e vieta il riuso di ID ancora posseduti. Gli
errori `PrismError` includono stato, messaggio, switch e transazione;
`InvalidHandleError` rappresenta handle locali non validi.

## Confine di trasporto

`ControlTransport.exchange(frames, timeout_seconds)` è l'unico hook richiesto.
Riceve frammenti già serializzati e restituisce i frammenti di risposta.
`WireSwitchClient` gestisce Transaction ID, frammentazione, riassemblaggio,
validazione dello schema e retry identici limitati. Il trasporto conserva
l'identità dello switch target e non interpreta i TLV.

Il confine permette futuri adapter raw Ethernet, sideband, PCIe o simulazione
senza duplicare il protocollo. Il repository corrente non ne dichiara uno.

## Stream verso l'RTL

Per un frame Ethernet senza tag su AXI4-Stream a 512 bit, il primo beat contiene
14 byte Ethernet, 2 byte di control word, l'intero header dati/risultato da 24
byte e 24 byte di payload. `TKEEP` descrive i byte fisici e `TLAST` chiude il
frame; nessuno dei due modifica la lunghezza logica derivata dall'operazione. La
backpressure deve conservare frame e associazione al peer fino all'accettazione
completa.

Gli header management e progress misurano rispettivamente 24 e 40 byte dopo il
control word. Il parser deve propagare Job, gruppo e generazioni dell'operazione
a lookup, replay e risposta.

