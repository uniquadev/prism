# 5.3 Formati numerici

## Collettive

Il datapath integrato attuale implementa Reduce e AllReduce SUM.
Broadcast, ReduceScatter e operatori come MIN e MAX richiedono implementazione
e verifica del comportamento specifico di ciascuna operazione.

Politiche di accumulo alternative, incluso l'arrotondamento stocastico,
richiedono semantiche numeriche distinte e supporto RTL. La valutazione dovrà
riportare garanzie e costi associati a ciascuna politica.

## Scale condivise

NVFP4 associa valori E2M1 a scale condivise per blocchi di 16 elementi e a
una scala globale, come descritto nella
[documentazione NVIDIA Transformer Engine](https://docs.nvidia.com/deeplearning/transformer-engine/features/low_precision_training/nvfp4/nvfp4.html).

**Interventi sul protocollo e sul datapath.** Definire la trasmissione delle scale,
preservare i confini dei blocchi durante la ripacketizzazione e accumulare
i valori decodificati. La somma esatta dei valori decodificati conserva l'errore
introdotto dalla quantizzazione iniziale.

**Valutazione.** Confrontare errore numerico e throughput con i formati
attualmente supportati, includendo il costo della gestione delle scale e
dell'allineamento dei blocchi.
