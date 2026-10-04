# Roadmap e gap map — voice-orchestrator vs ElevenLabs Agents

Documento di lavoro: tiene traccia di dove siamo, dove vogliamo arrivare e perché.
Si aggiorna a ogni feature, nello stesso commit del codice.

Ultimo aggiornamento: 2026-10-04

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
| **Config agente** | `conversation_config`: ASR, turn-taking, TTS (voce, velocità, stabilità), `agent.first_message`, lingua, `prompt.llm` / `temperature` per agente | prompt, trigger, eligibility, knowledge. LLM globale da env. Campo `voice` salvato ma **non collegato al TTS** | 🟡 |
| **Famiglie / flusso** | `workflow`: nodi `override_agent`, `standalone_agent`, `phone_number`, `tool` + archi con `forward_condition` | albero di agenti + router a 3 livelli + handoff. Editor ad albero testuale | 🟡 diverso, non indietro |
| **Tool built-in** | `end_call`, `transfer_to_number`, `transfer_to_agent`, `language_detection`, `voicemail_detection`, `skip_turn` | `transfer_to_human` | 🟡 |
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

### Blocco 2 — Modello agente più profondo

- [ ] `first_message` per agente.
- [ ] LLM per agente: provider, modello, temperature (oggi è globale da env).
- [ ] Voce collegata davvero al TTS: `voice_id`, velocità, stabilità per agente.
- [ ] Tool built-in `end_call`.
- [ ] Picker veri al posto dei campi testo libero (condizioni, voce).

### Blocco 3 — Tool webhook HTTP

- [ ] Tool custom: URL, metodo, header, parametri in JSON schema.
- [ ] Secrets per le chiavi usate negli header (mai in chiaro nella UI).
- [ ] Log delle esecuzioni dei tool.

### Blocco 4 — Vista grafo delle famiglie

- [ ] Famiglia mostrata come grafo (nodi = agenti, archi = possibili handoff), invece
      dell'albero testuale.
- [ ] Sugli archi, il livello del router che li attiva (gate / pattern / LLM): rende visibile
      la nostra tesi invece di copiare le loro `forward_condition`.
- [ ] Drag-and-drop, duplica agente, ricerca.

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
| D1 | Il campo `voice` dell'agente non è collegato al TTS: la voce è fissa in `voice/worker.py` | la UI promette una cosa che non succede | blocco 2 |
| ~~D2~~ | Il worker vocale (e la CLI) caricavano solo `config/agents.yaml`, non la famiglia modificata nella UI | — | ✅ risolto: `POST /api/agents/export` scrive la famiglia del builder in `agents.yaml` usando `save_family()` (già esistente, usato da `agents add`/`remove` da CLI). Azione esplicita, non automatica — va rifatta a ogni cambio da propagare. Non serve riavviare: `load_family()` viene chiamato di nuovo a ogni `chat`/`route`/chiamata vocale |
| D3 | Il box "try it" usa sempre `FakeProvider`, anche con un provider vero configurato | il test testuale non riflette le risposte reali | opzione per usare il provider configurato |
| D4 | Doppia fonte di verità: YAML (CLI/test) e SQLite (UI) non si sincronizzano | voluto per ora, documentato nel README | export DB → YAML, o CLI che legge il DB |
| D5 | Nell'opzione "tool dinamici" erano promessi webhook + MCP; è stato fatto solo MCP | buco nella funzionalità | blocco 3 |
| ~~D6~~ | `config.py` andava in crash con una variabile numerica impostata ma vuota | — | ✅ risolto: valore vuoto = assente (`_env_float`) |
| D7 | Il worker su Render richiede il piano Standard (2 GB): sul piano da 512 MB va in OOM | costo 25 $/mese | accettato; `num_idle_processes=0` riduce il danno |
| D8 | Python 3.14 nel venv locale: `livekit-api` non si installava | ambiente rotto | usare Python 3.11/3.12 (fatto sul Mac) |
| D10 | `FakeProvider.respond()` ripete il testo dei tool così com'è: per `transfer_to_human` è un'istruzione per l'LLM ("Tell the caller, briefly…"), che finisce letta come risposta | visibile nelle trascrizioni senza chiavi | far restituire ai tool una nota per l'utente separata dall'istruzione per l'LLM |
| D11 | L'euristica di valutazione (senza chiavi) dà verdetti poco sensati, es. "Agente giusto: fallito" su un instradamento corretto | etichettata come euristica, ma può confondere in una demo | per la demo pubblica configurare un provider vero; in alternativa criteri strutturali (es. agente finale atteso) |
| D9 | Bundle frontend > 1 MB (Recharts + livekit-client in un solo chunk) | primo caricamento lento | code-splitting per tab |

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
| (questo commit) | Fix D2: `POST /api/agents/export` — il builder scrive su `agents.yaml` su richiesta |
