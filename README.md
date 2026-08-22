# MPCWithGenerativeArt

Generate custom-appearing full-art decks of cards for [MakePlayingCards](https://www.makeplayingcards.com/) using modern AI image generators, high-resolution Scryfall card frames, and automated 800 DPI print-ready compositing.

---

## Features

- **Deck Parser & Global Prompts**: Supports standard MPC deck list formats with per-card prompts and `# global style prompt` prefixes.
- **Multi-Provider AI Image Generation**: Pluggable support for xAI Grok (`grok-imagine-image-2.0`), Google Gemini Imagen 3, OpenAI DALL-E 3, DeepSeek Janus-Pro-7B, Perchance AI (free, no API key), and algorithmic procedural fallback.
- **Card Frame & Bleed Compositing**: Automatically extracts Scryfall high-res frames, masks art windows, preserves card title/rules/stats/loyalty boxes, and scales to standard MPC 800 DPI bleed dimensions (822x1122 px).
- **Interactive UI**: Live real-time preview grid with Server-Sent Events (SSE) progress streaming, individual card prompt tweaking, and single-card regeneration.
- **MakePlayingCards Integration**: Export `cards.xml` and complete ZIP bundles, or use the built-in in-browser JavaScript injector script to automatically fill active MPC browser sessions.

---

## Quickstart

### Prerequisites
- Python 3.10+
- Playwright (optional, for Perchance browser generator): `playwright install chromium`

### Installation & Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (Optional) Install Playwright Chromium for Perchance AI generator
playwright install chromium

# 3. Create .env file (or copy from .env.example)
cp .env.example .env

# 4. Start the FastAPI server
uvicorn backend.app:app --reload --port 8000
```

Open your browser at `http://localhost:8000` to access the web application.

---

## Deck File Input Format

The application accepts deck lists with tab-separated prompts in this format:

```text
# [Optional global prompt/style applied to all cards]
Copies CardName (set) CollectorNumber\tprompt
```

### Example:
```text
# in watercolor studio ghibli fantasy anime style
1 Byode, Inverse Sun (PH21) 3	An anime girl dressed like a pixie
1 All-Seeing Toby (SLD) 2695	An anime boy in a library holding a book
2 Animate Dead (SLD) 2189	An old man in an anime style holding his hand up with a magic sphere
```

- **Copies**: Number of copies to print on MPC.
- **CardName**: Card name matching Scryfall.
- **(set)**: 3-4 letter MTG set code in parentheses.
- **CollectorNumber**: Card collector number.
- **prompt**: Prompt used for background art generation (separated by a Tab character `\t`).
- **Global Prompt (`# ...`)**: Optional style prefix placed at the top of the file applied to all generation requests.

---

## Environment Variables

All settings can be configured via environment variables or specified in a `.env` file located in the root directory.

### Quick Reference Table

| Variable | Default | Aliases / Alternatives | Description |
| :--- | :--- | :--- | :--- |
| `GENERATOR_PROVIDER` | `perchance` | `ART_GENERATOR`, `PROVIDER` | Active generative art backend (`grok`, `janus`, `gemini`, `openai`, `perchance`, `mock`). |
| `XAI_API_KEY` | *(empty)* | `GROK_API_KEY` | xAI API key for Grok Imagine 2.0 image generation. |
| `GEMINI_API_KEY` | *(empty)* | — | Google AI Studio API key for Imagen 3.0 image generation. |
| `OPENAI_API_KEY` | *(empty)* | — | OpenAI API key for DALL-E 3 image generation. |
| `HF_TOKEN` | *(empty)* | `HUGGINGFACE_TOKEN` | Hugging Face user access token for DeepSeek Janus-Pro-7B ZeroGPU Space. |
| `GENERATOR_TIMEOUT` | `300.0` | — | Overall HTTP client request timeout in seconds for AI generators (5 min). |
| `GENERATOR_READ_TIMEOUT` | `300.0` | — | HTTP socket read timeout in seconds waiting for generator responses. Defaults to `GENERATOR_TIMEOUT`. |
| `GENERATOR_CONNECT_TIMEOUT` | `60.0` | — | HTTP socket connection timeout in seconds when reaching generator APIs. |
| `GENERATOR_WRITE_TIMEOUT` | `60.0` | — | HTTP socket write timeout in seconds when transmitting request payloads. |
| `ENV_FILE` | `.env` | — | Path to `.env` file for runtime settings persistence. Set to `none`/`off` to disable writing to disk. |
| `TESTING` | `false` | — | When set to `true`, disables writing to `.env` during test execution. |

---

### Detailed Variable Descriptions

### 1. Generative Art Provider Selection
- **`GENERATOR_PROVIDER`** (aliases: `ART_GENERATOR`, `PROVIDER`):
  Specifies the active generative art provider. Supported values:
  - `grok` / `xai` / `grok-imagine-image-2.0`: xAI Grok Imagine 2.0.
  - `janus` / `janus-pro` / `deepseek`: DeepSeek Janus-Pro-7B via Hugging Face Spaces.
  - `gemini` / `imagen`: Google Gemini Imagen 3 (`imagen-3.0-generate-002`).
  - `openai` / `dall-e` / `dalle`: OpenAI DALL-E 3 (`dall-e-3`).
  - `perchance` / `perchance-ai`: Headless browser-based Perchance generator (free, no API key needed).
  - `mock` / `procedural`: Deterministic local procedural generator (no network calls, instant generation).

### 2. API Keys & Authentication
- **`XAI_API_KEY`** (alias: `GROK_API_KEY`):
  Your xAI API Key for calling `https://api.x.ai/v1/images/generations`.
- **`GEMINI_API_KEY`**:
  Your Google AI Studio API Key for Google Imagen 3 (`https://generativelanguage.googleapis.com`).
- **`OPENAI_API_KEY`**:
  Your OpenAI API Key for DALL-E 3 (`https://api.openai.com/v1/images/generations`).
- **`HF_TOKEN`** (alias: `HUGGINGFACE_TOKEN`):
  Hugging Face user token (`hf_...`) used to authorize and grant ZeroGPU priority when generating via `deepseek-ai/Janus-Pro-7B`.

### 3. Generator Timeout & Latency Controls
High-quality diffusion and multimodal models can experience high latency during peak usage. The following environment variables configure the HTTP connection and read thresholds:
- **`GENERATOR_TIMEOUT`**: Total request timeout across all phases in seconds (default: `300.0`).
- **`GENERATOR_READ_TIMEOUT`**: Maximum time in seconds to wait for image bytes or response payload from generator APIs (default: `300.0`).
- **`GENERATOR_CONNECT_TIMEOUT`**: Maximum time in seconds to establish network socket connection (default: `60.0`).
- **`GENERATOR_WRITE_TIMEOUT`**: Maximum time in seconds to write request body (default: `60.0`).

### 4. Configuration & Testing
- **`ENV_FILE`**:
  Specifies the destination path where UI settings updates submitted via `/api/settings` are persisted on disk. Defaults to `.env`. Set to `none`, `false`, `off`, or `disabled` to disallow persisting to disk.
- **`TESTING`**:
  Set to `true` to force automated testing mode, ensuring the local production `.env` is never modified by test suites.

---

### Example `.env` File

```env
# Active Generative Provider (grok, janus, gemini, openai, perchance, mock)
GENERATOR_PROVIDER=grok

# API Keys
XAI_API_KEY=xai-your-key-here
GEMINI_API_KEY=AIzaSyYourGeminiKeyHere
OPENAI_API_KEY=sk-proj-yourOpenAIKeyHere
HF_TOKEN=hf_yourHuggingFaceTokenHere

# Generator Timeouts (seconds)
GENERATOR_TIMEOUT=300.0
GENERATOR_READ_TIMEOUT=300.0
GENERATOR_CONNECT_TIMEOUT=60.0
GENERATOR_WRITE_TIMEOUT=60.0

# Settings persistence target
ENV_FILE=.env
```

---

## Running Tests

Run the full automated test suite using Python's built-in `unittest` runner:

```bash
# Run all unit and integration tests
python -m unittest tests/test_grok.py tests/test_janus.py tests/test_api.py tests/test_pipeline.py
```

---

## MakePlayingCards Upload & Export

Once your cards are generated, you can export or upload them using three methods:
1. **In-Browser Injector Script**: Copy the JavaScript snippet from the app (or navigate to `/api/mpc/injector.js`) and paste it into your browser's Developer Console on `makeplayingcards.com` to autofill the active order.
2. **Download `cards.xml`**: Download standard MPC Autofill XML formatted for compatibility with `mpc-autofill` desktop clients.
3. **Download ZIP Bundle**: Export an archive containing both `cards.xml` and all full-resolution 800 DPI print-ready card images.