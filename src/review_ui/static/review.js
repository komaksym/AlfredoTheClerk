(() => {
  "use strict";

  const cards = Array.from(document.querySelectorAll("[data-field-path]"));
  const overlays = Array.from(document.querySelectorAll("[data-evidence-path]"));

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
      const path = card.dataset.fieldPath;
      const selected = card.querySelector('input[name^="mode::"]:checked');
      const candidateList = card.querySelector("[data-candidate-controls]");
      const candidateInputs = card.querySelectorAll('[name^="candidate::"]');
      const manualInput = card.querySelector("[data-manual-input]");
      const useCandidates = selected?.value === "candidate";
      const useManual = selected?.value === "manual";

      candidateList?.classList.toggle("is-disabled", !useCandidates);
      candidateInputs.forEach((input) => {
        if (!input.closest(".candidate-disabled")) {
          input.disabled = !useCandidates;
        }
      });
      if (manualInput) {
        manualInput.disabled = !useManual;
      }
    });
  }

  updateRepairControls();
})();
