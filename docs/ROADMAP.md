# Roadmap e gap map — voice-orchestrator vs ElevenLabs Agents

Documento di lavoro: tiene traccia di dove siamo, dove vogliamo arrivare e perché.
Si aggiorna a ogni feature, nello stesso commit del codice.

Ultimo aggiornamento: 2026-10-05 (piano blocco 6)

---

## 1. Obiettivo

Il benchmark è la **ElevenLabs Agents Platform** (ex Conversational AI): circa 200 endpoint
pubblici in una ventina di aree (fonte: la loro API reference pubblica,
`elevenlabs.io/docs/api-reference`).

**Non** vogliamo copiare tutta la superficie. Circa metà è infrastruttura enterprise (branch e
merge proposal sugli agenti, triage ticket, WhatsApp/Exotel, bursting con fatturazione doppia)
che da soli non si pareggia e che non dimostra niente in un portfolio.

Il traguardo è che **il loro ciclo base sembri completo anche qui**:

1. configuro un agente (e una famiglia di agenti) con la stessa profondità,
2. lo testo (testo e voce),
3. vedo le conversazioni, turno per turno,
4. ne misuro la qualità (criteri di successo, dati estratti).

E lo facciamo tenendo il nostro elemento distintivo: il **router a 3 livelli**
(gate deterministico → pattern → LLM di fallback) su una famiglia di agenti, contro il loro
workflow a grafo con condizioni sugli archi.

---

## 2. Gap map

Legenda: ✅ fatto · 🟡 parziale · ❌ manca · ⏸️ escluso di proposito

