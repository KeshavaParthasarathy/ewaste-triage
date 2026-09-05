(function (global) {
  "use strict";

  const SUPPORTED_MIME = new Set([
    "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"
  ]);
  const SUPPORTED_EXTENSION = /\.(?:jpe?g|png|webp|heic|heif)$/i;
  const LABELS = {
    "0301_computer_mouse": "Computer mouse",
    "0301_keyboard": "Keyboard",
    "0301_small_it": "Small IT device",
    "0303_laptop": "Laptop",
    "0306_mobile_phone": "Mobile phone",
    "0306_mobile_phones": "Mobile phone",
    "0401_headphones": "Headphones"
  };

  function isSupportedImage(file) {
    if (!file || !file.name) return false;
    return SUPPORTED_MIME.has(String(file.type || "").toLowerCase()) ||
      SUPPORTED_EXTENSION.test(file.name);
  }

  function formatCategory(className) {
    if (!className) return "Unknown category";
    if (LABELS[className]) return LABELS[className];
    const plain = String(className).replace(/^\d{4}_/, "").replace(/_/g, " ");
    return plain.charAt(0).toUpperCase() + plain.slice(1);
  }

  function percent(value) {
    const bounded = Math.max(0, Math.min(1, Number(value) || 0));
    return `${Math.round(bounded * 100)}%`;
  }

  function currency(value) {
    return new Intl.NumberFormat(undefined, {
      style: "currency", currency: "USD", maximumFractionDigits: 2
    }).format(Number(value) || 0);
  }

  async function responseJson(response) {
    let payload = {};
    try {
      payload = await response.json();
    } catch (_error) {
      payload = {};
    }
    if (!response.ok) {
      const error = new Error(payload.error || `Request failed (${response.status || "offline"})`);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function createController(options) {
    const view = options.view;
    const fetchImpl = options.fetchImpl;
    const formDataFactory = options.formDataFactory;
    const nextFrame = options.nextFrame;
    const objectUrl = options.objectUrl;
    let running = false;

    async function api(url, init) {
      return responseJson(await fetchImpl(url, init));
    }

    async function loadExplanation(scanId) {
      try {
        const result = await api(`/api/v1/explain/${encodeURIComponent(scanId)}`, {
          method: "POST"
        });
        view.renderInfluence(result);
      } catch (error) {
        view.renderInfluence({
          error: "Model influence is unavailable for this scan. The classification result is unchanged."
        });
      }
    }

    async function loadHistory() {
      try {
        const records = await api("/api/v1/history");
        view.renderHistory(Array.isArray(records) ? records : []);
        return records;
      } catch (error) {
        view.renderHistory([], error.message);
        return [];
      }
    }

    async function analyze(file) {
      if (running) return false;
      if (!isSupportedImage(file)) {
        view.transition("error", {
          message: "Choose a JPEG, PNG, HEIC, or WebP image and try again."
        });
        return false;
      }

      running = true;
      view.setBusy(true);
      try {
        view.transition("decoding", {file});
        view.showPreview(objectUrl(file));
        await nextFrame();

        const body = formDataFactory();
        body.append("image", file, file.name);
        const mass = typeof view.getMass === "function" ? view.getMass() : "";
        if (mass) body.append("mass_g", mass);

        view.transition("classifying", {file});
        const result = await api("/api/v1/classify", {method: "POST", body});
        view.transition(result.low_confidence ? "review" : "result", result);
        if (result.scan_id) void loadExplanation(result.scan_id);
        void loadHistory();
        return true;
      } catch (error) {
        view.transition("error", {message: error.message});
        return false;
      } finally {
        running = false;
        view.setBusy(false);
      }
    }

    async function deleteHistory(scanId) {
      view.markHistoryDeleting(scanId);
      try {
        await api(`/api/v1/history/${encodeURIComponent(scanId)}`, {method: "DELETE"});
      } finally {
        await loadHistory();
      }
    }

    async function clearHistory() {
      try {
        await api("/api/v1/history", {method: "DELETE"});
      } finally {
        await loadHistory();
      }
    }

    function reset() {
      view.transition("empty");
      if (typeof view.reset === "function") view.reset();
    }

    function openHistory(record) {
      const prediction = record.prediction || {};
      view.showSection("scan");
      view.transition(prediction.low_confidence ? "review" : "result", {
        ...prediction,
        scan_id: record.scan_id,
        from_history: true
      });
      view.renderInfluence({
        error: "Model influence is available only immediately after a new classification."
      });
    }

    return {
      analyze, clearHistory, deleteHistory, loadExplanation, loadHistory,
      openHistory, reset
    };
  }

  function element(document, tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function createDomView(document) {
    const html = document.documentElement;
    const stateFrame = document.getElementById("state-frame");
    const live = document.getElementById("live-status");
    const progressImage = document.getElementById("progress-image");
    const resultImage = document.getElementById("result-image");
    const progressPlaceholder = document.getElementById("preview-placeholder");
    const resultPlaceholder = document.getElementById("result-placeholder");
    const resultCategory = document.getElementById("result-category");
    const resultBadge = document.getElementById("result-badge");
    const scanSaved = document.getElementById("scan-saved");
    const confidenceNumber = document.getElementById("confidence-number");
    const confidenceBar = document.getElementById("confidence-bar");
    const alternativesList = document.getElementById("alternatives-list");
    const selectionNote = document.getElementById("selection-note");
    const influenceGrid = document.getElementById("influence-grid");
    const influenceCopy = document.getElementById("influence-copy");
    const influenceToggleRow = document.getElementById("influence-toggle-row");
    const influenceToggle = document.getElementById("influence-toggle");
    const imageStage = document.querySelector(".image-stage");
    const valuation = document.getElementById("valuation");
    const historyWarning = document.getElementById("history-warning");
    const historyList = document.getElementById("history-list");
    const historyEmpty = document.getElementById("history-empty");
    let previewUrl = "";
    let activeResult = null;

    function announce(message) {
      live.textContent = "";
      global.setTimeout(() => { live.textContent = message; }, 0);
    }

    function setBusy(value) {
      stateFrame.setAttribute("aria-busy", String(value));
      for (const control of document.querySelectorAll("[data-submit]")) {
        control.disabled = value;
      }
      document.getElementById("photo-input").disabled = value;
    }

    function showPreview(url) {
      previewUrl = url;
      for (const image of [progressImage, resultImage]) {
        image.src = url;
        image.hidden = false;
      }
      progressPlaceholder.hidden = true;
      resultPlaceholder.hidden = true;
    }

    function renderAlternatives(result) {
      alternativesList.replaceChildren();
      const candidates = (Array.isArray(result.topk) ? result.topk : [])
        .filter(item => item.class_name !== result.class_name)
        .slice(0, 3);
      if (!candidates.length) {
        alternativesList.append(element(document, "p", "selection-note", "No other category scored strongly enough to show."));
        return;
      }
      for (const item of candidates) {
        const button = element(document, "button", "alternative");
        button.type = "button";
        button.setAttribute("aria-pressed", "false");
        button.append(
          element(document, "strong", "", formatCategory(item.class_name)),
          element(document, "span", "", percent(item.confidence))
        );
        button.addEventListener("click", () => {
          for (const option of alternativesList.querySelectorAll(".alternative")) {
            option.setAttribute("aria-pressed", String(option === button));
          }
          resultCategory.textContent = formatCategory(item.class_name);
          selectionNote.hidden = false;
          announce(`${formatCategory(item.class_name)} selected for review.`);
        });
        alternativesList.append(button);
      }
    }

    function renderValuation(result) {
      if (!result.valuation) {
        valuation.hidden = true;
        return;
      }
      const value = result.valuation;
      valuation.hidden = false;
      document.getElementById("valuation-value").textContent = currency(value.value_usd);
      document.getElementById("valuation-range").textContent =
        `${currency(value.value_low)}–${currency(value.value_high)} range`;
      document.getElementById("valuation-detail").textContent =
        `${Number(value.mass_kg || 0).toFixed(3)} kg (${value.mass_source || "estimated"}) · prices ${value.prices_quoted_date || "bundled"}`;
    }

    function renderResult(result) {
      activeResult = result;
      resultCategory.textContent = formatCategory(result.class_name);
      resultBadge.textContent = result.low_confidence ? "Needs review" : "Classified";
      scanSaved.textContent = result.from_history ? "From history" :
        result.scan_id ? "Saved locally" : "Not saved";
      confidenceNumber.textContent = percent(result.confidence);
      confidenceBar.style.setProperty("--confidence", String(Math.max(0, Math.min(1, Number(result.confidence) || 0))));
      historyWarning.hidden = !result.history_error;
      historyWarning.textContent = result.history_error || "";
      selectionNote.hidden = true;
      influenceToggleRow.hidden = true;
      influenceToggle.checked = false;
      imageStage.dataset.influence = "false";
      influenceCopy.textContent = result.from_history ?
        "Model influence is available only immediately after a new classification." :
        result.scan_id ? "The optional model influence view is loading." :
          "This result was not saved, so model influence is unavailable.";
      renderAlternatives(result);
      renderValuation(result);
    }

    function transition(state, payload = {}) {
      html.dataset.state = state;
      if (state === "result" || state === "review") renderResult(payload);
      if (state === "error") {
        document.getElementById("error-message").textContent = payload.message ||
          "Choose a supported image and try again.";
      }
      const messages = {
        empty: "Ready for a device photo.",
        decoding: "Preparing the selected photo.",
        classifying: "Classifying the device locally.",
        result: `Classification complete: ${formatCategory(payload.class_name)}.`,
        review: "Classification complete with low confidence. Review the leading categories.",
        error: payload.message || "The scan could not be completed."
      };
      announce(messages[state] || "");
    }

    function renderInfluence(result) {
      influenceGrid.replaceChildren();
      if (result.error) {
        influenceToggleRow.hidden = true;
        influenceCopy.textContent = result.error;
        return;
      }
      const values = Array.isArray(result.values) ? result.values : [];
      influenceGrid.style.setProperty("--grid-size", String(result.grid_size || values.length || 7));
      for (const row of values) {
        for (const value of row) {
          const cell = element(document, "span", "influence-cell");
          cell.style.setProperty("--influence", String(Math.max(0, Math.min(0.72, Number(value) * 0.72))));
          influenceGrid.append(cell);
        }
      }
      influenceGrid.hidden = false;
      influenceToggleRow.hidden = false;
      influenceCopy.textContent = `${result.copy || "Regions that influenced this result."} The overlay does not detect components or indicate condition.`;
      announce("The optional model influence view is ready.");
    }

    function renderHistory(records, errorMessage) {
      historyList.replaceChildren();
      historyEmpty.hidden = records.length > 0;
      if (errorMessage) {
        historyEmpty.hidden = false;
        historyEmpty.querySelector("h2").textContent = "History is unavailable";
        historyEmpty.querySelector("p").textContent = errorMessage;
        return;
      }
      records.forEach((record, index) => {
        const prediction = record.prediction || {};
        const item = element(document, "li", "history-item");
        item.dataset.scanId = record.scan_id;
        item.style.animationDelay = `${Math.min(index * 35, 105)}ms`;
        item.append(element(document, "span", "history-glyph", "⌁"));
        const copy = element(document, "span", "history-copy");
        copy.append(
          element(document, "strong", "", formatCategory(prediction.class_name)),
          element(document, "small", "", `${percent(prediction.confidence)} confidence · ${new Date(record.created_at).toLocaleString()}`)
        );
        const review = element(document, "button", "history-action", "Review");
        review.type = "button";
        review.dataset.historyReview = record.scan_id;
        const remove = element(document, "button", "history-action delete", "Delete");
        remove.type = "button";
        remove.dataset.historyDelete = record.scan_id;
        item.append(copy, review, remove);
        item._record = record;
        historyList.append(item);
      });
    }

    function markHistoryDeleting(scanId) {
      const item = Array.from(historyList.children).find(node => node.dataset.scanId === scanId);
      if (item) item.dataset.deleting = "true";
      announce("Deleting scan from local history.");
    }

    function showSection(section) {
      const scan = section === "scan";
      document.getElementById("scan-view").hidden = !scan;
      document.getElementById("history-view").hidden = scan;
      for (const link of document.querySelectorAll("[data-view-link]")) {
        if (link.classList.contains("nav-item")) {
          const selected = link.dataset.viewLink === section;
          link.classList.toggle("is-selected", selected);
          if (selected) link.setAttribute("aria-current", "page");
          else link.removeAttribute("aria-current");
        }
      }
    }

    function reset() {
      document.getElementById("photo-input").value = "";
      if (previewUrl) global.URL.revokeObjectURL(previewUrl);
      previewUrl = "";
      activeResult = null;
      progressImage.hidden = true;
      resultImage.hidden = true;
      progressPlaceholder.hidden = false;
      resultPlaceholder.hidden = false;
      influenceGrid.replaceChildren();
      influenceGrid.hidden = true;
      document.getElementById("drop-target").focus();
    }

    influenceToggle.addEventListener("change", () => {
      imageStage.dataset.influence = String(influenceToggle.checked);
      announce(influenceToggle.checked ? "Model influence overlay shown." : "Model influence overlay hidden.");
    });

    return {
      getMass: () => "",
      markHistoryDeleting,
      renderHistory,
      renderInfluence,
      reset,
      setBusy,
      showPreview,
      showSection,
      transition,
      get activeResult() { return activeResult; }
    };
  }

  function bootstrap(document) {
    const view = createDomView(document);
    const controller = createController({
      view,
      fetchImpl: global.fetch.bind(global),
      formDataFactory: () => new global.FormData(),
      nextFrame: () => new Promise(resolve => global.requestAnimationFrame(() => resolve())),
      objectUrl: file => global.URL.createObjectURL(file)
    });
    const input = document.getElementById("photo-input");
    const dropTarget = document.getElementById("drop-target");

    input.addEventListener("change", () => {
      if (input.files && input.files[0]) void controller.analyze(input.files[0]);
    });

    dropTarget.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        input.click();
      }
    });

    let dragDepth = 0;
    document.addEventListener("dragenter", event => {
      if (!event.dataTransfer || !Array.from(event.dataTransfer.types || []).includes("Files")) return;
      event.preventDefault();
      dragDepth += 1;
      dropTarget.dataset.drag = "true";
    });
    document.addEventListener("dragover", event => {
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
      event.preventDefault();
    });
    document.addEventListener("dragleave", () => {
      dragDepth = Math.max(0, dragDepth - 1);
      if (!dragDepth) dropTarget.dataset.drag = "false";
    });
    document.addEventListener("drop", event => {
      event.preventDefault();
      dragDepth = 0;
      dropTarget.dataset.drag = "false";
      const file = event.dataTransfer && event.dataTransfer.files[0];
      if (file) void controller.analyze(file);
    });

    document.addEventListener("click", event => {
      const viewLink = event.target.closest("[data-view-link]");
      if (viewLink) {
        event.preventDefault();
        const section = viewLink.dataset.viewLink;
        view.showSection(section);
        if (section === "history") void controller.loadHistory();
      }
      const phoneAction = event.target.closest("[data-phone-action], #phone-capture");
      if (phoneAction) document.getElementById("phone-dialog").showModal();
      const close = event.target.closest("[data-close-dialog]");
      if (close) close.closest("dialog").close();
      const historyDelete = event.target.closest("[data-history-delete]");
      if (historyDelete) void controller.deleteHistory(historyDelete.dataset.historyDelete);
      const historyReview = event.target.closest("[data-history-review]");
      if (historyReview) {
        const item = historyReview.closest(".history-item");
        if (item && item._record) controller.openHistory(item._record);
      }
    });

    document.getElementById("analyze-another").addEventListener("click", () => controller.reset());
    document.getElementById("try-again").addEventListener("click", () => controller.reset());
    document.getElementById("open-assessment").addEventListener("click", () => {
      document.getElementById("assessment-dialog").showModal();
    });
    document.getElementById("clear-history").addEventListener("click", () => {
      if (global.confirm("Delete every locally saved scan? This cannot be undone.")) {
        void controller.clearHistory();
      }
    });

    void controller.loadHistory();
    return controller;
  }

  const exported = {bootstrap, createController, createDomView, formatCategory, isSupportedImage};
  if (typeof module !== "undefined" && module.exports) module.exports = exported;
  global.EWasteTriage = exported;
  if (global.document) {
    if (global.document.readyState === "loading") {
      global.document.addEventListener("DOMContentLoaded", () => bootstrap(global.document), {once: true});
    } else {
      bootstrap(global.document);
    }
  }
})(typeof window !== "undefined" ? window : globalThis);
