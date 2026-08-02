(() => {
  "use strict";

  const cards = Array.from(document.querySelectorAll("[data-field-path]"));
  const overlays = Array.from(document.querySelectorAll("[data-evidence-path]"));
  const pdfStage = document.querySelector("[data-pdf-stage]");
  const zoomIn = document.querySelector("[data-zoom-in]");
  const zoomOut = document.querySelector("[data-zoom-out]");
  const zoomValue = document.querySelector("[data-zoom-value]");
  const documentCard = document.querySelector("[data-document-card]");
  const fullscreenButton = document.querySelector("[data-fullscreen]");
  let pdfScale = 1;

  function activateField(path, scrollTarget) {
    cards.forEach((card) => {
      card.classList.toggle("is-active", card.dataset.fieldPath === path);
    });
    overlays.forEach((overlay) => {
      overlay.classList.toggle(
        "is-active",
        overlay.dataset.evidencePath === path,
      );
    });

    if (scrollTarget === "evidence") {
      const overlay = overlays.find((item) => item.dataset.evidencePath === path);
      overlay?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    if (scrollTarget === "field") {
      const card = cards.find((item) => item.dataset.fieldPath === path);
      card?.scrollIntoView({ behavior: "smooth", block: "center" });
      card?.focus({ preventScroll: true });
    }
  }

  cards.forEach((card) => {
    const path = card.dataset.fieldPath;
    card.addEventListener("click", () => activateField(path, "evidence"));
    card.addEventListener("focusin", () => activateField(path, "evidence"));
  });

  overlays.forEach((overlay) => {
    const path = overlay.dataset.evidencePath;
    overlay.addEventListener("click", (event) => {
      event.stopPropagation();
      activateField(path, "field");
    });
  });

  document.querySelectorAll('input[name^="mode::"]').forEach((radio) => {
    radio.addEventListener("change", updateRepairControls);
  });

  document.querySelectorAll('[name^="candidate::"]').forEach((candidate) => {
    candidate.addEventListener("change", () => {
      const path = candidate.name.slice("candidate::".length);
      const mode = document.querySelector(
        `input[name="mode::${CSS.escape(path)}"][value="candidate"]`,
      );
      if (mode) {
        mode.checked = true;
        updateRepairControls();
      }
    });
  });

  document.querySelectorAll("[data-manual-input]").forEach((input) => {
    input.addEventListener("focus", () => {
      const path = input.dataset.manualInput;
      const mode = document.querySelector(
        `input[name="mode::${CSS.escape(path)}"][value="manual"]`,
      );
      if (mode) {
        mode.checked = true;
        updateRepairControls();
      }
    });
  });

  function updateRepairControls() {
    cards.forEach((card) => {
      const selected = card.querySelector('input[name^="mode::"]:checked');
      const candidateList = card.querySelector("[data-candidate-controls]");
      const manualInput = card.querySelector("[data-manual-input]");

      candidateList?.classList.toggle(
        "is-selected-mode",
        selected?.value === "candidate",
      );
      manualInput?.classList.toggle(
        "is-selected-mode",
        selected?.value === "manual",
      );
    });
  }

  function renderZoom() {
    if (!pdfStage || !zoomValue) {
      return;
    }
    pdfStage.style.transform = `scale(${pdfScale})`;
    zoomValue.textContent = `${Math.round(pdfScale * 100)}%`;
    if (zoomOut) {
      zoomOut.disabled = pdfScale <= 0.75;
    }
    if (zoomIn) {
      zoomIn.disabled = pdfScale >= 1.5;
    }
  }

  zoomOut?.addEventListener("click", () => {
    pdfScale = Math.max(0.75, Number((pdfScale - 0.1).toFixed(2)));
    renderZoom();
  });

  zoomIn?.addEventListener("click", () => {
    pdfScale = Math.min(1.5, Number((pdfScale + 0.1).toFixed(2)));
    renderZoom();
  });


  fullscreenButton?.addEventListener("click", async () => {
    if (document.fullscreenElement) {
      await document.exitFullscreen?.();
      return;
    }
    await documentCard?.requestFullscreen?.();
  });

  document.addEventListener("fullscreenchange", () => {
    if (!fullscreenButton) {
      return;
    }
    fullscreenButton.setAttribute(
      "aria-label",
      document.fullscreenElement ? "Exit fullscreen" : "Enter fullscreen",
    );
  });

  updateRepairControls();
  renderZoom();
})();