| Area | ElevenLabs | voice-orchestrator | Stato |
|---|---|---|---|
| **Config agente** | `conversation_config`: ASR, turn-taking, TTS (voce, velocità, stabilità), `agent.first_message`, lingua, `prompt.llm` / `temperature` per agente | `first_message`, LLM (provider/modello/temperature) e voce (voice_id/stabilità/velocità) per agente, con fallback alla famiglia. Voce collegata davvero al TTS e verificata su una chiamata LiveKit reale (D12) | ✅ (niente ASR/turn-taking/lingua configurabili per agente) |
| **Famiglie / flusso** | `workflow`: nodi `override_agent`, `standalone_agent`, `phone_number`, `tool` + archi con `forward_condition` | albero di agenti + router a 3 livelli + handoff + **vista a grafo** (nodi/archi annotati col livello di router, drag-and-drop, duplica, ricerca) oltre all'editor ad albero testuale | 🟡 diverso, non indietro |
| **Tool built-in** | `end_call`, `transfer_to_number`, `transfer_to_agent`, `language_detection`, `voicemail_detection`, `skip_turn` | `transfer_to_human`, `end_call` | 🟡 |
| **Tool custom** | webhook HTTP con parametri in JSON schema, client tool, secrets | tool Python fissi + server MCP gestibili da UI + **tool webhook HTTP gestibili da UI** (URL/metodo/header/parametri, secrets via variabile d'ambiente, log esecuzioni) | ✅ (manca ancora il "client tool" lato browser) |
| **MCP** | CRUD server, lista tool, approval policy | CRUD server da UI, attivi senza riavvio | ✅ (senza approval policy) |
| **Knowledge base** | upload file/URL/testo, crawl, indice RAG, cartelle | tab dedicata: documenti da testo, file `.md`/`.txt` o pagina web; vista dei chunk; anteprima di cosa recupera una domanda (per documento o "come lo vede un agente"); picker nel form agente. BM25, file in `data/knowledge/` | ✅ (niente crawl, cartelle, PDF/DOCX, ricerca semantica — vedi D17) |
| **Test testuale** | "simulate conversation" | box "try it" (un turno), sul provider configurato o su FakeProvider, con il provider che ha risposto mostrato accanto alla risposta | 🟡 (un turno solo, niente conversazione simulata) |
| **Test vocale** | widget / link condivisibile | tab "Test live (voce)" via LiveKit, più due script di verifica end-to-end (`scripts/d12_*`) | ✅ |
| **Conversazioni** | lista, dettaglio con trascrizione + audio, feedback, ricerca, tag | lista + dettaglio con trascrizione e routing/tool per turno; niente audio, ricerca, tag | 🟡 |
| **Valutazione post-call** | `evaluation.criteria` + `data_collection` giudicati da LLM | criteri + data collection da UI, analisi LLM on-demand, criteri strutturali (agente finale, tool usato/non usato) affidabili anche senza chiavi, success rate | ✅ (manca l'analisi automatica a fine chiamata) |
| **Analytics** | dashboard, topic, sentiment | dashboard: chiamate/giorno, livello di routing, uso tool | 🟡 |
| **Test automatici** | test case per agente, eseguibili da UI | comando `eval` da CLI, solo routing | 🟡 |
| **Privacy / limiti** | retention, redazione PII, limiti di concorrenza | tetto giornaliero di minuti voce (`usage_guard.py`) | 🟡 |
| **Versioning** | branch, draft, deployment, merge proposal | nessuno | ⏸️ |
| **Telefonia** | numeri, SIP trunk, Twilio, batch calling outbound | nessuna | ⏸️ per ora |
| **Widget embeddabile** | widget configurabile (colori, testi, avatar) | nessuno | ⏸️ per ora |
| **Multi-tenant / auth / secrets** | workspace, secrets, auth sugli agenti | nessuno, solo uso locale | ⏸️ |

---

## 3. Blocchi di lavoro

### Blocco 1 — Conversazioni + valutazione  ✅ prima versione consegnata

Perché per primo: è il pezzo che differenzia di più (QA da call center, legato all'esperienza
CAI e alla tesi sulle sales force) e senza trascrizioni salvate nessuna analisi è possibile.

- [x] Trascrizione per turno nel call log: testo, agente, decisione di routing (livello,
      candidati, latenza, motivo), tool usati, handoff. Retrocompatibile con i JSONL vecchi.
- [x] Dettaglio conversazione: `GET /api/calls/{call_id}`.
- [x] Criteri di successo + campi di data collection, configurabili da UI
      (`GET/PUT /api/analysis/config`). Valgono per tutta la famiglia, non per singolo
      agente: una chiamata attraversa più agenti, ed è la chiamata intera che si valuta.
- [x] Analisi on-demand: `POST /api/calls/{call_id}/analyze`. Con un provider vero giudica un
      LLM; senza chiavi gira un'euristica dichiarata come tale nella UI.
- [x] Success rate nelle statistiche della dashboard.
- [x] Tab "Conversazioni": lista, trascrizione con chip di routing/tool per turno, pannello di
      analisi, editor dei criteri.
- [ ] Dopo: analisi automatica di tutte le chiamate non ancora analizzate (batch).
- [ ] Dopo: ricerca testuale e tag sulle conversazioni.

### Blocco 2 — Modello agente più profondo  ✅ consegnato

- [x] `first_message` per agente. Solo il root lo usa nella demo (un agente raggiunto per
      handoff risponde a quello che ha causato l'handoff, non si ripresenta). Collegato in
      `cli.py` (`chat`) e `voice/worker.py` (`session.say()` prima del primo turno).
- [x] LLM per agente: provider, modello, temperature. `AgentSpec.llm_provider/llm_model/
      llm_temperature`, risolti da `llm.get_provider_for_agent()` (cache per provider+modello,
      i client veri aprono una connessione in `__init__`) e usati solo da `respond()` —
      `classify()` resta sul provider di default della chiamata apposta, per non far variare
      il routing per agente di destinazione. Vuoto = eredita `VOICE_ORCH_PROVIDER`.
- [x] Voce collegata davvero al TTS (fixa D1): `voice_id`/`voice_stability`/`voice_speed` per
      agente. `OrchestratorAgent.apply_voice()` usa l'API pubblica `Agent.update_options(tts=...)`
      quando cambia l'agente che risponde (all'inizio era uno scambio di `self._tts` dentro
      `tts_node()`: sostituito in D12). Verificato su una chiamata reale, vedi **D12**.
- [x] Tool built-in `end_call` (`tools/end_call_tool.py`, stesso schema di
      `transfer_to_human`). In voce, `OrchestratorAgent` aspetta `SpeechHandle.wait_for_playout()`
      del saluto e poi chiude la stanza (`ctx.delete_room()`) — all'inizio era un'attesa stimata
      sul numero di parole: sostituita in D12, verificata su una chiamata reale.
- [x] Picker veri al posto dei campi testo libero: eligibility ha un builder
      campo/operatore/valore con fallback a testo libero per espressioni con `and`/`or`/`not`
      (`EligibilityBuilder.tsx`); voce è un dropdown di preset ElevenLabs + id personalizzato
      (`VoicePicker.tsx`); LLM è un dropdown provider + modello/temperature (`LlmOverridePicker.tsx`).

### Blocco 3 — Tool webhook HTTP  ✅ consegnato

- [x] Tool custom: URL, metodo (GET/POST/PUT/PATCH/DELETE), header, parametri.
      `tools/webhook_tool.py` (`WebhookTool`/`WebhookToolConfig`), config-driven
      esattamente come i server MCP (`config/webhook_tools.yaml`, mirror
      web-editable in `webapi/webhook_repository.py` + `webhook_sync.py`, stesso
      pattern "sincronizza il registry in-place, usabile dal turno dopo senza
      riavvio" di `mcp_sync.py`). I "parametri in JSON schema" che l'originale
      prometteva sono presi da due soli posti — uno slot della chiamata
      (`session.slots[...]`) o un valore letterale fissato in fase di
      configurazione — mai da un'estrazione LLM a testo libero: questo progetto
      non usa native function-calling (vedi `tools/base.py`), quindi
      `should_trigger()` resta lo stesso meccanismo a parole-chiave di ogni
      altro tool, non un riempimento di schema.
- [x] Secrets mai in chiaro nella UI: un valore header può essere
      `{{secret:NOME}}`, risolto a tempo di chiamata leggendo
      `VOICE_ORCH_SECRET_NOME` dall'ambiente del server — mai salvato né
      mostrato nel browser o nel DB. Un secret referenziato ma non impostato
      fa fallire quella singola chiamata con un errore chiaro, non invia un
      header vuoto in silenzio.
- [x] Log delle esecuzioni dei tool: ogni chiamata webhook (successo o
      fallimento) viene accodata a `data/webhook_log.jsonl`
      (`tools/webhook_log.py`, stesso formato JSONL-append-only di
      `call_log.py`, stessa ragione: zero dipendenze extra nel core), letta
      dalla tab "Log esecuzioni" del pannello (`GET
      /api/webhook-tools/executions`).
- [x] Demo pronta all'uso: `config/webhook_tools.yaml` include un tool
      `network_status` agganciato all'agente `tech_internet`
      (`webhook:network_status` in `config/agents.yaml`) — a differenza del
      demo MCP (un processo locale, zero rete), un tool HTTP ha bisogno per
      forza di un endpoint vero: punta a `https://httpbin.org/anything`
      (gratuito, senza chiave, pensato apposta per questo), quindi richiede
      internet in uscita — dichiarato esplicitamente nel commento YAML invece
      di nasconderlo. I test (`tests/test_webhook_tool.py`) restano comunque
      offline al 100%: esercitano lo stesso identico percorso di
      `WebhookTool.run()` contro un `httpx.MockTransport` iniettato, non
      contro la rete vera.

### Blocco 4 — Vista grafo delle famiglie  ✅ consegnato

- [x] Famiglia mostrata come grafo (nodi = agenti, archi = possibili handoff), oltre
      all'albero testuale (toggle "Albero"/"Grafo" nel tab Agent builder). `AgentGraph.tsx`,
      layout automatico ad albero finché un nodo non viene trascinato (poi la posizione si
      salva in `AgentRow.layout_x/layout_y` via `PATCH /api/agents/{id}/layout`).
- [x] Sugli archi, il livello del router che li attiva: badge "gate" quando il figlio ha
      un'`eligibility`, più "pattern" (ha `triggers`) o "LLM fallback" (nessun trigger) — letto
      direttamente dai campi dell'agente, non ri-derivato chiamando il router. Gli agenti con
      `transfer_to_human`/`end_call` tra i tool hanno anche un arco tratteggiato verso due nodi
      virtuali ("Operatore umano"/"Fine chiamata"), per rendere visibile che l'unica uscita da
      una foglia è un tool esplicito (il router guarda solo in basso — vedi `routing/router.py`).
- [x] Drag-and-drop (persistito), duplica agente (POST di una copia con nuovo id, stesso
      parent), ricerca (filtra/attenua i nodi per id/nome/descrizione).
- [x] Reparenting (D13): trascinare un nodo sopra un altro nodo (invece che su spazio
      vuoto) chiede conferma e sposta l'intero sotto-albero sotto il nuovo genitore —
      `PATCH /api/agents/{id}/parent`, con validazione anti-ciclo sia lato client
      (disabilita i bersagli non validi durante il trascinamento) sia, in modo
      autoritativo, lato backend (`repository.reparent_agent`).

### Blocco 5 — Knowledge base da UI  ✅ consegnato

- [x] Core condiviso `knowledge.py`: chunking (sezioni `##`, poi paragrafi oltre
      `MAX_CHUNK_CHARS` = 1200, con il titolo della sezione ripetuto su ogni pezzo; una
      sezione fatta solo di titoli non è un chunk) e ricerca BM25 con punteggi e
      provenienza (documento, indice del chunk). Lo usa il tool `knowledge_lookup` *e*
      l'anteprima della UI: l'anteprima non può divergere da ciò che l'agente riceve.
- [x] Indice in cache con chiave (nome, mtime, dimensione) per file: un documento
      modificato dalla UI viene re-indicizzato alla query successiva, senza riavvio
      (prima la cache `lru_cache` per nome serviva il contenuto vecchio per sempre).
- [x] Passaggi con punteggio 0 scartati: se nessun chunk ha parole in comune con la
      domanda, il tool dice al modello che non c'è nulla e al chiamante non dice niente,
      invece di leggere un paragrafo a caso. Il tool ora registra anche le fonti
      (`data.sources`: documento, chunk, punteggio).
- [x] Upload da testo, file (`.md`/`.txt`, letto nel browser e inviato come testo) e
      URL (`POST /api/knowledge/from-url`: HTML → testo con i titoli convertiti in
      sezioni, script/nav/footer scartati; rifiuta host locali/privati anche dopo un
      redirect). Nomi normalizzati, niente path; 409 se esiste già, salvo "sovrascrivi".
- [x] Vista documento: origine, dimensione, agenti che lo usano, chunk numerati o testo
      completo. Eliminazione rifiutata (409) se un agente lo usa ancora. Un nome
      referenziato da un agente senza file dietro compare in lista come "file mancante".
- [x] Anteprima "Prova una domanda": su tutti i documenti, su uno, o sui documenti di un
      agente (con i primi 2 marcati "usato dall'agente", come fa il tool); clic su un
      risultato apre il documento sul chunk evidenziato.
- [x] Form agente: i file di knowledge sono checkbox sui documenti esistenti, non più
      nomi a testo libero (un refuso falliva in silenzio).

### Blocco 6 — Piattaforma online (Render, due servizi + Postgres)  🚧 in corso

Perché: oggi il progetto si prova solo in locale. Su Render gira solo il worker vocale, un
background worker senza URL, quindi non lo si può nemmeno chiamare senza un client esterno come
l'Agents Playground di LiveKit. L'obiettivo è il ciclo base della sezione 1 **online**: creo e
orchestro gli agenti dal builder, li provo in voce dal browser, e quello che salvo risponde subito
alle chiamate vere. Poi vedo conversazioni, analisi e dashboard.

Cosa è e cosa non è: una piattaforma **single-owner** online. Non è multi-tenant (account,
workspace, agenti isolati per cliente, billing per cliente), che resta escluso, vedi sotto. Lo
schema però va pensato in modo che aggiungere un `workspace_id` più avanti sia un'estensione e non
una riscrittura.

Topologia scelta (vedi log decisioni): **web service + worker + Postgres gestito**, non un servizio
unico con disco condiviso.

| Servizio Render | Piano | Costo/mese (listino ott. 2026) |
|---|---|---|
| Web service (FastAPI + frontend compilato) | Starter, 512 MB | $7 |
| Background worker (LiveKit) | Standard, 2 GB (sotto va in OOM, D7) | $25 |
| Postgres | base (256 MB) | $6 + spazio |
| **Totale** | | **~$38–40** (oggi $25, solo il worker) |

- [x] **DB configurabile.** `VOICE_ORCH_DATABASE_URL` attiva la **modalità condivisa**: un solo
      database (Postgres su Render; accettato il formato `postgres://…` di Render, driver psycopg 3
      con l'extra `postgres`) per tutto. Senza, il comportamento è quello di prima: SQLite del
      builder più file, quindi CLI e test non richiedono database. `sync_columns()` ora usa letterali
      adatti al dialetto, e il `DROP COLUMN` di una colonna orfana viene loggato.
      `VOICE_ORCH_TEST_DATABASE_URL` fa girare tutta la suite in modalità condivisa contro un DB
      vero: 182/182 verdi su Postgres 16.
- [x] **Dati condivisi nel DB, non su file.** Web e worker sono macchine diverse e non condividono
      il disco. Vanno nel DB: il call log (oggi `data/call_log.jsonl`), le analisi (già in DB), il
      log dei webhook (oggi JSONL), il contenuto dei documenti di knowledge (oggi file in
      `data/knowledge/`, D16) e il contatore dei minuti di `usage_guard` (oggi file JSON).
      Vincolo da non rompere: il **core** (CLI, `orchestrator.py`, worker) resta importabile senza
      `fastapi`/`sqlalchemy` (vedi le decisioni su `call_log.py`). Strada probabile: interfacce di
      storage nel core con un'implementazione su file (default, CLI e test) e una su DB, selezionata
      da configurazione. **Fatto così:** `call_log`, `webhook_log`, `UsageGuard` e `knowledge`
      passano a `webapi/stores.py` (import lazy) solo se `config.shared_mode()`. Nuove tabelle
      `calls`, `webhook_executions`, `usage_days`; il testo dei documenti in
      `knowledge_docs.content`, con la prima apertura che copia i documenti demo nel DB.
      L'incremento dei minuti usa un lock di riga, per due worker che chiudono insieme.
      `tests/test_shared_mode.py` verifica anche che in modalità condivisa non venga scritto nessun
      file.
- [ ] **Il worker legge la famiglia dal DB** a ogni chiamata, invece di `config/agents.yaml`: quello
      che salvo nel builder è subito "in onda". Chiude D4. `agents.yaml` resta il seed iniziale e
      l'export manuale resta utile per la CLI.
- [ ] **Un solo web service.** FastAPI serve anche `web/dist`: niente Vite in produzione, niente CORS
      tra domini.
- [ ] **Accesso.** Login owner con password da variabile d'ambiente (sessione via cookie firmato). I
      visitatori senza login vedono tutto in sola lettura: builder, knowledge base, conversazioni,
      dashboard. Il test vocale è aperto a tutti ma dentro il tetto giornaliero di minuti già
      esistente; da valutare un limite per visitatore, per esempio per IP. Ogni endpoint che scrive
      richiede la sessione owner, con test dedicati: un visitatore che prova a scrivere riceve 401.
- [ ] **`render.yaml` (Blueprint)** che crea web, worker e database in un passo, con le variabili
      d'ambiente dichiarate: chiavi LiveKit/Deepgram/ElevenLabs, password owner, `DATABASE_URL`
      collegato al DB. **Il deploy lo lancia Matteo**: chiedere conferma prima.
- [ ] **Verifica online.** Dopo il deploy: login, una modifica nel builder, una chiamata dal tab
      "Test live (voce)" che usa la modifica, la chiamata visibile in Conversazioni.
      `scripts/d12_room_e2e.py` contro il worker deployato richiede la sua dispatch: il worker di
      produzione usa la dispatch automatica, quello locale `agent_name`.

Lavorare in 2–3 commit verificabili (per esempio: 1. DB configurabile e dati condivisi; 2. worker
dal DB e web service unico; 3. accesso e `render.yaml`), test verdi a ogni commit, questa sezione
aggiornata nello stesso commit del codice.

Si apre in seguito, non in questo blocco: multi-tenant (`workspace_id` su ogni tabella, account,
inviti), limiti e costi per workspace, più worker in parallelo.

### Escluso di proposito (per ora)

Telefonia (numeri, SIP, batch outbound), widget embeddabile, versioning con branch/merge,
multi-tenant e billing. Non sono ciò che differenzia il progetto, e sono la distanza di
infrastruttura che nessuna rifinitura della UI chiude.

---

## 4. Debiti tecnici e problemi noti

| # | Problema | Impatto | Fix previsto |
|---|---|---|---|
| ~~D1~~ | Il campo `voice` dell'agente non era collegato al TTS: la voce era fissa in `voice/worker.py` | — | ✅ risolto nel blocco 2 (`voice_id`/`voice_stability`/`voice_speed`), verificato su una chiamata vera in D12 |
| ~~D2~~ | Il worker vocale (e la CLI) caricavano solo `config/agents.yaml`, non la famiglia modificata nella UI | — | ✅ risolto: `POST /api/agents/export` scrive la famiglia del builder in `agents.yaml` usando `save_family()` (già esistente, usato da `agents add`/`remove` da CLI). Azione esplicita, non automatica — va rifatta a ogni cambio da propagare. Non serve riavviare: `load_family()` viene chiamato di nuovo a ogni `chat`/`route`/chiamata vocale |
| ~~D3~~ | Il box "try it" usava sempre `FakeProvider`, anche con un provider vero configurato | — | ✅ risolto: `use_configured_provider` su `POST /api/test/route` + `GET /api/llm/status` (provider richiesto vs. risolto: `get_provider()` ricade su FakeProvider in silenzio se manca la chiave, e la UI ora lo dice). Checkbox nel box, attiva di default quando c'è un provider vero; la risposta riporta il provider che l'ha composta davvero (dopo l'override per agente). Errore del provider → 502 con il messaggio, non 500 |
| D4 | Doppia fonte di verità: YAML (CLI/test) e SQLite (UI). Dal fix di D2 esiste l'export DB → YAML, ma è manuale: finché non lo si lancia, CLI e worker vocale vedono la famiglia vecchia | voluto per ora, documentato nel README | export automatico a ogni salvataggio, o CLI/worker che leggono il DB |
| ~~D5~~ | Nell'opzione "tool dinamici" erano promessi webhook + MCP; è stato fatto solo MCP | — | ✅ risolto nel blocco 3 (`tools/webhook_tool.py` + UI dedicata) |
| ~~D6~~ | `config.py` andava in crash con una variabile numerica impostata ma vuota | — | ✅ risolto: valore vuoto = assente (`_env_float`) |
| D7 | Il worker su Render richiede il piano Standard (2 GB): sul piano da 512 MB va in OOM | costo 25 $/mese | accettato; `num_idle_processes=0` riduce il danno |
| D8 | Python 3.14 nel venv locale: `livekit-api` non si installava | ambiente rotto | usare Python 3.11/3.12 (fatto sul Mac) |
| ~~D9~~ | Bundle frontend > 1 MB (Recharts + livekit-client in un solo chunk) | — | ✅ risolto: ogni tab tranne l'albero dell'Agent builder è caricata con `React.lazy` al primo clic. Chunk iniziale da 1.172 kB (326 kB gzip) a 261 kB (79 kB gzip); `livekit-client` (520 kB) e `recharts` (362 kB) si scaricano solo aprendo "Test live" e "Dashboard". `chunkSizeWarningLimit` a 560 kB: l'avviso torna utile se cresce qualcos'altro |
| ~~D10~~ | `FakeProvider.respond()` ripeteva il testo dei tool così com'era: per `transfer_to_human`/`end_call` è un'istruzione per l'LLM ("Tell the caller, briefly…"), che finiva letta come risposta | — | ✅ risolto: `ToolResult.caller_text` (frase per il chiamante) separato da `summary` (per l'LLM); `respond()` riceve entrambe le liste, i provider veri leggono `tool_notes`, FakeProvider `caller_notes`. Impostato per transfer, end_call, account, knowledge (il passaggio migliore, non tutti) e webhook (errori → "servizio non disponibile") |
| ~~D11~~ | L'euristica di valutazione (senza chiavi) dava verdetti poco sensati, es. "Agente giusto: fallito" su un instradamento corretto | — | ✅ risolto: criteri con un `kind` — `llm` (giudicato da un modello; senza chiavi ora è `unknown` con il motivo, mai più un punteggio a sovrapposizione di parole) oppure strutturali `final_agent`/`tool_used`/`tool_not_used`, verificati in modo deterministico sulla trascrizione con qualsiasi provider e mai mandati all'LLM. Default: "Instradata a uno specialista" (`final_agent`) e "Senza operatore umano" (`tool_not_used: transfer_to_human`). I dati estratti restano euristici senza chiavi (etichettati). Un DB già seminato tiene i criteri vecchi (tutti `llm`): vanno cambiati dalla UI |
| ~~D12~~ | La voce per-agente e la chiusura dopo `end_call` erano state scritte leggendo l'API di `livekit-agents` 1.8.4 ma mai eseguite su una chiamata vera | — | ✅ risolto e verificato con chiavi reali, prima con `scripts/d12_live_check.py` (sessione vera + ElevenLabs, senza stanza) poi con `scripts/d12_room_e2e.py` (stanza LiveKit vera, chiamante scriptato, Deepgram + ElevenLabs, worker locale): saluto a ~255 Hz, risposta di billing dopo l'handoff a ~110 Hz (voce Arnold), stanza chiusa 0,01 s dopo la fine del saluto, chiamata registrata nel call log con le trascrizioni Deepgram corrette. La verifica ha trovato **due bug che rompevano ogni chiamata vera**: (1) senza un `llm=` configurato, `livekit-agents` 1.8.4 salta la risposta a ogni turno dell'utente (`elif self.llm is None: return`), quindi l'agente diceva il saluto e poi taceva: ora l'agente porta un `RouterLLM` segnaposto mai chiamato; (2) il plugin ElevenLabs legge solo `ELEVEN_API_KEY`, mentre progetto e `.env.example` documentano `ELEVENLABS_API_KEY`: con il nome documentato il worker andava in errore alla creazione del TTS. Ora `config.ELEVENLABS_API_KEY` accetta entrambi e la chiave viene passata esplicitamente. Inoltre: voce cambiata con `Agent.update_options(tts=...)` (API pubblica, fa prewarm e aggancia gli eventi di errore) invece dello scambio di `self._tts` in `tts_node()`, che con un'interruzione poteva ripristinare la voce sbagliata; chiusura dopo `SpeechHandle.wait_for_playout()` invece della stima sulle parole. `tests/test_voice_agent.py` copre lo stesso percorso offline (TTS finto) nella suite normale |
| ~~D13~~ | Il grafo (blocco 4) non supporta il reparenting: si può trascinare un nodo visivamente ma il suo genitore nell'albero non cambia | limite preesistente di `repository.update_agent` (mai esposto, non introdotto ora) | ✅ risolto: `PATCH /api/agents/{id}/parent` (`repository.reparent_agent`, con `_is_descendant` anti-ciclo) + nel grafo, trascinare un nodo sopra un altro nodo (invece che su spazio vuoto) chiede conferma e sposta il sotto-albero; trascinare un nodo su un proprio discendente non è un bersaglio valido (stesso controllo lato client, poi comunque ribadito dal backend) |
| **D14** | Il tool webhook demo (`network_status`, blocco 3) punta a `https://httpbin.org/anything` — a differenza di ogni altro demo in questo progetto (MCP: un processo locale; agenti/tool built-in: zero rete), questo ha bisogno per forza di internet in uscita, perché un tool HTTP non ha un equivalente "stdio locale" | il "try it"/la chiamata vocale di demo che tocca `tech_internet` con una frase come "stato della rete" fallisce offline o dietro un firewall che blocca httpbin.org | accettato e dichiarato esplicitamente nel commento YAML, non nascosto; i test restano offline al 100% (`httpx.MockTransport`, vedi tests/test_webhook_tool.py) — se serve un demo offline, l'alternativa è un server HTTP locale bundlato con lifecycle proprio, più invasivo di quanto valga per questa demo |
| ~~D15~~ | `create_all()` crea le tabelle mancanti ma non tocca quelle esistenti: un `agents.db` creato prima del blocco 2/4 non aveva `first_message`, `llm_*`, `voice_*`, `layout_*` (ogni query su `agents` falliva) e aveva ancora la colonna `voice` NOT NULL senza default (ogni INSERT falliva). Trovato sul DB locale del Mac | — | ✅ risolto: `db.sync_columns()` all'apertura aggiunge le colonne mancanti con il default del modello, ed elimina solo le colonne orfane NOT NULL senza default (le altre restano). Non è un framework di migrazioni: niente rinomini né cambi di tipo |
| **D16** | I documenti caricati dalla UI vivono in `data/knowledge/` sulla macchina dove gira l'API, e sono in `.gitignore` (solo i 4 file demo sono tracciati) | il worker vocale deployato (Render) non li vede finché non vengono committati a mano (`git add -f data/knowledge/<nome>`) | voluto: un documento caricato può essere privato e il repo è un portfolio pubblico — meglio un passo esplicito che un commit accidentale. Stesso principio dell'export manuale di D2/D4 |
| **D17** | Limiti della knowledge base: retrieval solo lessicale (BM25, nessuna stopword: "a", "il" contano), nessun supporto PDF/DOCX, nessun crawl di più pagine, nessuna cartella | una domanda in italiano su un documento in inglese recupera poco; l'anteprima lo rende visibile, non lo risolve | stopword italiane come primo passo economico; poi estrazione PDF (`pypdf`) e, se serve, la pipeline ibrida di Company Brain dietro la stessa interfaccia `knowledge.search()` |

---

## 5. Decisioni architetturali (log)

| Data | Decisione | Perché |
|---|---|---|
| — | Router a 3 livelli: gate deterministico → pattern → LLM di fallback | la maggior parte delle decisioni si risolve senza LLM: latenza e costo |
| — | Agenti in YAML per CLI/test, copia in SQLite per la UI (seed una volta) | non toccare codice core già testato per servire un livello più nuovo |
| — | Call log in JSONL nel core, non in SQLite | CLI e worker vocale scrivono senza dipendere da `fastapi`/`sqlalchemy` |
| 2026-10 | `num_idle_processes=0` sul worker LiveKit | riduce la RAM a riposo; non sostituisce un'istanza adeguata |
| 2026-10 | Server MCP da UI: `webapi/mcp_sync.py` modifica `tools.REGISTRY` sul posto | attivi al turno dopo senza riavvio e senza toccare `orchestrator.py` |
| 2026-10 | Criteri di valutazione a livello di famiglia, non per agente | una chiamata attraversa più agenti; si valuta la chiamata intera |
| 2026-10 | Analisi salvate in SQLite (webapi), trascrizioni nel JSONL (core) | il core registra le chiamate senza dipendenze; la UI possiede criteri e risultati |
| 2026-10 | LLM per agente: `classify()` resta sempre sul provider di default della chiamata, solo `respond()` guarda l'override dell'agente | il routing deve restare economico/deterministico; far scegliere il modello di classificazione all'agente di destinazione avrebbe reso il costo di una chiamata dipendente da dove finisce, non da come inizia |
| 2026-10 | D12: un `RouterLLM` segnaposto sull'agente invece di togliere l'override di `llm_node` | `livekit-agents` decide *se* rispondere guardando che ci sia un LLM, non che venga usato: il segnaposto soddisfa quella regola senza cambiare chi risponde davvero (il router), e `chat()` che solleva è la prova che nessuno lo chiama |
| 2026-10 | D12: verifica vocale con dispatch esplicito (`agent_name`) verso un worker locale | il worker deployato su Render è registrato sullo stesso progetto LiveKit: con la dispatch automatica una stanza di test poteva finire a lui, con il codice vecchio |
| 2026-10 | Blocco 6: due servizi Render (web + worker) con Postgres gestito, non un servizio unico con disco condiviso (~$38–40/mese contro ~$25) | un servizio unico costa come oggi ma lega worker e builder allo stesso disco, una scorciatoia da smontare appena servono più worker o più utenti (un servizio Render con disco non scala oltre un'istanza). Il lavoro in più (dati condivisi nel DB, worker che legge dal DB) è quello che una piattaforma richiede comunque |
| 2026-10 | Blocco 6: accesso "owner con password + visitatori in sola lettura", non multi-utente | per un portfolio conta che il ciclo base funzioni dal vivo e sia linkabile; account e workspace sono il salto multi-tenant, rimandato |
| 2026-10 | D9: code-splitting per tab con `React.lazy`, non `manualChunks` | le due dipendenze pesanti servono ognuna a una sola tab: caricarle all'apertura di quella tab toglie il costo dal primo caricamento, mentre dividere i vendor in chunk separati lo avrebbe solo spezzato |
| 2026-10 | Voce per agente via `tts_node()` override (scambio di `self._tts`), poi sostituito in D12 da `update_options(tts=...)`; non via il multi-agent handoff pattern di LiveKit (un'istanza `Agent` per sotto-agente) | l'architettura usa già un `OrchestratorAgent` unico per tutta la chiamata (il router interno gestisce gli handoff, non LiveKit) — cambiarlo per la sola voce avrebbe significato riscrivere il modello della chiamata per un singolo campo |
| 2026-10 | Il grafo (blocco 4) mostra solo archi genitore→figlio (sempre veri) + archi tratteggiati verso nodi virtuali per i tool di uscita (`transfer_to_human`/`end_call`), non un grafo di stato libero come il `workflow` di ElevenLabs | `routing/router.py` guarda solo in basso nell'albero — un grafo più "ricco" mentirebbe su come funziona davvero il routing |
| 2026-10 | D13 (reparenting nel grafo): il trascinamento esistente fa doppio uso — su spazio vuoto sposta solo `layout_x`/`layout_y`, su un altro nodo cambia `parent_id` (con conferma) | riusa il gesto già presente invece di aggiungere un widget dedicato; il controllo anti-ciclo lato client (`subtreeIds`) è solo per disabilitare bersagli non validi durante il trascinamento — l'unica fonte di verità resta `reparent_agent` lato backend |
| 2026-10 | Blocco 3: i secrets per gli header dei tool webhook vivono solo come variabili d'ambiente (`VOICE_ORCH_SECRET_<NOME>`), referenziate con `{{secret:NOME}}` nella UI — non un secrets store cifrato nel DB | stessa convenzione già usata per `LIVEKIT_API_SECRET`/le chiavi dei provider LLM: zero infrastruttura nuova, e un valore che non passa mai per browser/DB non può trapelare da lì per costruzione |
| 2026-10 | Blocco 3: i parametri di un tool webhook vengono da `session.slots[...]` (per nome) o da un valore letterale fissato in configurazione, mai da un'estrazione LLM del testo dell'utterance | coerente con la scelta di progetto di non usare native function-calling (vedi `tools/base.py`): un tool si attiva per parola-chiave, quindi i suoi argomenti non possono venire da un riempimento di schema che richiederebbe esattamente il meccanismo che il progetto evita |
| 2026-10 | D10: ogni tool restituisce due testi, `summary` per l'LLM e `caller_text` per il chiamante, invece di un solo testo "neutro" | un'istruzione al modello ("di' al chiamante che…") è il modo giusto di guidare un LLM ed è sbagliata letta parola per parola; un solo testo costringe a peggiorare l'uno o l'altro caso |
| 2026-10 | D11: senza un LLM, un criterio scritto in linguaggio naturale è `unknown`, non stimato | un punteggio a parole in comune *sembra* un verdetto e sbaglia una volta su due: in una demo è peggio di nessun verdetto. Ciò che si può verificare davvero senza modello (dove è finita la chiamata, quali tool sono partiti) diventa un tipo di criterio a sé, deterministico anche con un LLM configurato |
| 2026-10 | D15: `sync_columns()` additivo invece di Alembic | lo schema è piccolo e cambia per aggiunte; serve che un DB locale vecchio continui ad aprirsi, non una storia delle migrazioni. Da rivedere al primo rinomino o cambio di tipo |
| 2026-10 | Blocco 5: il contenuto dei documenti resta nei file di `data/knowledge/`; SQLite tiene solo da dove vengono (`KnowledgeDocRow`) | CLI, worker vocale e API leggono gli stessi file: per la knowledge base non nasce una seconda fonte di verità come per gli agenti (D4) |
| 2026-10 | Blocco 5: upload di file come JSON (il browser legge il file e manda il testo), non multipart | niente dipendenza `python-multipart`, e accettiamo comunque solo formati testo; l'estrazione da PDF sarebbe lato server in ogni caso |
| 2026-10 | Blocco 5: la ricerca scarta i chunk con punteggio 0 invece di restituire "i migliori tra niente" | un passaggio senza nessuna parola in comune con la domanda non è grounding, è rumore che il modello (o FakeProvider) presenta come risposta |
| 2026-10 | Blocco 5: "aggiungi da URL" controlla l'host a ogni richiesta (redirect inclusi) e rifiuta indirizzi locali/privati | la pagina la scarica il server: senza controllo, il campo URL leggerebbe qualsiasi servizio raggiungibile dalla sua rete |
| 2026-10 | Blocco 3: log delle esecuzioni webhook in un JSONL dedicato (`data/webhook_log.jsonl`, `tools/webhook_log.py`), non negli `attributes` di `CallSession.event_log`/`call_log.jsonl` | stesso principio di `call_log.py`: il tool che fa la chiamata HTTP (e quindi `orchestrator.py`, la CLI, il worker vocale che lo importano) deve restare installabile con zero dipendenze `webapi` (niente sqlalchemy/fastapi); un file JSONL separato ottiene lo stesso risultato senza toccare `orchestrator.py` o lo schema di `CallRecord` |

---

## 6. Storico feature consegnate

| Commit | Feature |
|---|---|
| `359062c` | Agent builder: backend FastAPI + frontend React |
| `f3ee513` | Console di test vocale live |
| `f49d27b` | Dashboard di analytics sul call log |
| `11d9ed7` | `num_idle_processes=0` sul worker (mitigazione OOM) |
| `2a5c8e9` | Gestione server MCP dalla UI |
| `f419011` | Blocco 1: trascrizioni per turno, tab Conversazioni, criteri + analisi post-call |
| `b094f8a` | Fix D2: `POST /api/agents/export` — il builder scrive su `agents.yaml` su richiesta |
| `c55fea8` | Blocco 2 (modello agente più profondo: first_message, LLM e voce per agente, tool `end_call`, picker veri) + blocco 4 (vista a grafo con drag-and-drop, duplica, ricerca, badge di livello router) |
| `5ab1db0` | D13: reparenting nel grafo — trascinare un nodo sopra un altro ne cambia il genitore (con conferma e anti-ciclo) |
| `1b6e10d` | Blocco 3: tool webhook HTTP (URL/metodo/header/parametri, secrets via variabile d'ambiente, log esecuzioni) — risolve anche D5 |
| `a0e9dde` | D3 (try-it sul provider configurato), D10 (testo per il chiamante separato dall'istruzione per l'LLM), D11 (criteri strutturali, niente verdetti euristici sui criteri in linguaggio naturale), D15 (`sync_columns()`: un DB locale vecchio torna ad aprirsi) |
| `8df57c3` | Blocco 5: knowledge base da UI (documenti da testo/file/URL, vista dei chunk, anteprima del retrieval, picker nel form agente; ricerca condivisa con il tool, cache invalidata alla modifica, chunk a punteggio 0 scartati) |
| `8a429cb` | D9 (tab caricate su richiesta: chunk iniziale 1.172 → 261 kB) + D12 (voce per agente e chiusura dopo il saluto verificate su una chiamata LiveKit reale; corretti due bug che rompevano ogni chiamata vera: nessuna risposta senza LLM configurato, chiave ElevenLabs col nome sbagliato) |
| `58ed2f4` | Piano del blocco 6 (piattaforma online: web + worker + Postgres su Render) aggiunto alla roadmap, nessun cambio di codice |
| (questo commit) | Blocco 6, passo 1: modalità condivisa (`VOICE_ORCH_DATABASE_URL`, Postgres o SQLite): chiamate, log webhook, minuti vocali e testo della knowledge nel DB; suite verde anche su Postgres |
