/**
 * MPCWithGenerativeArt - Interactive Client Application
 */

const SAMPLE_DECK = `1 Byode, Inverse Sun (PH21) 3 # An anime girl dressed like a pixie
1 All-Seeing Toby (SLD) 2695 # An anime boy in a library holding a book
1 Animate Dead (SLD) 2189 # An old man in an anime style holding his hand up with a magic sphere surroundning him`;

// Application state
let currentCards = [];
let currentMode = "art";
let eventSource = null;
let debounceTimer = null;

document.addEventListener("DOMContentLoaded", () => {
  initUI();
  initEventSource();
  loadInitialCards();
  loadSettings();
  const deckInput = document.getElementById("deckInput");
  if (deckInput && deckInput.value.trim()) {
    validateDeckInput();
  }
});

function initUI() {
  const deckInput = document.getElementById("deckInput");
  const btnSample = document.getElementById("btnSample");
  const btnGenerate = document.getElementById("btnGenerate");
  const btnGenerateProxies = document.getElementById("btnGenerateProxies");
  const btnGenerateArtNav = document.getElementById("btnGenerateArtNav");
  const btnJustProxiesNav = document.getElementById("btnJustProxiesNav");
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const btnDone = document.getElementById("btnDone");
  const btnGridDone = document.getElementById("btnGridDone");
  const btnSettings = document.getElementById("btnSettings");

  // Tab key interceptor for deck textarea (inserts " # " prompt separator)
  deckInput.addEventListener("keydown", (e) => {
    if (e.key === "Tab") {
      e.preventDefault();
      const start = deckInput.selectionStart;
      const end = deckInput.selectionEnd;
      const insertText = " # ";
      deckInput.value = deckInput.value.substring(0, start) + insertText + deckInput.value.substring(end);
      deckInput.selectionStart = deckInput.selectionEnd = start + insertText.length;
      validateDeckInput();
    }
  });

  // Real-time syntax validation debounce
  let debounceTimer;
  deckInput.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(validateDeckInput, 300);
  });

  // Load sample deck
  btnSample.addEventListener("click", () => {
    deckInput.value = SAMPLE_DECK;
    validateDeckInput();
  });

  // Generate Art buttons
  if (btnGenerate) btnGenerate.addEventListener("click", handleGenerateDeck);
  if (btnGenerateArtNav) btnGenerateArtNav.addEventListener("click", handleGenerateDeck);

  // Just Proxies buttons
  if (btnGenerateProxies) btnGenerateProxies.addEventListener("click", handleGenerateProxies);
  if (btnJustProxiesNav) btnJustProxiesNav.addEventListener("click", handleGenerateProxies);

  // File Dropzone
  dropzone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
      handleFileUpload(e.target.files[0]);
    }
  });

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  });

  // "Ready for MPC" buttons
  if (btnDone) btnDone.addEventListener("click", openDoneModal);
  if (btnGridDone) btnGridDone.addEventListener("click", openDoneModal);

  // Settings button
  btnSettings.addEventListener("click", openSettingsModal);

  // Modal close handlers
  document.querySelectorAll(".close-modal").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".modal-backdrop").forEach((m) => m.classList.remove("active"));
    });
  });

  // MPC Upload trigger
  document.getElementById("btnStartMpcUpload").addEventListener("click", startMpcUpload);

  // Copy Snippet trigger
  document.getElementById("btnCopySnippet").addEventListener("click", copySnippetToClipboard);

  // Save settings
  document.getElementById("btnSaveSettings").addEventListener("click", saveSettings);
}

function initEventSource() {
  if (eventSource) {
    eventSource.close();
  }
  eventSource = new EventSource("/api/events");
  eventSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.type === "card_update") {
        updateCardInUI(data.card);
      } else if (data.type === "log") {
        console.log(`[SSE Log]`, data.message);
      }
    } catch (err) {
      // heartbeats or non-json
    }
  };
}

