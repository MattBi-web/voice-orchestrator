# Roadmap e gap map — voice-orchestrator vs ElevenLabs Agents

Documento di lavoro: tiene traccia di dove siamo, dove vogliamo arrivare e perché.
Si aggiorna a ogni feature, nello stesso commit del codice.

Ultimo aggiornamento: 2026-10-04 (blocco 2 + blocco 4)

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
| **Config agente** | `conversation_config`: ASR, turn-taking, TTS (voce, velocità, stabilità), `agent.first_message`, lingua, `prompt.llm` / `temperature` per agente | `first_message`, LLM (provider/modello/temperature) e voce (voice_id/stabilità/velocità) per agente, con fallback alla famiglia. Voce collegata davvero al TTS (vedi debito D12: non verificata su una chiamata reale) | 🟡 |
| **Famiglie / flusso** | `workflow`: nodi `override_agent`, `standalone_agent`, `phone_number`, `tool` + archi con `forward_condition` | albero di agenti + router a 3 livelli + handoff + **vista a grafo** (nodi/archi annotati col livello di router, drag-and-drop, duplica, ricerca) oltre all'editor ad albero testuale | 🟡 diverso, non indietro |
| **Tool built-in** | `end_call`, `transfer_to_number`, `transfer_to_agent`, `language_detection`, `voicemail_detection`, `skip_turn` | `transfer_to_human`, `end_call` | 🟡 |
| **Tool custom** | webhook HTTP con parametri in JSON schema, client tool, secrets | tool Python fissi + server MCP gestibili da UI | 🟡 manca il webhook |
| **MCP** | CRUD server, lista tool, approval policy | CRUD server da UI, attivi senza riavvio | ✅ (senza approval policy) |
| **Knowledge base** | upload file/URL/testo, crawl, indice RAG, cartelle | file markdown in `data/knowledge/` referenziati per nome, BM25 | 🟡 |
| **Test testuale** | "simulate conversation" | box "try it" (un turno, FakeProvider) | 🟡 |
| **Test vocale** | widget / link condivisibile | tab "Test live (voce)" via LiveKit | ✅ (vedi debito D2) |
| **Conversazioni** | lista, dettaglio con trascrizione + audio, feedback, ricerca, tag | lista + dettaglio con trascrizione e routing/tool per turno; niente audio, ricerca, tag | 🟡 |
| **Valutazione post-call** | `evaluation.criteria` + `data_collection` giudicati da LLM | criteri + data collection da UI, analisi LLM on-demand (euristica dichiarata senza chiavi), success rate | ✅ (manca l'analisi automatica a fine chiamata) |
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
      agente. `voice/agent.py`'s `OrchestratorAgent.tts_node()` scambia `self._tts` con
      un'istanza `elevenlabs.TTS` per-agente prima di delegare alla sintesi di default. Vedi
      **D12**: ragionato sull'API reale di `livekit-agents` 1.8.4, non eseguito su una chiamata
      vera (niente credenziali LiveKit/ElevenLabs in questo ambiente).
- [x] Tool built-in `end_call` (`tools/end_call_tool.py`, stesso schema di
      `transfer_to_human`). In voce, `OrchestratorAgent` aspetta un tempo euristico (basato sul
      conteggio parole del saluto) e poi chiude la stanza (`ctx.delete_room()`) — vedi **D12**,
      stessa riserva: non è un'attesa reale della fine della sintesi vocale.
- [x] Picker veri al posto dei campi testo libero: eligibility ha un builder
      campo/operatore/valore con fallback a testo libero per espressioni con `and`/`or`/`not`
      (`EligibilityBuilder.tsx`); voce è un dropdown di preset ElevenLabs + id personalizzato
      (`VoicePicker.tsx`); LLM è un dropdown provider + modello/temperature (`LlmOverridePicker.tsx`).

### Blocco 3 — Tool webhook HTTP

- [ ] Tool custom: URL, metodo, header, parametri in JSON schema.
- [ ] Secrets per le chiavi usate negli header (mai in chiaro nella UI).
- [ ] Log delle esecuzioni dei tool.

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
- [ ] Non fatto: l'"aggiungi figlio" dal grafo apre lo stesso form dell'albero, ma il grafo non
      ha ancora un modo per cambiare il *parent* di un agente esistente (reparenting) —
      limite preesistente di `repository.update_agent`, non introdotto da questo blocco.

### Blocco 5 — Knowledge base da UI

- [ ] Upload file / testo / URL dalla UI.
- [ ] Anteprima dei chunk recuperati per una domanda di prova.

### Escluso di proposito (per ora)

Telefonia (numeri, SIP, batch outbound), widget embeddabile, versioning con branch/merge,
multi-tenant e billing. Non sono ciò che differenzia il progetto, e sono la distanza di
infrastruttura che nessuna rifinitura della UI chiude.

---

## 4. Debiti tecnici e problemi noti

| # | Problema | Impatto | Fix previsto |
|---|---|---|---|
| ~~D1~~ | Il campo `voice` dell'agente non era collegato al TTS: la voce era fissa in `voice/worker.py` | — | ✅ risolto nel blocco 2 (`voice_id`/`voice_stability`/`voice_speed` + `tts_node()` override) — con la riserva di **D12**: non verificato su una chiamata vera |
| ~~D2~~ | Il worker vocale (e la CLI) caricavano solo `config/agents.yaml`, non la famiglia modificata nella UI | — | ✅ risolto: `POST /api/agents/export` scrive la famiglia del builder in `agents.yaml` usando `save_family()` (già esistente, usato da `agents add`/`remove` da CLI). Azione esplicita, non automatica — va rifatta a ogni cambio da propagare. Non serve riavviare: `load_family()` viene chiamato di nuovo a ogni `chat`/`route`/chiamata vocale |
| D3 | Il box "try it" usa sempre `FakeProvider`, anche con un provider vero configurato | il test testuale non riflette le risposte reali | opzione per usare il provider configurato |
| D4 | Doppia fonte di verità: YAML (CLI/test) e SQLite (UI) non si sincronizzano | voluto per ora, documentato nel README | export DB → YAML, o CLI che legge il DB |
| D5 | Nell'opzione "tool dinamici" erano promessi webhook + MCP; è stato fatto solo MCP | buco nella funzionalità | blocco 3 |
| ~~D6~~ | `config.py` andava in crash con una variabile numerica impostata ma vuota | — | ✅ risolto: valore vuoto = assente (`_env_float`) |
| D7 | Il worker su Render richiede il piano Standard (2 GB): sul piano da 512 MB va in OOM | costo 25 $/mese | accettato; `num_idle_processes=0` riduce il danno |
| D8 | Python 3.14 nel venv locale: `livekit-api` non si installava | ambiente rotto | usare Python 3.11/3.12 (fatto sul Mac) |
| D9 | Bundle frontend > 1 MB (Recharts + livekit-client in un solo chunk) | primo caricamento lento | code-splitting per tab |
| D10 | `FakeProvider.respond()` ripete il testo dei tool così com'è: per `transfer_to_human`/`end_call` è un'istruzione per l'LLM ("Tell the caller, briefly…"), che finisce letta come risposta | visibile nelle trascrizioni senza chiavi | far restituire ai tool una nota per l'utente separata dall'istruzione per l'LLM |
| D11 | L'euristica di valutazione (senza chiavi) dà verdetti poco sensati, es. "Agente giusto: fallito" su un instradamento corretto | etichettata come euristica, ma può confondere in una demo | per la demo pubblica configurare un provider vero; in alternativa criteri strutturali (es. agente finale atteso) |
| **D12** | La voce per-agente (`tts_node()` override) e la chiusura automatica della chiamata dopo `end_call` (attesa euristica sul conteggio parole + `ctx.delete_room()`) sono state scritte leggendo l'API reale di `livekit-agents` 1.8.4 installata in questo ambiente, ma **mai eseguite contro una chiamata LiveKit vera** — qui non ci sono credenziali LiveKit/Deepgram/ElevenLabs. Rischio concreto: `Agent.tts` potrebbe essere letto una sola volta all'ingresso nell'agente invece che "a runtime" come dice la sua docstring, nel qual caso lo scambio di `self._tts` non avrebbe effetto | la voce per-agente e l'hangup automatico potrebbero non funzionare finché non testati su una chiamata reale | testare su una chiamata vera (serve `LIVEKIT_URL`/`DEEPGRAM_API_KEY`/`ELEVENLABS_API_KEY`) appena disponibili; se `tts_node()` non basta, l'alternativa è passare a LiveKit's multi-agent handoff pattern (un'istanza `Agent` per sotto-agente, con `session.update_agent()`), più invasivo |
| **D13** | Il grafo (blocco 4) non supporta il reparenting: si può trascinare un nodo visivamente ma il suo genitore nell'albero non cambia | limite preesistente di `repository.update_agent` (mai esposto, non introdotto ora) | esporre `parent_id` in `AgentUpdate` + endpoint dedicato, con validazione anti-ciclo |

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
| 2026-10 | Voce per agente via `tts_node()` override (scambio di `self._tts`), non via il multi-agent handoff pattern di LiveKit (un'istanza `Agent` per sotto-agente) | l'architettura usa già un `OrchestratorAgent` unico per tutta la chiamata (il router interno gestisce gli handoff, non LiveKit) — cambiarlo per la sola voce avrebbe significato riscrivere il modello della chiamata per un singolo campo |
| 2026-10 | Il grafo (blocco 4) mostra solo archi genitore→figlio (sempre veri) + archi tratteggiati verso nodi virtuali per i tool di uscita (`transfer_to_human`/`end_call`), non un grafo di stato libero come il `workflow` di ElevenLabs | `routing/router.py` guarda solo in basso nell'albero — un grafo più "ricco" mentirebbe su come funziona davvero il routing |

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
| (questo commit) | Blocco 2 (modello agente più profondo: first_message, LLM e voce per agente, tool `end_call`, picker veri) + blocco 4 (vista a grafo con drag-and-drop, duplica, ricerca, badge di livello router) |
