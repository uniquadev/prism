# 5.1 Hardware

## Test sulla scheda

**Evidenze attuali.** La simulazione RTL verifica funzionalità e risultati
numerici e misura throughput e latenze nelle configurazioni SINGLE studiate. La
[build a una porta per la U280](../2-getting-started/u280.md) rispetta i vincoli
di timing a 250 MHz, le sue [risorse](../4-results/resources.md) sono misurate
dopo il routing, e una simulazione dell'intero top della scheda esegue riduzioni
dal driver della libreria.

**Implementazione.** Portare su il link a 100G verso uno switch o una NIC ed
eseguire sulla scheda le riduzioni di `prism-single`.

**Valutazione.** Misurare throughput, tempo di risposta e potenza sulla scheda e
confrontarli con la simulazione RTL.

## Multi-switch

**Evidenze attuali.** Il datapath integrato implementa lo scenario `SINGLE` con rank
direttamente collegati. Generazione e merge delle somme intermedie esatte e
trasmettitore `AUTO` tile-wide sono verificati in test RTL separati.

**Implementazione.** Integrare questi blocchi negli scenari multi-switch e aggiungere:

- inoltro e instradamento delle somme intermedie e dei risultati;
- affidabilità tra nodi adiacenti;
- svuotamento sicuro del traffico in volo durante la cancellazione;
- code di uscita virtuali e crossbar per un fabric di inoltro generale.

**Valutazione.** Verificare l'intera collettiva tra switch, incluse backpressure,
completamento e cancellazione. Misurare traffico delle somme intermedie e
prestazioni end-to-end per diverse configurazioni dell'albero.

La [documentazione dell'architettura](../3-architecture/2.pipeline.md) distingue
il percorso implementato dalle risorse di inoltro ancora da aggiungere.
