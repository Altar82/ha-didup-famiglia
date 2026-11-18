# Changelog

## 0.4.1

### Correzioni
- Download degli allegati (e quindi presa visione) rifiutato da Argo con *HTTP 403*: il link firmato veniva
  ricodificato prima della richiesta e la firma non era più valida.

## 0.4.0

### Novità
- **Circolari da confermare**: nuova lista (in *Elenchi*) con le circolari che chiedono la presa visione, con data,
  autore e allegati. Spuntandone una se ne conferma la presa visione; sotto restano le ultime confermate.
- **Allegati**: nuova azione `didup_famiglia.scarica_allegati` che salva gli allegati nella cartella dei media
  (*Media → Media locali → didup_famiglia*), divisi per alunno e comunicazione. Nel README c'è l'automazione per
  scaricarli appena arriva una comunicazione.
- **Comunicazioni da leggere**: l'attributo `da_leggere` ora elenca tutte le circolari da confermare, non solo le prime 10.

## 0.3.4

### Correzioni
- Tolto un avviso nel registro sull'uso di una funzione del registro dispositivi che Home Assistant dismetterà.

## 0.3.3

### Correzioni
- Con la nuova API Argo dà all'alunno un identificativo diverso: le entità e il dispositivo esistenti vengono ora
  spostati sul nuovo identificativo, così restano gli stessi (nomi, area, storico e automazioni) invece di comparire
  doppi con quelli vecchi non disponibili. I doppioni creati dalla 0.3.2 vengono tolti da soli.

## 0.3.2

### Correzioni
- **Argo ha spento la vecchia API dell'app** (`/appfamiglia`, risponde *HTTP 503*): l'integrazione ora usa la nuova
  API Famiglia, la stessa dell'app attuale. Se un giorno la nuova non rispondesse, prova ancora quella vecchia.
  Non serve rifare l'accesso e le entità restano le stesse.

## 0.3.1

### Novità
- **Riparazioni**: quando Argo rifiuta l'accesso (password cambiata o accesso SPID/CIE scaduto) compare un avviso
  in *Impostazioni → Riparazioni* che porta direttamente al nuovo accesso; sparisce da solo appena l'accesso torna valido.

## 0.3.0

### Novità
- **Presa visione delle circolari da Home Assistant**: pulsante *Presa visione comunicazioni* (conferma tutte
  quelle in attesa) e azione `didup_famiglia.presa_visione` per confermarne una sola, anche da una notifica.
- **Ultima comunicazione**: nuovo sensore con il titolo dell'ultima comunicazione in bacheca; data, autore,
  categoria, allegati e link negli attributi.
- **Media per materia**: un sensore per ogni materia; quelle nuove compaiono da sole quando arriva il primo voto.
- **Promemoria prossimi 7 giorni**: verifiche, interrogazioni e avvisi dei docenti, più il nuovo evento
  `didup_famiglia_nuovo_promemoria`.
- **Collegamento Argo**: sensore di diagnostica che resta disponibile anche quando Argo non risponde, con l'ora
  dell'ultimo aggiornamento riuscito e l'errore.
- Le comunicazioni hanno ora l'attributo `id`, anche negli eventi.
- README: esempi di automazioni per notifiche con pulsante di presa visione, medie, verifiche di domani e Argo
  non raggiungibile.

### Correzioni
- L'integrazione non chiude più la sessione di rete condivisa di Home Assistant (avviso nel registro).
- Dopo l'aggiornamento i promemoria già presenti non generano una raffica di eventi.
