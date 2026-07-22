# 5. Sviluppi futuri

L'implementazione corrente si ferma intenzionalmente a un nodo `SINGLE` con due porte. Le
estensioni direttamente motivate dalle lacune osservabili sono:

- implementare e verificare il datapath multi-switch LEAF/INTERNAL/ROOT e le
  partial DATA generate dagli switch;
- definire un partial format lossless prima di dichiarare esattezza Kulisch
  sull'intero albero;
- implementare PROGRESS, ACK, replay, retry e recovery bounded in RTL, se
  l'affidabilità hop-by-hop è richiesta;
- aggiungere test unitari mirati per tabelle CONTROL, result store/router,
  packetizer e reset dei wrapper;
- completare sintesi, place-and-route e timing sul profilo OpenNIC scelto,
  riportando risorse, cammini critici, latenza e throughput payload sostenuto;
- aggiungere operatori o collective soltanto dopo averne definito semantica
  numerica, stato e compatibilità wire.

Forwarding Layer-2, VOQ, crossbar generale e packet memory condivisa non sono
requisiti incompleti dell'implementazione corrente: richiederebbero una decisione di scope separata.