function setActionButtonsDisabled(disabled) {
  const btnGenerate = document.getElementById("btnGenerate");
  const btnGenerateProxies = document.getElementById("btnGenerateProxies");
  const btnGenerateArtNav = document.getElementById("btnGenerateArtNav");
  const btnJustProxiesNav = document.getElementById("btnJustProxiesNav");

  if (btnGenerate) btnGenerate.disabled = disabled;
  if (btnGenerateProxies) btnGenerateProxies.disabled = disabled;
  if (btnGenerateArtNav) btnGenerateArtNav.disabled = disabled;
  if (btnJustProxiesNav) btnJustProxiesNav.disabled = disabled;
}

async function validateDeckInput() {
  const text = document.getElementById("deckInput").value;
  const statusEl = document.getElementById("validationStatus");
  const errorContainer = document.getElementById("errorContainer");

  if (!text.trim()) {
    statusEl.innerHTML = `<span style="color: var(--text-muted)">Awaiting deck input...</span>`;
    errorContainer.style.display = "none";
    setActionButtonsDisabled(true);
    return false;
  }

  try {
    const res = await fetch("/api/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await res.json();

    if (data.valid) {
      statusEl.innerHTML = `<span class="validation-valid">✓ Format Valid (${data.cards.length} unique cards, ${data.total_copies} total copies ready)</span>`;
      errorContainer.style.display = "none";
      setActionButtonsDisabled(false);
      currentCards = data.cards;
      return true;
    } else {
      statusEl.innerHTML = `<span class="validation-invalid">⚠ Validation Errors Found (${data.errors.length})</span>`;
      errorContainer.style.display = "block";
      errorContainer.innerHTML = data.errors.map((e) => `<div>• ${escapeHtml(e)}</div>`).join("");
      setActionButtonsDisabled(true);
      return false;
    }
  } catch (err) {
    statusEl.innerHTML = `<span class="validation-invalid">Network error validating deck</span>`;
    return false;
  }
}

async function handleFileUpload(file) {
  const text = await file.text();
  document.getElementById("deckInput").value = text;
  validateDeckInput();
}

async function handleGenerateDeck() {
  const valid = await validateDeckInput();
  if (!valid || !currentCards || currentCards.length === 0) {
    alert("Please provide a valid deck list before generating art.");
    return;
  }

  currentMode = "art";
  const btnGenerate = document.getElementById("btnGenerate");
  const btnGenerateArtNav = document.getElementById("btnGenerateArtNav");
  setActionButtonsDisabled(true);
  if (btnGenerate) btnGenerate.innerHTML = `<span class="spinner"></span> Generating Art...`;
  if (btnGenerateArtNav) btnGenerateArtNav.innerHTML = `<span class="spinner"></span> Generating...`;

  currentCards.forEach((c) => {
    c.mode = "art";
    c.status = "generating";
    c.status_message = "Starting art generation...";
  });
  renderCardGrid();

  const gridSec = document.getElementById("gridSection");
  if (gridSec) {
    gridSec.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  try {
    const res = await fetch("/api/generate", { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      alert("Error starting art generation: " + (data.detail || JSON.stringify(data)));
      return;
    }
    console.log("Art generation started:", data);
  } catch (err) {
    alert("Error starting art generation: " + err.message);
  } finally {
    setActionButtonsDisabled(false);
    if (btnGenerate) btnGenerate.innerHTML = `🎨 Generate Art`;
    if (btnGenerateArtNav) btnGenerateArtNav.innerHTML = `🎨 Generate Art`;
  }
}

async function handleGenerateProxies() {
  const valid = await validateDeckInput();
  if (!valid || !currentCards || currentCards.length === 0) {
    alert("Please provide a valid deck list before generating proxies.");
    return;
  }

  currentMode = "proxy";
  const btnGenerateProxies = document.getElementById("btnGenerateProxies");
  const btnJustProxiesNav = document.getElementById("btnJustProxiesNav");
  setActionButtonsDisabled(true);
  if (btnGenerateProxies) btnGenerateProxies.innerHTML = `<span class="spinner"></span> Creating Proxies...`;
  if (btnJustProxiesNav) btnJustProxiesNav.innerHTML = `<span class="spinner"></span> Processing...`;

  currentCards.forEach((c) => {
    c.mode = "proxy";
    c.status = "fetching";
    c.status_message = "Retrieving card scan from Scryfall...";
  });
  renderCardGrid();

  const gridSec = document.getElementById("gridSection");
  if (gridSec) {
    gridSec.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  try {
    const res = await fetch("/api/generate-proxies", { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      alert("Error starting proxy generation: " + (data.detail || JSON.stringify(data)));
      return;
    }
    console.log("Proxy generation started:", data);
  } catch (err) {
    alert("Error starting proxy generation: " + err.message);
  } finally {
    setActionButtonsDisabled(false);
    if (btnGenerateProxies) btnGenerateProxies.innerHTML = `🎴 Just Proxies`;
    if (btnJustProxiesNav) btnJustProxiesNav.innerHTML = `🎴 Just Proxies`;
  }
}

async function loadInitialCards() {
  try {
    const res = await fetch("/api/cards");
    const data = await res.json();
    if (data.cards && data.cards.length > 0) {
      currentCards = data.cards;
      if (currentCards.some((c) => c.mode === "proxy")) {
        currentMode = "proxy";
      }
      renderCardGrid();
    }
  } catch (err) {
    console.error("Error loading cards:", err);
  }
}

function renderCardGrid() {
  const grid = document.getElementById("cardsGrid");
  const countEl = document.getElementById("cardCountLabel");
  const section = document.getElementById("gridSection");
  const gridTitle = document.getElementById("gridTitle");

  if (!currentCards || currentCards.length === 0) {
    section.style.display = "none";
    return;
  }

  section.style.display = "block";
  const isProxyMode = currentMode === "proxy" || currentCards.every((c) => c.mode === "proxy");
  if (gridTitle) {
    gridTitle.textContent = isProxyMode ? "🎴 Generated Proxies" : "🎨 Generated Cards";
  }

  const totalCopies = currentCards.reduce((sum, c) => sum + (c.copies || 1), 0);
  countEl.textContent = `${currentCards.length} Unique Cards (${totalCopies} Total Copies)`;

  grid.innerHTML = currentCards.map((card) => createCardElementHTML(card)).join("");

  // Attach event listeners for prompt regeneration and preview
  currentCards.forEach((card) => {
    const cardEl = document.getElementById(`card-elem-${card.id}`);
    if (!cardEl) return;

    const btnRegen = cardEl.querySelector(".btn-regen");
    const promptInput = cardEl.querySelector(".prompt-textarea");
    const previewContainer = cardEl.querySelector(".card-preview-container");

    if (btnRegen && promptInput) {
      btnRegen.addEventListener("click", () => {
        regenerateSingleCard(card.id, promptInput.value);
      });
    }

    if (previewContainer) {
      previewContainer.addEventListener("click", () => {
        openLightbox(card);
      });
    }
  });
}

function createCardElementHTML(card) {
  const isReady = card.status === "ready";
  const isProxyMode = card.mode === "proxy" || currentMode === "proxy";
  const imgSrc = isReady ? `/api/cards/${card.id}/thumb?t=${Date.now()}` : "";
  const placeholderText = card.status_message || (isReady ? "Card Rendered" : "Queued...");
  const showStatusMsg = !isReady && card.status_message && card.status_message.trim().length > 0;

  return `
    <div class="card-item" id="card-elem-${card.id}">
      <div class="card-preview-container" title="Click to view full 800 DPI preview">
        ${
          isReady
            ? `<img src="${imgSrc}" class="card-preview-img" alt="${escapeHtml(card.card_name)}" />`
            : `<div style="padding: 2rem; text-align: center; color: var(--text-muted); font-size: 0.85rem;">
                <div class="spinner" style="margin-bottom: 0.5rem;"></div>
                <div>${escapeHtml(placeholderText)}</div>
              </div>`
        }
        <span class="card-overlay-copies">${card.copies}x</span>
        <span class="card-overlay-badge">${escapeHtml(card.set_code)} #${escapeHtml(card.collector_number)}</span>
      </div>

      <div class="card-body">
        <div class="card-meta">
          <div class="card-title">${escapeHtml(card.card_name)}</div>
          <span class="card-status-badge status-${card.status}">${escapeHtml(card.status)}</span>
        </div>

        ${showStatusMsg ? `<div style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.5rem;">${escapeHtml(card.status_message)}</div>` : ""}

        ${
          !isProxyMode
            ? `<div>
                <label class="prompt-label">Generative Prompt:</label>
                <textarea class="prompt-textarea" rows="3">${escapeHtml(card.prompt)}</textarea>
              </div>

              <div class="card-actions">
                <button class="btn btn-secondary btn-sm btn-regen" ${card.status === "generating" || card.status === "compositing" ? "disabled" : ""}>
                  🔄 Regenerate
                </button>
              </div>`
            : ""
        }
      </div>
    </div>
  `;
}

function updateCardInUI(updatedCard) {
  const index = currentCards.findIndex((c) => c.id === updatedCard.id);
  if (index !== -1) {
    currentCards[index] = updatedCard;
  } else {
    currentCards.push(updatedCard);
  }

  const existingEl = document.getElementById(`card-elem-${updatedCard.id}`);
  if (existingEl) {
    const parent = existingEl.parentElement;
    const temp = document.createElement("div");
    temp.innerHTML = createCardElementHTML(updatedCard);
    const newEl = temp.firstElementChild;
    parent.replaceChild(newEl, existingEl);

    // Reattach listeners
    const btnRegen = newEl.querySelector(".btn-regen");
    const promptInput = newEl.querySelector(".prompt-textarea");
    const previewContainer = newEl.querySelector(".card-preview-container");

    if (btnRegen && promptInput) {
      btnRegen.addEventListener("click", () => regenerateSingleCard(updatedCard.id, promptInput.value));
    }
    if (previewContainer) {
      previewContainer.addEventListener("click", () => openLightbox(updatedCard));
    }
  } else {
    renderCardGrid();
  }
}

async function regenerateSingleCard(cardId, prompt) {
  const cardEl = document.getElementById(`card-elem-${cardId}`);
  const btnRegen = cardEl.querySelector(".btn-regen");
  btnRegen.disabled = true;
  btnRegen.innerHTML = `<span class="spinner"></span> Regenerating...`;

  try {
    const res = await fetch(`/api/cards/${cardId}/regenerate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    const data = await res.json();
    console.log("Regeneration triggered:", data);
  } catch (err) {
    alert("Error regenerating card: " + err.message);
  }
}

function openLightbox(card) {
  if (card.status !== "ready") return;
  const modal = document.getElementById("lightboxModal");
  const img = document.getElementById("lightboxImage");
  const caption = document.getElementById("lightboxCaption");

  img.src = `/api/cards/${card.id}/image?t=${Date.now()}`;
  caption.textContent = `${card.card_name} (${card.set_code} #${card.collector_number}) — 800 DPI MakePlayingCards Format`;
  modal.classList.add("active");
}

function openDoneModal() {
  const modal = document.getElementById("doneModal");
  const totalCopies = currentCards.reduce((sum, c) => sum + (c.copies || 1), 0);
  document.getElementById("modalTotalCards").textContent = `${totalCopies} Cards (${currentCards.length} Unique)`;
  
  // Calculate closest MPC bracket
  const brackets = [18, 36, 55, 72, 90, 108, 126, 144, 162, 180, 198, 216, 234, 396, 504, 612];
  let bracket = 612;
  for (let b of brackets) {
    if (totalCopies <= b) {
      bracket = b;
      break;
    }
  }
  document.getElementById("modalBracket").textContent = `${bracket} Cards Bracket`;

  // Dynamically configure Bookmarklet & Snippet
  const origin = window.location.origin;
  const bookmarkletBtn = document.getElementById("mpcBookmarklet");
  const snippetCode = document.getElementById("snippetCode");

  if (bookmarkletBtn) {
    bookmarkletBtn.href = `javascript:(function(){window.__MPC_SERVER_URL__='${origin}';var s=document.createElement('script');s.src='${origin}/api/mpc/injector.js?t='+Date.now();document.body.appendChild(s);})();`;
  }
  if (snippetCode) {
    snippetCode.textContent = `fetch('${origin}/api/mpc/injector.js').then(r=>r.text()).then(eval)`;
  }

  modal.classList.add("active");
}

async function copySnippetToClipboard() {
  const snippetCode = document.getElementById("snippetCode");
  const btn = document.getElementById("btnCopySnippet");
  if (!snippetCode || !btn) return;

  const textToCopy = snippetCode.textContent;
  try {
    await navigator.clipboard.writeText(textToCopy);
    const originalText = btn.textContent;
    btn.textContent = "✅ Copied!";
    btn.style.background = "var(--accent-success)";
    btn.style.borderColor = "var(--accent-success)";
    btn.style.color = "#fff";
    setTimeout(() => {
      btn.textContent = originalText;
      btn.style.background = "";
      btn.style.borderColor = "";
      btn.style.color = "";
    }, 2000);
  } catch (err) {
    alert("Copy failed: " + err.message);
  }
}

async function startMpcUpload() {
  const terminal = document.getElementById("mpcLogTerminal");
  const btn = document.getElementById("btnStartMpcUpload");
  terminal.style.display = "block";
  terminal.textContent = "Connecting to MakePlayingCards automation...\n";
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span> Uploading...`;

  try {
    const response = await fetch("/api/mpc/upload-stream", { method: "POST" });
    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      const text = decoder.decode(value);
      const lines = text.split("\n");
      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.substring(6));
            terminal.textContent += data.message + "\n";
            terminal.scrollTop = terminal.scrollHeight;
          } catch (e) {}
        }
      }
    }
  } catch (err) {
    terminal.textContent += `\n❌ Upload stream error: ${err.message}\n`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = `🚀 Upload to MakePlayingCards Order`;
  }
}

async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    const data = await res.json();
    if (data.provider) {
      document.getElementById("providerSelect").value = data.provider;
    }
    if (data.xai_api_key) {
      document.getElementById("xaiApiKey").value = data.xai_api_key;
    }
    if (data.hf_token) {
      document.getElementById("hfToken").value = data.hf_token;
    }
    if (data.gemini_api_key) {
      document.getElementById("geminiApiKey").value = data.gemini_api_key;
    }
    if (data.openai_api_key) {
      document.getElementById("openaiApiKey").value = data.openai_api_key;
    }
  } catch (e) {}
}

function openSettingsModal() {
  document.getElementById("settingsModal").classList.add("active");
}

async function saveSettings() {
  const provider = document.getElementById("providerSelect").value;
  const xai_api_key = document.getElementById("xaiApiKey").value;
  const hf_token = document.getElementById("hfToken").value;
  const gemini_api_key = document.getElementById("geminiApiKey").value;
  const openai_api_key = document.getElementById("openaiApiKey").value;

  try {
    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, xai_api_key, hf_token, gemini_api_key, openai_api_key }),
    });
    alert("Settings saved successfully!");
    document.getElementById("settingsModal").classList.remove("active");
  } catch (err) {
    alert("Failed to save settings: " + err.message);
  }
}


function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
