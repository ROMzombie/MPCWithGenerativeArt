/**
 * MPC With Generative Art - In-Browser Session Injector
 * 
 * Injects generated card images from the local server (http://localhost:8000)
 * directly into your active MakePlayingCards designer tab.
 */

(async function () {
  const SERVER_URL = window.__MPC_SERVER_URL__ || "http://localhost:8000";

  // 1. Remove existing HUD if present
  const existingHud = document.getElementById("mpc-injector-hud");
  if (existingHud) {
    existingHud.remove();
  }

  // 2. Create Floating HUD Overlay
  const hud = document.createElement("div");
  hud.id = "mpc-injector-hud";
  hud.style.cssText = [
    "position: fixed",
    "top: 20px",
    "right: 20px",
    "width: 400px",
    "max-width: 90vw",
    "background: #111827",
    "color: #f3f4f6",
    "border: 2px solid #6366f1",
    "border-radius: 12px",
    "box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.7), 0 10px 10px -5px rgba(0, 0, 0, 0.5)",
    "z-index: 9999999",
    "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    "font-size: 14px",
    "line-height: 1.5",
    "padding: 16px",
    "transition: all 0.3s ease"
  ].join(";");

  hud.innerHTML = [
    '<div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; border-bottom: 1px solid #374151; padding-bottom: 8px;">',
      '<div style="font-weight: 700; font-size: 15px; display: flex; align-items: center; gap: 8px;">',
        '<span>🎴</span>',
        '<span style="background: linear-gradient(135deg, #818cf8, #c084fc); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">MPC Art Injector</span>',
      '</div>',
      '<button id="mpc-hud-close" style="background: none; border: none; color: #9ca3af; font-size: 18px; cursor: pointer; padding: 0 4px; line-height: 1;">&times;</button>',
    '</div>',
    '<div id="mpc-hud-status" style="margin-bottom: 10px; color: #d1d5db; font-size: 13px;">',
      'Initializing injector...',
    '</div>',
    '<div style="background: #374151; border-radius: 9999px; height: 8px; overflow: hidden; margin-bottom: 12px;">',
      '<div id="mpc-hud-bar" style="background: linear-gradient(90deg, #6366f1, #a855f7); width: 5%; height: 100%; transition: width 0.2s ease;"></div>',
    '</div>',
    '<div id="mpc-hud-details" style="font-size: 12px; color: #9ca3af; max-height: 120px; overflow-y: auto; background: #1f2937; padding: 8px; border-radius: 6px; border: 1px solid #374151;">',
      'Connecting to local server...',
    '</div>'
  ].join('');

  document.body.appendChild(hud);

  const statusEl = document.getElementById("mpc-hud-status");
  const barEl = document.getElementById("mpc-hud-bar");
  const detailsEl = document.getElementById("mpc-hud-details");
  const closeBtn = document.getElementById("mpc-hud-close");

  closeBtn.addEventListener("click", () => hud.remove());

  function setStatus(msg, progressPercent, detailLine) {
    if (statusEl) statusEl.innerHTML = msg;
    if (barEl && progressPercent !== undefined) barEl.style.width = Math.min(100, Math.max(0, progressPercent)) + "%";
    if (detailsEl && detailLine) {
      const line = document.createElement("div");
      line.textContent = detailLine;
      detailsEl.appendChild(line);
      detailsEl.scrollTop = detailsEl.scrollHeight;
    }
  }

  // 3. Validation: Check if running on MakePlayingCards
  if (!window.location.hostname.includes("makeplayingcards.com")) {
    setStatus(
      "⚠️ <strong>Wrong website!</strong>",
      100,
      "Please navigate to MakePlayingCards.com in this tab before running the injector."
    );
    return;
  }

  // 4. Check page state
  const isSetupPage = window.location.href.includes("custom-blank-card.html");
  const isInDesigner = (
    window.location.href.includes("dn_playingcards_front_dynamic.aspx") ||
    typeof oDesign !== "undefined"
  );

  // If user is on the custom blank card setup page, help them configure and enter the designer!
  if (isSetupPage) {
    setStatus("📡 Fetching deck info to configure MakePlayingCards...", 25, "Reading /api/cards...");
    try {
      const cardsResp = await fetch(SERVER_URL + "/api/cards", { mode: "cors" });
      const deckData = await cardsResp.json();
      const totalCopies = (deckData.cards || []).reduce((sum, c) => sum + (c.copies || 1), 0);

      const brackets = [18, 36, 55, 72, 90, 108, 126, 144, 162, 180, 198, 216, 234, 396, 504, 612];
      let bracket = 612;
      for (let b of brackets) {
        if (totalCopies <= b) {
          bracket = b;
          break;
        }
      }

      setStatus(
        "⚙️ Selecting <strong>" + bracket + " Cards Bracket</strong>...",
        60,
        "Selecting deck size (" + bracket + " cards) for " + totalCopies + " total cards."
      );

      const sizeSelect = document.getElementById("dro_choosesize");
      if (sizeSelect) {
        sizeSelect.value = String(bracket);
        sizeSelect.dispatchEvent(new Event("change", { bubbles: true }));
      }

      setStatus("🚀 Launching MakePlayingCards Card Designer...", 90, "Entering designer...");
      await new Promise((r) => setTimeout(r, 800));

      if (typeof doPersonalize === "function") {
        doPersonalize("https://www.makeplayingcards.com/products/pro_item_process_flow.aspx");
      } else {
        const startBtn = document.querySelector("a[href*='doPersonalize']");
        if (startBtn) startBtn.click();
      }
      return;
    } catch (e) {
      console.warn("[Injector Setup Page Notice]", e);
    }
  }

  if (!isInDesigner) {
    setStatus(
      "⚠️ <strong>Please enter the Card Designer!</strong>",
      50,
      "Go to the Custom Card Designer page on MakePlayingCards, then click the bookmarklet again."
    );
    return;
  }

  try {
    // 5. Fetch deck data from local server
    setStatus("📡 Fetching cards from MPCWithGenerativeArt...", 10, "Requesting /api/cards...");
    
    const cardsResp = await fetch(SERVER_URL + "/api/cards", { mode: "cors" });
    if (!cardsResp.ok) {
      throw new Error("Failed to fetch cards from " + SERVER_URL + " (Status: " + cardsResp.status + ")");
    }
    const deckData = await cardsResp.json();
    const cards = deckData.cards || [];

    if (cards.length === 0) {
      throw new Error("No cards found in your MPCWithGenerativeArt deck session. Please generate cards first!");
    }

    const totalCopies = cards.reduce((sum, c) => sum + (c.copies || 1), 0);
    setStatus("📦 Downloading " + cards.length + " card assets (" + totalCopies + " total copies)...", 20, "Found " + cards.length + " unique cards.");

    // 6. Download 800 DPI card images as Blobs and build File list
    const fileList = [];
    let downloadedCount = 0;

    for (let i = 0; i < cards.length; i++) {
      const card = cards[i];
      const imgUrl = SERVER_URL + "/api/cards/" + encodeURIComponent(card.id) + "/image";
      setStatus(
        "⬇️ Downloading card " + (i + 1) + "/" + cards.length + ": " + card.card_name + "...",
        20 + Math.floor((downloadedCount / cards.length) * 40),
        "Fetching 800 DPI image for " + card.card_name + "..."
      );

      const imgResp = await fetch(imgUrl, { mode: "cors" });
      if (!imgResp.ok) {
        throw new Error("Failed to download image for " + card.card_name);
      }

      const blob = await imgResp.blob();
      const cleanName = card.card_name.replace(/[^a-zA-Z0-9_-]/g, "_");

      // Expand copies into distinct file entries for MPC slot autofill
      for (let copyIdx = 0; copyIdx < (card.copies || 1); copyIdx++) {
        const fileName = cleanName + "_copy" + (copyIdx + 1) + ".png";
        const file = new File([blob], fileName, { type: "image/png", lastModified: Date.now() });
        fileList.push(file);
      }

      downloadedCount++;
    }

    setStatus("🚀 Uploading " + fileList.length + " cards to MakePlayingCards...", 65, "Dispatching files to MakePlayingCards uploader...");

    // 7. Hook into MakePlayingCards uploader and capture uploaded key list
    let capturedPhotoKeys = null;

    await new Promise((resolve, reject) => {
      // Option A: HTMLUploader global object
      if (typeof HTMLUploader !== "undefined" && typeof HTMLUploader.onUpload === "function") {
        setStatus("⬆️ MakePlayingCards upload in progress...", 75, "Uploading directly via MPC HTMLUploader...");

        // Hook upload completion callback
        HTMLUploader.dragUploadCallBack = function (keys) {
          if (keys) {
            capturedPhotoKeys = keys;
          }
          setStatus("✅ Upload completed on MakePlayingCards server!", 90, "MPC upload complete callback received.");
          resolve(true);
        };

        try {
          HTMLUploader.waitingCount = fileList.length;
          HTMLUploader.onUpload(0, fileList, function () {
            resolve(true);
          });
        } catch (e) {
          console.warn("[Injector] HTMLUploader.onUpload direct failed, falling back to input dispatch", e);
          fallbackDispatch();
        }
      } else {
        fallbackDispatch();
      }

      function fallbackDispatch() {
        // Option B: File Input element
        const fileInput = document.getElementById("uploadId") || document.querySelector("input[type='file']");
        if (fileInput) {
          setStatus("⬆️ Dispatching file uploads to MPC input...", 80, "Found upload element. Assigning DataTransfer...");
          const dataTransfer = new DataTransfer();
          fileList.forEach((f) => dataTransfer.items.add(f));
          fileInput.files = dataTransfer.files;
          fileInput.dispatchEvent(new Event("change", { bubbles: true }));
          setTimeout(() => resolve(true), 4000);
        } else {
          reject(new Error("Could not find MakePlayingCards upload handler on this page."));
        }
      }
    });

    // 8. Auto-fill slots starting from the next open space in the order
    setStatus("🪄 Assigning card images to the next open slots in the order...", 92, "Executing oDesign.setAutoFill()...");
    await new Promise((r) => setTimeout(r, 1500));

    // Try reading hidd_image_list if capturedPhotoKeys was not set
    if (!capturedPhotoKeys) {
      try {
        const hiddImg = document.getElementById("hidd_image_list") ||
          (oDesign && oDesign.DesignFrame && oDesign.DesignFrame.contentWindow && oDesign.DesignFrame.contentWindow.document.getElementById("hidd_image_list"));
        if (hiddImg && hiddImg.value) {
          capturedPhotoKeys = hiddImg.value;
        }
      } catch (err) {}
    }

    if (typeof oDesign !== "undefined") {
      try {
        if (typeof oDesign.setAutoFill === "function") {
          oDesign.setAutoFill(capturedPhotoKeys || "");
        }
        setStatus("💾 Saving project to your MakePlayingCards account...", 96, "Calling oDesign.setTemporarySave()...");
        if (typeof oDesign.setTemporarySave === "function") {
          oDesign.setTemporarySave();
        }
      } catch (err) {
        console.warn("[Injector] Autofill notice:", err);
      }
    }

    // 9. Complete!
    setStatus(
      "🎉 <strong style='color: #4ade80;'>Deck Successfully Injected!</strong>",
      100,
      "✅ All " + fileList.length + " card images have been uploaded and placed into the open spaces of your MakePlayingCards order!"
    );

    // Turn bar green
    if (barEl) {
      barEl.style.background = "linear-gradient(90deg, #10b981, #34d399)";
    }
  } catch (error) {
    console.error("[MPC Injector Error]", error);
    setStatus(
      "❌ <strong style='color: #f87171;'>Injection Error</strong>",
      100,
      "Error: " + error.message
    );
  }
})();
