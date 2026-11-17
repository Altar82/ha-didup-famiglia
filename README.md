# DidUP Famiglia per Home Assistant

[![Marketplace](https://img.shields.io/badge/Marketplace-default-41BDF5.svg)](https://github.com/hacs/default) [![Download](https://img.shields.io/github/downloads/Altar82/ha-didup-famiglia/total?label=download)](https://github.com/Altar82/ha-didup-famiglia/releases) [![Installazioni attive](https://img.shields.io/badge/dynamic/json?label=installazioni%20attive&query=%24.didup_famiglia.total&url=https%3A%2F%2Fanalytics.home-assistant.io%2Fcustom_integrations.json&color=41BDF5)](https://analytics.home-assistant.io/custom_integrations)

Integrazione **non ufficiale** per [Home Assistant](https://www.home-assistant.io/) che porta in casa i dati del
registro elettronico **Argo didUP Famiglia**: compiti, voti e medie, assenze e ritardi, note disciplinari e comunicazioni
della bacheca. Funziona con più figli sullo stesso account.

> [!WARNING]
> Questo progetto **non è affiliato, approvato o supportato da Argo Software S.r.l.** Usa le stesse API dell'app
> ufficiale, che non sono documentate e possono cambiare in qualsiasi momento (l'ultima modifica al login è di fine
> ottobre 2026). Secondo Argo quei servizi sono riservati alla sua app: usa l'integrazione solo con il tuo account e a
> tuo rischio. I marchi *Argo*, *didUP* e *Argo Famiglia* appartengono ai rispettivi proprietari.

## Funzionalità

- **Due modi di accesso**: codice scuola + utente + password Argo, oppure **SPID / CIE**
- **Calendario** dei compiti per data di consegna, con i promemoria della scuola
- **Sensori** per voti, medie (anche per materia), compiti, promemoria, assenze, note e comunicazioni
- **Presa visione** delle circolari da Home Assistant: spuntandole da una lista, con un pulsante o da una notifica
- **Allegati** della bacheca salvati nei media di Home Assistant
- **Eventi** per le automazioni quando arriva un voto, una nota, un'assenza, una comunicazione, un compito o un promemoria
- Un **dispositivo per ogni figlio**, con nome, classe e scuola
- **Diagnostica** scaricabile con i dati personali oscurati

## Installazione

### Dal Marketplace (consigliata)

1. In Home Assistant apri **Marketplace** e cerca **DidUP Famiglia**.
2. Installala e riavvia Home Assistant.

### Come repository personalizzato

Se non la trovi nella ricerca, nel Marketplace apri il menu ⋮ → **Repository personalizzati**, incolla `https://github.com/Altar82/ha-didup-famiglia`, scegli la categoria **Integrazione** e poi installala come sopra.

### Manuale

Copia la cartella `custom_components/didup_famiglia` dentro `/config/custom_components/` e riavvia Home Assistant.

## Configurazione

**Impostazioni → Dispositivi e servizi → Aggiungi integrazione → DidUP Famiglia (Argo)**.
La prima schermata chiede come accedi al registro.

### Codice scuola, utente e password

Inserisci le credenziali Argo del genitore. L'integrazione rifà il login da sola quando serve.
Se la password cambia, Home Assistant ti chiede quella nuova.

### SPID o CIE

Molte scuole dal 2026 accettano solo SPID/CIE. Il login con identità digitale va fatto in un browser, ma **una volta
sola**: dopo Home Assistant rinnova l'accesso da solo.

1. Usa un **computer** con Chrome o Edge. Non farlo dal telefono se hai l'app didUP installata, perché l'app intercetta
   il codice al posto di Home Assistant.
2. Premi **F12** e apri la scheda **Console**, poi lasciala aperta.
3. Apri il link **Accedi ad Argo** che compare nella schermata di configurazione.
4. Inserisci il codice scuola, premi **SPID - CIE - EIDAS** e completa l'accesso come al solito.
5. Alla fine la pagina sembra non fare nulla. Nella Console compare un errore simile a
   `Failed to launch 'it.argosoft.didup.famiglia.new://login-callback?code=...'`.
6. Copia l'indirizzo tra apici, da `it.argosoft` fino alla fine, e incollalo in Home Assistant **entro un paio di
   minuti**: il codice scade presto e vale una volta sola.

Se Home Assistant resta spento a lungo o Argo revoca l'accesso, compare una notifica di **nuova autenticazione** e
basta ripetere questi passi.

### Opzioni

Dal pulsante **Configura** dell'integrazione:

- **Intervallo di aggiornamento**: 30 minuti di default, minimo 10.
- **Versione app didUP Famiglia**: Argo rifiuta le versioni vecchie dell'app (errore HTTP 410). Se nel log compare
  *"Argo rifiuta la versione app"*, inserisci la versione attuale di didUP Famiglia sul Play Store.

## Entità

Per ogni figlio viene creato un dispositivo con queste entità:

| Entità | Stato | Attributi principali |
|---|---|---|
| Calendario **Compiti** | acceso se c'è un evento oggi | compiti per data di consegna e promemoria |
| **Media generale** | media calcolata da Argo | `medie_materie` |
| **Media *materia*** | una per materia, es. *Media Matematica* (si aggiungono da sole) | `numero_voti`, `ultimi_voti` |
| **Ultimo voto** | es. `7½` | materia, data, tipo, docente, `ultimi_voti`, `annotazioni` |
| **Numero voti** | voti con valore numerico | |
| **Compiti per domani** | numero | `compiti` |
| **Compiti prossimi 7 giorni** | numero | `compiti` |
| **Promemoria prossimi 7 giorni** | verifiche, interrogazioni e avvisi segnati dai docenti | `promemoria` |
| **Assenze** | numero di assenze | `ritardi`, `uscite_anticipate`, `ultimi_eventi` |
| **Da giustificare** | numero | `eventi` |
| **Note disciplinari** | numero | `ultime_note` |
| **Ultima comunicazione** | titolo dell'ultima comunicazione pubblicata in bacheca | `id`, `data`, `categoria`, `autore`, `presa_visione_richiesta`, `presa_visione`, `allegati`, `url` |
| **Comunicazioni da leggere** | circolari con presa visione mancante | `da_leggere` (tutte), `ultime_comunicazioni` |
| Lista **Circolari da confermare** | le circolari da confermare: spuntane una per prendere visione; sotto le ultime confermate | |
| Pulsante **Presa visione comunicazioni** | conferma tutte le circolari che chiedono la presa visione | |
| **Collegamento Argo** (diagnostica) | acceso se l'ultimo aggiornamento è riuscito, resta disponibile anche quando Argo è giù | `ultimo_aggiornamento_riuscito`, `errore` |

Le annotazioni senza valore che Argo registra tra i voti (*Impreparato*, *Comunicazione*…) non contano come voti:
sono nell'attributo `annotazioni` del sensore *Ultimo voto*.

## Presa visione

La lista **Circolari da confermare** (la trovi in **Elenchi** nella barra laterale, o aggiungendo una scheda
*Elenco cose da fare* alla dashboard) mostra le circolari che chiedono la presa visione, con data, autore e allegati:
spunta quelle che vuoi confermare. Una presa visione su Argo non si può annullare, quindi togliere la spunta non fa nulla.

Il pulsante **Presa visione comunicazioni** conferma in un colpo tutte le circolari che la richiedono.
Per confermarne una sola c'è l'azione `didup_famiglia.presa_visione`, con l'`id` della comunicazione
(lo trovi nell'evento `didup_famiglia_nuova_comunicazione` e negli attributi dei sensori della bacheca):

```yaml
action: didup_famiglia.presa_visione
data:
  comunicazione: "123456"   # senza id conferma tutte quelle in attesa
```

Come nell'app, Argo registra la presa visione dopo che è stato aperto un allegato: l'integrazione lo scarica
da sola (senza salvarlo) prima di confermare. La conferma vale come quella fatta dall'app del genitore.

## Allegati

L'azione `didup_famiglia.scarica_allegati` salva gli allegati nella cartella dei media di Home Assistant: li apri
e li scarichi da **Media → Media locali → didup_famiglia**, divisi per alunno e per comunicazione. I file già
scaricati vengono saltati e scaricare un allegato non conferma la presa visione.

```yaml
action: didup_famiglia.scarica_allegati
data:
  comunicazione: "123456"     # facoltativo: senza id, tutte le comunicazioni in bacheca
  solo_da_confermare: false   # senza id, solo quelle ancora da confermare
```

## Eventi per le automazioni

| Evento | Quando |
|---|---|
| `didup_famiglia_nuovo_voto` | un voto o un'annotazione nuova |
| `didup_famiglia_nuova_nota` | una nota disciplinare |
| `didup_famiglia_nuova_assenza` | un'assenza, un ritardo o un'uscita |
| `didup_famiglia_nuova_comunicazione` | una comunicazione in bacheca |
| `didup_famiglia_nuovo_compito` | un compito assegnato |
| `didup_famiglia_nuovo_promemoria` | un promemoria dei docenti (verifiche, interrogazioni…) |

Ogni evento contiene `alunno` più i campi dell'elemento (`materia`, `voto`, `valore`, `data`, `titolo`, `compito`…).
Al primo avvio non viene emesso nulla: gli elementi già presenti sono considerati visti.

### Esempi

```yaml
automation:
  - alias: "Notifica nuovo voto"
    triggers:
      - trigger: event
        event_type: didup_famiglia_nuovo_voto
    conditions:
      # solo voti numerici, non Impreparato/Comunicazione
      - condition: template
        value_template: "{{ trigger.event.data.valore is not none }}"
    actions:
      - action: notify.mobile_app_telefono
        data:
          title: "Nuovo voto per {{ trigger.event.data.alunno }}"
          message: "{{ trigger.event.data.materia }}: {{ trigger.event.data.voto }}"

  - alias: "Compiti per domani alle 18"
    triggers:
      - trigger: time
        at: "18:00:00"
    conditions:
      - condition: numeric_state
        entity_id: sensor.mario_rossi_compiti_per_domani
        above: 0
    actions:
      - action: notify.mobile_app_telefono
        data:
          title: "Compiti per domani"
          message: >
            {% for c in state_attr('sensor.mario_rossi_compiti_per_domani', 'compiti') %}
            • {{ c.materia }}: {{ c.compito }}
            {% endfor %}

```

Sostituisci `notify.mobile_app_telefono` con il tuo servizio di notifica e `mario_rossi` con il nome
dei tuoi sensori.

#### Nuova comunicazione, con il pulsante "Presa visione" nella notifica

```yaml
automation:
  - alias: "Nuova comunicazione in bacheca"
    triggers:
      - trigger: event
        event_type: didup_famiglia_nuova_comunicazione
    actions:
      - action: notify.mobile_app_telefono
        data:
          title: "Bacheca: {{ trigger.event.data.alunno }}"
          message: >
            {{ trigger.event.data.titolo }}
            {% if trigger.event.data.autore %}({{ trigger.event.data.autore }}){% endif %}
            {% if trigger.event.data.allegati %}
            Allegati: {{ trigger.event.data.allegati | join(', ') }}{% endif %}
          data:
            url: "{{ trigger.event.data.url or '' }}"
            actions: >
              {% if trigger.event.data.presa_visione_richiesta %}
              [{"action": "DIDUP_PV_{{ trigger.event.data.id }}", "title": "Presa visione"}]
              {% else %}[]{% endif %}

  - alias: "Presa visione dalla notifica"
    triggers:
      - trigger: event
        event_type: mobile_app_notification_action
    conditions:
      - condition: template
        value_template: "{{ trigger.event.data.action.startswith('DIDUP_PV_') }}"
    actions:
      - action: didup_famiglia.presa_visione
        data:
          comunicazione: "{{ trigger.event.data.action.removeprefix('DIDUP_PV_') }}"
```

#### Allegati salvati appena arriva una comunicazione

```yaml
automation:
  - alias: "Scarica gli allegati della bacheca"
    triggers:
      - trigger: event
        event_type: didup_famiglia_nuova_comunicazione
    conditions:
      - condition: template
        value_template: "{{ trigger.event.data.allegati | count > 0 }}"
    actions:
      - action: didup_famiglia.scarica_allegati
        data:
          comunicazione: "{{ trigger.event.data.id }}"
```

#### Promemoria della circolare non confermata la sera

```yaml
automation:
  - alias: "Circolari da confermare"
    triggers:
      - trigger: time
        at: "20:30:00"
    conditions:
      - condition: numeric_state
        entity_id: sensor.mario_rossi_comunicazioni_da_leggere
        above: 0
    actions:
      - action: notify.mobile_app_telefono
        data:
          title: "Circolari da confermare"
          message: >
            {% for n in state_attr('sensor.mario_rossi_comunicazioni_da_leggere', 'da_leggere') %}
            • {{ n.titolo }}
            {% endfor %}
          data:
            actions:
              - action: DIDUP_PV_TUTTE
                title: "Presa visione di tutte"

  - alias: "Presa visione di tutte dalla notifica"
    triggers:
      - trigger: event
        event_type: mobile_app_notification_action
        event_data:
          action: DIDUP_PV_TUTTE
    actions:
      - action: button.press
        target:
          entity_id: button.mario_rossi_presa_visione_comunicazioni
```

#### Media di una materia sotto il 6

```yaml
automation:
  - alias: "Media matematica sotto la sufficienza"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.mario_rossi_media_matematica
        below: 6
    actions:
      - action: notify.mobile_app_telefono
        data:
          title: "Attenzione alla media"
          message: >
            Media di matematica scesa a {{ states('sensor.mario_rossi_media_matematica') }}
            (ultimo voto: {{ state_attr('sensor.mario_rossi_media_matematica', 'ultimi_voti')[0].voto }})
```

#### Verifiche e interrogazioni di domani

```yaml
automation:
  - alias: "Verifiche di domani"
    triggers:
      - trigger: time
        at: "19:00:00"
    variables:
      domani: "{{ (now() + timedelta(days=1)).date() | string }}"
      lista: >
        {{ state_attr('sensor.mario_rossi_promemoria_prossimi_7_giorni', 'promemoria')
           | selectattr('data', 'eq', domani) | list }}
    conditions:
      - condition: template
        value_template: "{{ lista | count > 0 }}"
    actions:
      - action: notify.mobile_app_telefono
        data:
          title: "Domani a scuola"
          message: >
            {% for p in lista %}• {{ p.promemoria }}{% if p.docente %} ({{ p.docente }}){% endif %}
            {% endfor %}

  - alias: "Nuovo promemoria dei docenti"
    triggers:
      - trigger: event
        event_type: didup_famiglia_nuovo_promemoria
    actions:
      - action: notify.mobile_app_telefono
        data:
          title: "Promemoria per {{ trigger.event.data.alunno }}"
          message: "{{ trigger.event.data.data }}: {{ trigger.event.data.promemoria }}"
```

#### Argo non raggiungibile o accesso da rifare

Se la password cambia o l'accesso SPID/CIE scade, compare un avviso in **Impostazioni → Riparazioni**:
aprilo e segui il nuovo accesso. L'avviso sparisce da solo appena Argo accetta di nuovo l'accesso. Questa automazione avvisa se Argo non risponde da 3 ore:

```yaml
automation:
  - alias: "didUP non si aggiorna"
    triggers:
      - trigger: state
        entity_id: binary_sensor.mario_rossi_collegamento_argo
        to: "off"
        for: "03:00:00"
    actions:
      - action: notify.mobile_app_telefono
        data:
          title: "didUP non si aggiorna"
          message: >
            Ultimo aggiornamento riuscito:
            {{ as_timestamp(state_attr(trigger.entity_id, 'ultimo_aggiornamento_riuscito'), 0) | timestamp_custom('%d/%m %H:%M') }}.
            Errore: {{ state_attr(trigger.entity_id, 'errore') }}
```

## Problemi

- **"Impossibile completare il login"**: probabilmente Argo ha cambiato il flusso di accesso. Apri una issue allegando
  il log con il debug attivo (vedi sotto).
- **Sensori vuoti o valori strani**: scarica la **diagnostica** dalla pagina dell'integrazione e allegala a una issue.
  Password, token, nomi, codici fiscali ed email sono oscurati, ma controllala comunque prima di pubblicarla.
- **Log dettagliato**: dalla pagina dell'integrazione → **Abilita la registrazione di debug**, oppure:

  ```yaml
  logger:
    logs:
      custom_components.didup_famiglia: debug
  ```

### Provare il login fuori da Home Assistant

```bash
pip install aiohttp
python3 tools/prova_login.py SC12345 nomeutente -v
```

Stampa il flusso di login e salva la dashboard grezza in `dashboard_*.json` (contiene dati personali: non pubblicarla).

## Sviluppo

- `api.py`: client OAuth2/PKCE (login automatico con credenziali, oppure login nel browser con SPID/CIE e refresh token
  ruotato) e chiamate REST `login`, `profilo`, `dashboard/dashboard`. Non dipende da Home Assistant.
- `parse.py`: legge voti, compiti, promemoria, appello, note e bacheca in modo tollerante ai campi mancanti.
- `coordinator.py`: aggiornamento periodico ed eventi per gli elementi nuovi.
- `config_flow.py`: scelta del metodo di accesso, nuova autenticazione, opzioni.

I test simulano il portale Argo (login con pagina di consenso, SPID, rinnovo del token, parsing):

```bash
pip install pytest
pytest tests
```

## Ringraziamenti

Il flusso di accesso è stato ricostruito grazie al lavoro di chi ha studiato l'app prima:
[portaleargo-api](https://github.com/DTrombett/portaleargo-api),
[portaleargo-mcp](https://github.com/DanielVd/portaleargo-mcp),
[didupAPI-wrapper](https://github.com/Rocciadura/didupAPI-wrapper) e
[argofamiglia](https://github.com/salvatore-abello/argofamiglia).

## Licenza

[MIT](LICENSE)
