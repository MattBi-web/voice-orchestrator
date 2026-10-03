# Voice Orchestrator — Architecture Decision Doc

Ricerca + raccomandazione per il progetto "voice orchestrator" da portfolio: una famiglia di agenti
vocali (router + specialisti) costruita from scratch, latenza e routing come priorità assolute.

## TL;DR — cosa farei io

1. **Transport**: LiveKit (WebRTC) per il demo — niente numero di telefono, niente costi Twilio/Telnyx,
   basta il browser. Documento come si estende a PSTN reale (Telnyx/Twilio SIP trunk → LiveKit SIP) senza
   costruirlo davvero per il demo.
2. **STT**: Deepgram Nova-3. **TTS**: ElevenLabs Flash v2.5. È la coppia più matura e documentata, perfetta
   per un demo che deve sembrare production-grade.
3. **LLM di reasoning**: Gemini 3 Flash (o Flash-Lite) come default — sub-1s TTFT, ~6-10x più economico di
   GPT-5 mini, function-calling solido. GPT-4.1 mini/nano come seconda opzione intercambiabile (mostra che
   il sistema è provider-agnostic). **Niente speech-to-speech nativo** (OpenAI Realtime / Gemini Live) come
   pipeline principale — ti serve il controllo granulare su tool-calling e routing che solo una pipeline
   modulare STT→LLM→TTS ti dà. Posso aggiungerlo come "modalità 2" solo per mostrare che conosci anche
   quell'architettura.
