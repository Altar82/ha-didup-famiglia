# Changelog

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
