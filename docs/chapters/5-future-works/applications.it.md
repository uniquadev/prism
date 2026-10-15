# 5.4 Applicazioni

## Convergenza

La prossima domanda applicativa è se riduzioni più accurate permettano di
raggiungere una qualità della soluzione prefissata con meno iterazioni o in
meno tempo. I risultati riproducibili della riduzione PRISM costituiscono una
base per questo studio.

[Cacciola et al.](https://arxiv.org/html/2301.01651v2) studiano la convergenza
della SGD a bassa precisione e mostrano benefici da una maggiore precisione degli
accumulatori in esperimenti di regressione logistica. Gli interventi riguardano
i calcoli locali; l'effetto della sola riduzione tra rank richiede una verifica
specifica.

## Metodo

Inserire riduzioni convenzionali e Kulisch nell'intero ciclo applicativo:

- **AI:** aggregazione dei gradienti nel training distribuito;
- **HPC:** riduzioni dei prodotti scalari in un solver iterativo.

Mantenere uguali dati, inizializzazione, parametri dell'algoritmo, precisione
dei calcoli locali e precisione del risultato. Il risultato di ogni riduzione
deve alimentare l'iterazione successiva. Ripetere i confronti nel training
su più seed.

## Misure

| Misura | Obiettivo |
| --- | --- |
| Errore numerico | Confrontare l'accuratezza della riduzione e della soluzione finale con un riferimento comune. |
| Iterazioni per raggiungere la stessa soglia di qualità | Verificare se la riduzione modifica la convergenza. |
| Tempo per raggiungere la stessa soglia di qualità | Includere calcolo, comunicazione e costi della compressione senza perdita. |

Usare un criterio comune per valutare la qualità della soluzione nei due modi
di riduzione. Lo [studio software sulla compressione](protocol.md#compressione-degli-accumulatori)
stima il costo del trasporto; lo studio della convergenza richiede riduzioni
inserite nell'applicazione iterativa, i cui risultati influenzino i calcoli
successivi.