4. **Routing tra agenti**: ibrido a due livelli, non uno dei tre che hai elencato da solo.
   - **Livello 1 — gate deterministico (zero costo LLM)**: condizioni booleane su variabili di stato
     (autenticato sì/no, intent già estratto, orario, lingua) decidono quali agenti sono *eleggibili*,
     in codice, non nel prompt. Questo è il confine di sicurezza/compliance che l'LLM non può scavalcare.
   - **Livello 2 — router leggero e rapido SOLO tra gli eleggibili**: un pattern-matcher/classificatore
     leggero (regex/keyword/embedding, non il modello di conversazione) decide nel caso comune; il modello
     di conversazione interviene solo per i casi ambigui. Questo è esattamente il pattern che un caso di
     studio pubblico ha misurato: p50 da 1.4s (router "LLM-first") a 620ms (router "pattern-first con
     fallback LLM").
   - Il modello "Calpurnia" (router leggero dedicato) e il modello Parloa (gate deterministico + LLM solo
     sugli eleggibili) non sono alternative — sono complementari, e li ho combinati qui.
5. **Markdown/RAG come knowledge, non come routing**: la tecnica "prompt injection di file markdown" (che
   pensavi fosse di Wonderful — non ho trovato conferme pubbliche, trattalo come non verificato) è in
   realtà RAG applicato alla conoscenza di un agente, non al routing. Usala per dare a ogni agente della
   famiglia accesso dinamico a documentazione/policy (esattamente la pipeline ibrida che hai già costruito
   in **Company Brain** — stesso dense+BM25+graph, chunking section-aware). Le condizioni di **ElevenLabs**
   (natural-language, valutate dall'LLM dell'agente attivo) sono un terzo meccanismo ancora diverso — buone
   per leggibilità/manutenibilità, costose in latenza perché il turno di generazione deve completarsi prima
   che il transfer scatti.
6. **Locale vs cloud**: cloud resta la scelta pragmatica per il demo principale. Un M4 Pro/Max (l'M5
   Pro/Max non è ancora uscito a inizio 2026 — solo l'M5 base sul MacBook Pro 14") puà realisticamente
   arrivare a 500ms-1.2s per turno in locale (Whisper/Parakeet MLX + Qwen3 8B + Kokoro TTS), competitivo
   con il cloud sulla carta. Ma: un Mac non gestisce bene più chiamate simultanee, i modelli piccoli
   ragionano peggio, Kokoro suona meno naturale di ElevenLabs, e la pipeline streaming richiede molto più
   lavoro di integrazione. Costruirei comunque una "modalità locale" come feature opzionale — è un'ottima
   storia di continuità con meeting-copilot (privacy-first, zero-dipendenza-cloud) — ma non come
   architettura primaria.
7. **Memoria durante la chiamata**: niente Redis per il demo. Un singolo processo con un oggetto di stato
   condiviso in memoria basta — router e specialisti sono funzioni/classi nello stesso processo, non
   microservizi separati. Redis entra in scena solo se la "famiglia" diventa più processi separati (allora
   serve un pub/sub per segnali di handoff) o se vuoi un livello esplicito di "session memory" con TTL.
   Per la visibilità: il router vede una **summary continua + le ultime 1-2 battute**, non il transcript
   intero (altrimenti ogni turno ripaghi in token e latenza la lunghezza crescente della chiamata). Ogni
   specialista riceve, all'handoff, un **pacchetto strutturato** (slot estratti + summary breve + ultime
   battute) — non tutto quello che ha visto il router. Per la memoria tra chiamate diverse (cliente che
   richiama): profilo utente + poche "memory facts" durevoli caricate all'inizio, scritte in modo
   asincrono a fine chiamata — mai il transcript grezzo.

---

## 1. Transport: Twilio vs Telnyx vs LiveKit

**Twilio Media Streams**: websocket bidirezionale audio mulaw 8kHz grezzo sulla chiamata — massima
flessibilità, ma gestisci tu VAD, turn-taking, barge-in. **Twilio ConversationRelay** (GA) è il layer
gestito sopra: STT/TTS gestiti da Twilio (Deepgram Flux), tu scrivi solo la logica LLM — latenza mediana
dichiarata <0.5s, p95 <0.725s.

**Telnyx**: stesso modello di Media Streaming, ma è un carrier che possiede la propria rete e GPU — testing
indipendente misura ~71ms p50 / ~118ms p95 sulla leg carrier, ~43ms più rapido di Twilio al p95. Ha anche
"LiveKit on Telnyx": LiveKit Agents eseguito co-locato sulla rete/GPU Telnyx, <200ms round-trip dichiarati
eliminando il salto di rete verso API esterne.

**LiveKit**: non è un carrier — è un SFU WebRTC open-source + framework di orchestrazione Agents. Per
prendere chiamate telefoniche serve un trunk SIP da un vero carrier (Twilio, Telnyx, Plivo, Sinch sono
tutti supportati ufficialmente): il carrier passa la chiamata a LiveKit come "SIP participant" in una
room, e gli Agents fanno STT→LLM→TTS su quell'audio.

Chi usa cosa in produzione: Vapi/Retell/Bland girano tutti su media-streaming stile Twilio/Telnyx con
orchestrazione propria — benchmark di terze parti (500 chiamate): Retell ~680ms mediana/920ms p95, Vapi
~720/1050ms, Bland ~850/1180ms. Un test a stack fisso (stesso GPT-4.1/Deepgram Nova-3/ElevenLabs Flash)
mette la pipeline di ElevenLabs stessa come più rapida (1.73s round-trip completo), poi Retell (1.96s).

**Per il demo**: LiveKit via browser (WebRTC puro, nessun numero di telefono) è la scelta più pratica —
zero costi carrier, zero complessità SIP, e LiveKit è comunque lo standard che tutte le piattaforme
serie (Vapi, Retell incluse nelle comparazioni) citano come riferimento. Se in futuro vuoi un vero numero
di telefono: Telnyx (o Twilio) solo come trunk SIP verso LiveKit.

## 2. STT + TTS

**STT** — Soniox: ~$0.12/h, WER 1.25%, 60+ lingue con traduzione/diarizzazione incluse, nessun numero di
latenza pubblicato. Deepgram Nova-3: ~$0.29-0.75/h, WER 1.71%, 10 lingue con code-switching, ma è il
default de facto nei framework voice-agent (Vapi, Retell, Pipecat, LiveKit) per la maturità di
endpointing/VAD — che è esattamente ciò che conta per il turn-taking.

**TTS** — numeri reali (non da vendor) a settembre 2026: ElevenLabs Flash v2.5 ~185ms mediana (molto
consistente), Cartesia Sonic 3.5 ~166-269ms (ma la versione 3.6 è *peggiorata* a 440ms — non dare per
scontato che "più nuovo" sia "più rapido"), Deepgram Aura-2 ~290ms (spread largo), PlayHT ~100ms solo
on-prem. OpenAI TTS è inadatto al realtime (~3.9s p95).

**Scelta**: Deepgram Nova-3 + ElevenLabs Flash v2.5 — combo più matura e documentata. Soniox + Cartesia
Sonic 3.5 come alternativa se conta più il costo/multilingua che l'ecosistema.

## 3. LLM di reasoning

Dati artificialanalysis.ai (ott. 2026): Gemini 3 Flash ~0.90s TTFT, ~187 tok/s, $0.435/M — il più
economico. GPT-5 mini con reasoning alto arriva a TTFT di 43s (!) perché genera token di reasoning prima
della risposta visibile — una trappola per il voice se non forzi `reasoning_effort: minimal`.

Le piattaforme reali (Vapi, Retell, Bland) nel 2026 **non** usano speech-to-speech nativo di default —
restano su pipeline modulare STT→LLM→TTS proprio per mantenere tool-calling e controllo del routing puliti
e debuggabili. Il costo è ~300-500ms in più end-to-end rispetto al nativo, ma è il prezzo del controllo.

**Scelta**: Gemini 3 Flash/Flash-Lite come default, GPT-4.1 mini/nano come provider intercambiabile
(mostra l'abstraction, stesso pattern di meeting-copilot). OpenAI Realtime API come "modalità 2"
opzionale, solo per dimostrare di conoscere anche l'architettura speech-to-speech nativa.

## 4. Routing multi-agente — il confronto che hai chiesto

| Pattern | Chi lo usa | Latenza aggiunta | Scala bene? |
|---|---|---|---|
| Router leggero dedicato (il tuo "Calpurnia") | pattern custom | bassa (decine di ms) ma è comunque una chiamata modello | media — serve ri-addestrare/aggiornare il classificatore |
| LLM decide via tool-call ("transfer") | ElevenLabs Workflows, LiveKit Agents, OpenAI Agents SDK/Swarm | alta — il turno di generazione deve completarsi | buona con pochi agenti, degrada con molti (prompt/tool bloat) |
| Condizioni deterministiche / state machine | Parloa (gate "Activation Restrictions"), Twilio ConversationRelay logic | bassissima — zero chiamata modello | ottima a scala, ma rigida su formulazioni impreviste |

**ElevenLabs Workflows** in dettaglio: nodi collegati da condizioni in linguaggio naturale valutate
dall'LLM dell'agente attivo + un tool di sistema `transfer_to_agent` con regole scritte in linguaggio
naturale ma applicate a discrezione dell'LLM. Il transcript completo persiste attraverso ogni hop (ogni
agente figlio eredita tutta la storia), il che è comodo ma pesa sui token/latenza con chiamate lunghe.

**Parloa** (il più rilevante per la tua domanda): due livelli — "Activation Restrictions" sono check
booleani su variabili di stato valutati in codice (es. `is_authenticated == true`) che escludono gli
agenti non eleggibili *prima* che un LLM li veda; solo tra gli eleggibili, l'LLM dell'agente attivo
sceglie con istruzioni brevi in linguaggio naturale. Risultato riportato: -24% nel tempo di risoluzione
chiamata, più percorsi di compliance verificabili staticamente (es. "nessun percorso da non-autenticato a
dati sensibili").

**Wonderful**: nessuna conferma pubblica sulla tecnica "markdown injection" — la fonte tecnica disponibile
(case study Google Cloud) dice che girano su Gemini + Vertex AI, usano Gemini anche come "AI-as-judge" per
affinare i prompt dopo ogni chiamata. Tratta l'idea del markdown-injection come un'ipotesi tua, non un
fatto confermato — ma resta una buona idea indipendentemente da chi la usa (vedi punto 5 sopra).

**Caso di studio pattern-first**: riprogettando un router da "LLM-first" (classificazione da sola:
600-1200ms, p50 totale ~1.4s) a "pattern/keyword-first con fallback LLM solo sui casi ambigui" (percorso
deterministico <8ms al p95), il p50 è sceso a ~620ms.

**La mia raccomandazione** combina tutto questo: gate deterministico (Parloa-style, sicurezza/compliance,
zero costo) → pattern-matcher leggero per il caso comune (stile Calpurnia, bassa latenza) → LLM della
conversazione per i soli casi ambigui (fallback, non default).

## 5. Pipeline locale su Apple Silicon — fattibile?

Verifica fattuale: l'M5 base è uscito nel MacBook Pro 14" a ottobre 2025; **M5 Pro/Max non erano ancora
usciti** a metà novembre 2025, previsti "inizio 2026"; M5 Ultra rinviato a metà/fine 2026 (Apple ha
saltato l'M4 Ultra). Quindi il top-spec davvero acquistabile a inizio 2026 potrebbe essere ancora un M4
Pro/Max, non un M5 Pro/Max — verifica lo stato di uscita prima di specificare l'hardware nel progetto.

- **STT locale**: Whisper (MLX)/Parakeet-MLX girano 7-55x più rapidi del realtime su audio già segmentato
  su M4 — ma serve comunque VAD/endpointing (~200-400ms) che questi benchmark non includono. Parakeet è
  più rapido ma tagliato per l'inglese; Whisper resta meglio per italiano/multilingua.
- **LLM locale**: Qwen3 8B (Q4) via MLX/Ollama su M4 Max: ~112 tok/s, TTFT ~170-290ms — competitivo col
  cloud sulla carta. Modelli 14B rischiano OOM sotto 48GB di memoria unificata. La concorrenza è il punto
  debole: throughput cala ~40% già a batch=2 — un Mac non serve bene più chiamate simultanee.
- **TTS locale**: Kokoro-82M via CoreML è il migliore — 12-79x il realtime, supporta l'italiano
  nativamente (voci Nicola/Sara). Opzioni più espressive (Orpheus-TTS, CSM) competono per memoria/GPU con
  l'LLM e aggiungono più latenza.
- **Verdetto**: un pipeline locale ben costruito può plausibilmente stare in 500ms-1.2s per turno su
  hardware M4 Pro/Max — competitivo con il cloud. Ma tre compromessi reali: qualità di reasoning inferiore
  (modelli 4-8B vs frontier cloud), Kokoro meno naturale di ElevenLabs, e un costo di engineering molto più
  alto per ottenere streaming incrementale vero (STT incrementale → LLM incrementale → TTS streaming) —
  lavoro che Twilio/cloud LLM/ElevenLabs già fanno per te. Per un demo portfolio da una persona, il cloud
  resta la scelta pragmatica; il locale è una storia di privacy/costo (coerente con meeting-copilot), non
  di latenza o qualità.

## 6. Memoria durante la chiamata

**In-call state**: per un agente a singolo processo, la memoria in-process (un oggetto chat-context) è lo
standard ed è sufficiente — nessun bisogno di uno store esterno. Redis entra in gioco specificamente in
architetture multi-processo che hanno bisogno di stato condiviso a bassa latenza o pub/sub tra processi
(es. segnali di handoff, lock per evitare che due agenti parlino sopra l'altro), o quando un vendor
costruisce un layer di "agent memory" gestito — Redis stesso modella due livelli: **session memory**
(transcript ordinato della chiamata corrente, scrittura sincrona) e **long-term memory** (fatti estratti
in background, scrittura asincrona che non blocca il turno live). LiveKit stesso usa Redis internamente
solo per il coordinamento multi-nodo del proprio server, non come store applicativo.

**Handoff tra router e specialisti**: il consenso (LiveKit, Vapi, i vendor di eval) è di NON rimandare
il transcript completo ogni turno. Pattern "supervisor": il router/orchestratore tiene il contesto
completo; gli specialisti delegati ricevono una copia **scoped**, non tutta la storia. Vapi Squads chiama
questo "context engineering" — limitare esplicitamente cosa attraversa il confine di handoff per
controllare token/latenza/"context poisoning", spesso via estrazione di variabili/summary piuttosto che
replay del transcript. Coval (che analizza i fallimenti di sistemi multi-agente voice in produzione)
raccomanda uno split di memoria gerarchico: info critica (identità, obiettivo) persiste per intero, info
di lavoro (task corrente) temporanea, info storica (small talk, problemi risolti) compressa o scartata.

**Memoria tra chiamate diverse**: profilo utente + poche "memory facts" durevoli caricate all'inizio
della chiamata, più un summary scritto in modo asincrono alla fine — non il transcript grezzo, e solo
cose che cambierebbero davvero una risposta futura.

**Raccomandazione per il tuo sistema**: stato in-process per il demo (niente Redis finché non hai
processi separati); router con summary continua + ultime 1-2 battute (non transcript intero); ogni
handoff porta un pacchetto strutturato (slot estratti + summary breve + ultime battute); tra chiamate,
un profilo utente leggero caricato all'inizio, scritto async a fine chiamata.

---

## Fonti principali

- Twilio ConversationRelay: twilio.com/en-us/products/conversational-ai/conversationrelay
- Telnyx latency comparison: telnyx.com/resources/voice-ai-agents-compared-latency
- LiveKit telephony docs: docs.livekit.io/telephony/
- LiveKit handoff pattern: livekit.com/blog/handoff-pattern-voice-agents
- Parloa multi-agent architecture: parloa.com/labs/insights/multi-agent-architecture-for-voice/
- Coval — perché i sistemi multi-agente voice falliscono: coval.ai/blog/why-multi-agent-voice-ai-systems-fail-7-common-pitfalls-and-how-to-avoid-them
- Redis Agent Memory: redis.io/docs/latest/develop/ai/context-engine/agent-memory/overview/
- Vapi Squads (context engineering): docs.vapi.ai/docs/squads
- TTS Latency Benchmark 2026: gradium.ai/content/tts-latency-benchmark-2026
- Qwen3 M4 Max throughput: markaicode.com/benchmarks/ollama-qwen-3-m4-max-throughput-benchmark/
- Kokoro CoreML benchmarks: huggingface.co/mattmireles/kokoro-coreml
- Case study pattern-first routing: craftedbydaniel.com/blog/my-voice-router-that-refuses-to-think-patternfirst-multiagent-orchestration-for-subsecond-latency
