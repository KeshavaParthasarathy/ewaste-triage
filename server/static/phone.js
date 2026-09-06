(() => {
  "use strict";

  const body = document.body;
  const token = body.dataset.token;
  const requireCode = body.dataset.requireCode === "true";
  const states = ["capture-state", "preview-state", "analyzing-state", "result-state", "expired-state"];
  const imageInput = document.getElementById("image-input");
  const pairingCodeGroup = document.getElementById("pairing-code-group");
  const pairingCode = document.getElementById("pairing-code");
  const preview = document.getElementById("photo-preview");
  const uploadForm = document.getElementById("upload-form");
  const chooseAnother = document.getElementById("choose-another-button");
  const retryButton = document.getElementById("retry-button");
  const errorMessage = document.getElementById("error-message");
  let previewUrl = null;
  let statusTimer = null;

  function showState(id) {
    states.forEach((stateId) => {
      document.getElementById(stateId).hidden = stateId !== id;
    });
    errorMessage.hidden = true;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function showError(message) {
    errorMessage.textContent = message;
    errorMessage.hidden = false;
  }

  function clearPreview() {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      previewUrl = null;
    }
    preview.removeAttribute("src");
    imageInput.value = "";
  }

  function resetCapture() {
    clearPreview();
    showState("capture-state");
  }

  function endSession() {
    if (statusTimer) {
      window.clearInterval(statusTimer);
      statusTimer = null;
    }
    clearPreview();
    showState("expired-state");
  }

  function enteredCode() {
    return pairingCode.value.replace(/\s/g, "");
  }

  function statusUrl() {
    const parameters = new URLSearchParams({ token });
    if (requireCode) parameters.set("code", enteredCode());
    return `/phone/status?${parameters.toString()}`;
  }

  async function checkStatus() {
    if (requireCode && enteredCode().length !== 6) return;
    try {
      const response = await fetch(statusUrl(), { cache: "no-store" });
      if (response.status === 404) endSession();
    } catch (_error) {
      // A transient local-network interruption does not prove that the session ended.
    }
  }

  function renderResult(prediction) {
    const confidence = Math.max(0, Math.min(1, Number(prediction.confidence) || 0));
    document.getElementById("result-label").textContent = String(prediction.label || "Unknown device").replaceAll("_", " ");
    document.getElementById("result-confidence").textContent = `${Math.round(confidence * 100)}%`;
    document.getElementById("confidence-fill").style.width = `${Math.round(confidence * 100)}%`;

    const alternatives = document.getElementById("alternatives");
    alternatives.replaceChildren();
    if (Array.isArray(prediction.alternatives) && prediction.alternatives.length) {
      const names = prediction.alternatives
        .slice(0, 2)
        .map((item) => String(item.label || "").replaceAll("_", " "))
        .filter(Boolean);
      if (names.length) alternatives.textContent = `Other possibilities: ${names.join(", ")}`;
    }
    showState("result-state");
  }

  pairingCodeGroup.hidden = !requireCode;

  imageInput.addEventListener("change", () => {
    const image = imageInput.files && imageInput.files[0];
    if (!image) return;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(image);
    preview.src = previewUrl;
    showState("preview-state");
  });

  uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const image = imageInput.files && imageInput.files[0];
    const code = enteredCode();
    if (!image) {
      resetCapture();
      return;
    }
    if (requireCode && !/^\d{6}$/.test(code)) {
      resetCapture();
      pairingCode.focus();
      showError("Enter the six-digit pairing code shown on your Mac.");
      return;
    }

    const formData = new FormData();
    formData.set("token", token);
    if (requireCode) formData.set("code", code);
    formData.set("image", image, image.name || "phone-capture.jpg");
    showState("analyzing-state");

    try {
      const response = await fetch("/phone/upload", { method: "POST", body: formData });
      if (response.status === 404) {
        endSession();
        return;
      }
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "The photo could not be analyzed.");
      renderResult(payload.prediction || {});
    } catch (error) {
      showState("preview-state");
      showError(error instanceof Error ? error.message : "The photo could not be analyzed. Try again.");
    }
  });

  chooseAnother.addEventListener("click", resetCapture);
  retryButton.addEventListener("click", resetCapture);
  pairingCode.addEventListener("input", () => {
    pairingCode.value = pairingCode.value.replace(/\D/g, "").slice(0, 6);
    if (pairingCode.value.length === 6) checkStatus();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") checkStatus();
  });

  statusTimer = window.setInterval(checkStatus, 15000);
  checkStatus();
})();
