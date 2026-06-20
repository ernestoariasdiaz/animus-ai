# ANIMUS v4.0

### Autonomous Network for Intelligence, Memory, and Understanding Systems

> \*\*Honest reconstruction of an autonomous knowledge system.\*\*  
> This version corrects metric inflation found in v3.0, documents a complete engine migration, and introduces a four-layer epistemic honesty architecture.

**Author:** Ernesto Antonio Arias Díaz — Independent Researcher, Santo Domingo, Dominican Republic  
**Paper (EN):** [Zenodo DOI: 10.5281/zenodo.18932137](https://doi.org/10.5281/zenodo.18932137)  
**Status:** Active — running autonomously on Dell Precision 7610, RTX 3050, Windows 11

\---

## What ANIMUS Is

ANIMUS is an autonomous knowledge system written in Rust that builds its own episodic memory graph through continuous unsupervised operation. It runs a local LLM (currently Gemma 4 E2B via llama.cpp), investigates knowledge gaps in its own graph, scrapes web sources, generates knowledge nodes, and produces business opportunity hypotheses — all without human intervention between cycles.

It is not a chatbot. It is not a RAG system. It is a loop that thinks, writes, and audits itself.

\---

## What Changed in v4.0 (Honest Changelog)

### The Graph Audit

v3.0 reported 824 unique deduplicated nodes. The actual graph had **1,892 nodes, of which 981 (52%) were duplicates**. The deduplication mechanism described in the v3.0 paper was not present in the production code path.

After audit: **911 verified unique nodes**.

Root causes:

* `agregar\_recuerdo()` had no label uniqueness guard — every call appended unconditionally
* Gap nodes were never weighted up after investigation — the same gaps were re-selected indefinitely (one topic investigated 65 times across sessions)

### Engine Migration History

|Version|Engine|Hardware|Speed|
|-|-|-|-|
|v2.0–v3.0|Llama 3.2 3B fine-tuned (QLoRA, loss 0.489)|CPU i5, no GPU|\~3.5 tok/s|
|v3.x|BitNet b1.58-2B-4T (i2\_s)|CPU i7, no GPU|\~19 tok/s|
|**v4.0**|**Gemma 4 E2B UD-Q4\_K\_XL**|**RTX 3050 4GB**|**\~77 tok/s**|

### Four-Layer Epistemic Honesty Architecture

Content cannot enter the graph unless it passes all four layers:

1. **Manual template without `<|think|>`** — Gemma 4's reasoning channel is never activated; the model responds directly without routing ambiguity
2. **Marker contract** — every response must contain `\[RESPUESTA]...\[/RESPUESTA]`; content outside is discarded
3. **`rfind()` extraction** — takes the *last* occurrence of the closing marker, immune to the model mentioning markers in its own reasoning
4. **Validation guard** — empty, short, or reasoning-contaminated responses return `Err()` and are never integrated

### Other Fixes

* Edge and provenance persistence: `load()` now deserializes edges and source URLs (previously silently discarded on every restart)
* UTF-8 sanitization: replaced allowlist (7 characters) with denylist (control chars only) — Gemma handles full UTF-8 without degradation
* HTTP client lifecycle: moved from per-call to per-`Brain` instance, eliminating the resource leak that caused \~8h freezes
* Gap weight increment: investigated gaps get `weight += 10.0`, preventing indefinite re-selection
* Uniqueness guard: `agregar\_recuerdo()` now rejects duplicate labels before writing

\---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  ANIMUS Autonomous Loop              │
│                                                     │
│  Priority 1: External tasks (tareas\_pendientes.txt) │
│  Priority 2: Gap investigation (episodic graph)     │
│  Priority 3: Web scraping (32-URL pool)             │
│                                                     │
│  Every 10 cycles: Synthesis (compress top-5 nodes)  │
│  Every 25 cycles: Value Cycle (business hypothesis) │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│              Four-Layer Honesty Filter              │
│  Template → Markers → rfind() → Validation Guard   │
└─────────────────┬───────────────────────────────────┘
                  │ passes all 4 layers
                  ▼
┌─────────────────────────────────────────────────────┐
│           Episodic Memory Graph (911 nodes)         │
│              animus\_memory.json                     │
│  Nodes: concepts | Edges: validated connections     │
│  Provenance: source URLs persisted across restarts  │
└─────────────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│         Gemma 4 E2B (llama.cpp, RTX 3050)           │
│   76.83 tok/s | Manual template | No thinking chan  │
└─────────────────────────────────────────────────────┘
```

\---

## Running ANIMUS

### Prerequisites

* Rust (stable, MSVC toolchain on Windows)
* Python 3.x with `scrapling\[fetchers]`
* llama.cpp build with CUDA (`llama-b\*\*\*\*-bin-win-cuda-\*.zip` + cudart zip)
* Gemma 4 E2B GGUF (`UD-Q4\_K\_XL` variant recommended for 4GB VRAM)

### Configuration

Edit the constants at the top of `src/brain.rs`:

```rust
const LLAMA\_SERVER\_PATH: \&str = r"C:\\path\\to\\llama-server.exe";
const MODEL\_PATH: \&str = r"C:\\path\\to\\gemma-4-E2B-it-UD-Q4\_K\_XL.gguf";
const SERVER\_URL: \&str = "http://127.0.0.1:8081";
```

### Build

```powershell
cargo build --release
```

### Usage

```powershell
# Single query (model answers, node integrated into graph)
.\\target\\release\\animus\_rust.exe --query "your question here"

# Autonomous loop (runs indefinitely, Ctrl+C to stop)
.\\target\\release\\animus\_rust.exe --autonomous

# Add external tasks while loop is running
Add-Content .\\tareas\_pendientes.txt "your task here"
```

> \*\*Important:\*\* Never run `--query` and `--autonomous` simultaneously against the same `animus\_memory.json`. Last writer wins — the other session's nodes will be lost. A file-lock mechanism is not yet implemented.

\---

## Value Cycle

Every 25 autonomous cycles, ANIMUS generates a business opportunity hypothesis using a structured `PROBLEM / EVIDENCE / FIRST STEP` format. Proposals are saved to `propuestas/valor\_<timestamp>.md` and never written to the main graph (to prevent speculation from contaminating knowledge).

The evidence clause requires proposals to cite web sources only — internal graph concepts are context, not evidence.

Seven proposals were generated during the June 2026 session. The most notable (proposals 6 and 7) converged on ISO 8583 message validation against AI confabulation risk in financial transaction systems — a domain matching the author's four years of production experience at CardNET (Dominican Republic's primary card payment processor), without being told about that background.

\---

## Behavioral Calibration Notes

Gemma 4 E2B behaves differently from prior engines. Four probes on June 12, 2026:

|Probe|Behavior|Status|
|-|-|-|
|Factual query without graph data|Explicit disclaimer + general knowledge labeled as such|✅ Correct|
|Factual query with confidence (BCRD/SB institutional roles)|Fluent but institutionally incorrect|⚠️ Elegant confabulation|
|Self-inventory (what does your memory contain?)|Described Gemma's training data, not the graph|⚠️ Identity bleed|
|Opinion/preference question|Refused citing honesty clause (over-rejection)|✅ Fixed — clause refined|

**Key finding:** Gemma 4 E2B confabulates with expert-level fluency. For regulatory or institutional facts, the system must operate in pure retrieval mode — summarizing provided documents, never generating from parametric memory.

\---

## Known Limitations

* **Semantic deduplication not implemented** — label-based dedup catches exact duplicates but not thematic paraphrases
* **Race condition on concurrent write** — `--query` and `--autonomous` must not run simultaneously
* **No multi-source validation** — each node enters after a single scraping cycle passing the four layers (the 30+ source threshold described in v3.0 is not implemented in this codebase)
* **Single hardware profile** — all measurements from Dell Precision 7610, i7-11800H, RTX 3050 4GB, Windows 11
* **Elegant confabulation** — Gemma 4 E2B confabulates fluently; domain-specific facts require retrieval mode

\---

## Repository Structure

```
animus-ai/
├── src/
│   ├── main.rs          # Autonomous loop, query mode, value cycle
│   ├── brain.rs         # LLM server management, generation, honesty layers
│   ├── memory.rs        # Graph structure, persistence, load/save
│   ├── hypothesis.rs    # Hypothesis forge (legacy, low activity)
│   ├── inspector.rs     # Graph inspection utilities
│   ├── scraper.rs       # Web scraping helpers
│   └── voz.rs           # Voice/wisdom mode
├── fetcher\_autonomo.py  # Web scraper (32-URL pool, scrapling)
├── Cargo.toml
└── README.md
```

Files **not** in the repository (personal/operational):

* `animus\_memory.json` — your graph (personal knowledge state)
* `propuestas/` — generated value proposals
* `autorretrato/` — cycle self-portraits
* `ciclos\_autonomos.txt`, `tareas\_pendientes.txt` — operational state

\---

## Version History

|Version|Date|Engine|Nodes (reported)|Nodes (verified)|
|-|-|-|-|-|
|v1.0|Feb 2026|Candle (Rust, float16)|154|—|
|v2.0|Feb–Mar 2026|Llama 3.2 3B fine-tuned|824|—|
|v3.0|Mar 2026|BitNet b1.58-2B-4T|824|—|
|v3.x|Mar–Jun 2026|BitNet b1.58-2B-4T|1,892|911 (audited)|
|**v4.0**|**Jun 2026**|**Gemma 4 E2B (GPU)**|**911**|**911**|

\---

## Citation

```bibtex
@misc{arias2026animus,
  title  = {ANIMUS v4.0: Honest Reconstruction of an Autonomous Knowledge System},
  author = {Arias D\\'iaz, Ernesto Antonio},
  year   = {2026},
  month  = {June},
  doi    = {10.5281/zenodo.18932137},
  url    = {https://doi.org/10.5281/zenodo.18932137}
}
```

\---



\## Support



If this project was useful to you, USDT donations (TRC20 network) are welcome:



`TBBpUCkhSc9EuverYayokZzWP2xLfCTx2R`



\---

*Built by one person, in one city, on consumer hardware.*  
*Santo Domingo, República Dominicana — June 2026*

