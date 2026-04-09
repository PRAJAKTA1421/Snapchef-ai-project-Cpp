function applyTheme(mode) {
  const body = document.body;
  if (mode === "light") {
    body.classList.add("light-mode");
  } else {
    body.classList.remove("light-mode");
  }

  const toggle = document.getElementById("theme-toggle");
  if (toggle) {
    toggle.textContent = mode === "light" ? "🌙 Dark" : "☀️ Light";
  }

  localStorage.setItem("snapchef_theme", mode);
}

function toggleTheme() {
  const current = localStorage.getItem("snapchef_theme") || "dark";
  applyTheme(current === "light" ? "dark" : "light");
}

function createQuickMenu() {
  const topRight = document.querySelector(".topbar .top-right");
  const menuButton = document.querySelector(".topbar .menu-toggle");
  if (!topRight || !menuButton) {
    return null;
  }

  let quickMenuWrap = menuButton.closest(".quick-menu-wrap");
  if (!quickMenuWrap) {
    quickMenuWrap = document.createElement("div");
    quickMenuWrap.className = "quick-menu-wrap";
    topRight.insertBefore(quickMenuWrap, menuButton);
    quickMenuWrap.appendChild(menuButton);
  }

  if (!quickMenuWrap.querySelector(".quick-menu-dropdown")) {
    quickMenuWrap.insertAdjacentHTML(
      "beforeend",
      `
    <div class="quick-menu-dropdown" aria-hidden="true">
      <button type="button" class="quick-menu-item" data-action="2fa">
        <span class="quick-menu-item-left">
          <i data-lucide="shield-check"></i>
          <span>2FA</span>
        </span>
        <span class="quick-menu-status" data-2fa-status>Off</span>
      </button>
      <button type="button" class="quick-menu-item" data-action="faq">
        <span class="quick-menu-item-left">
          <i data-lucide="circle-help"></i>
          <span>FAQ</span>
        </span>
      </button>
      <button type="button" class="quick-menu-item" data-action="rate">
        <span class="quick-menu-item-left">
          <i data-lucide="star"></i>
          <span>Rate this app</span>
        </span>
      </button>
    </div>
  `
    );
  }

  const modal = document.createElement("div");
  modal.className = "quick-modal";
  modal.setAttribute("aria-hidden", "true");
  modal.innerHTML = `
    <div class="quick-modal-backdrop" data-close-modal></div>
    <div class="quick-modal-card" role="dialog" aria-modal="true" aria-labelledby="quick-modal-title">
      <div class="quick-modal-header">
        <div>
          <h3 id="quick-modal-title">Quick Menu</h3>
          <p class="quick-modal-subtitle" id="quick-modal-subtitle"></p>
        </div>
        <button type="button" class="quick-modal-close" aria-label="Close" data-close-modal>
          <i data-lucide="x"></i>
        </button>
      </div>
      <div class="quick-modal-body"></div>
    </div>
  `;

  document.body.appendChild(modal);

  const dropdown = quickMenuWrap.querySelector(".quick-menu-dropdown");
  const twoFaBadge = quickMenuWrap.querySelector("[data-2fa-status]");
  const modalTitle = modal.querySelector("#quick-modal-title");
  const modalSubtitle = modal.querySelector("#quick-modal-subtitle");
  const modalBody = modal.querySelector(".quick-modal-body");

  const state = {
    twoFactorEnabled: localStorage.getItem("snapchef_2fa_enabled") === "true",
    rating: Number(localStorage.getItem("snapchef_app_rating") || 0),
  };

  function refreshBadges() {
    twoFaBadge.textContent = state.twoFactorEnabled ? "On" : "Off";
  }

  function closeDropdown() {
    dropdown.classList.remove("is-open");
    dropdown.setAttribute("aria-hidden", "true");
    menuButton.setAttribute("aria-expanded", "false");
  }

  function openDropdown() {
    dropdown.classList.add("is-open");
    dropdown.setAttribute("aria-hidden", "false");
    menuButton.setAttribute("aria-expanded", "true");
  }

  function closeModal() {
    modal.classList.remove("is-visible");
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("quick-modal-open");
    modalSubtitle.textContent = "";
    modalBody.innerHTML = "";
  }

  function openModal() {
    modal.classList.add("is-visible");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("quick-modal-open");
  }

  function setModalContent(title, subtitle, content) {
    modalTitle.textContent = title;
    modalSubtitle.textContent = subtitle;
    modalBody.innerHTML = content;
    openModal();
    if (window.lucide) {
      window.lucide.createIcons();
    }
  }

  async function saveTwoFactor(enabled) {
    const response = await fetch("/toggle_2fa", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ enabled }),
    });

    const data = await response.json();
    if (!response.ok || !data.success) {
      throw new Error(data.message || "Unable to update 2FA.");
    }

    state.twoFactorEnabled = Boolean(data.enabled);
    localStorage.setItem("snapchef_2fa_enabled", String(state.twoFactorEnabled));
    refreshBadges();
    return data.message;
  }

  async function saveRating(rating) {
    const response = await fetch("/rate_app", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ rating }),
    });

    const data = await response.json();
    if (!response.ok || !data.success) {
      throw new Error(data.message || "Unable to save rating.");
    }

    state.rating = Number(data.rating || rating);
    localStorage.setItem("snapchef_app_rating", String(state.rating));
    return data.message;
  }

  function showTwoFactorPanel() {
    setModalContent(
      "Two-factor authentication",
      "Add an extra confirmation step for sign-in.",
      `
        <div class="quick-panel">
          <div class="quick-setting-row">
            <div>
              <strong>Account protection</strong>
              <p>Require a second verification step when you log in.</p>
            </div>
            <label class="switch">
              <input type="checkbox" id="twofa-toggle" ${state.twoFactorEnabled ? "checked" : ""}>
              <span class="switch-slider"></span>
            </label>
          </div>
          <div class="quick-callout">
            <i data-lucide="badge-check"></i>
            <span>Recommended for accounts that store saved recipes and personal profile data.</span>
          </div>
          <p class="quick-feedback" id="twofa-feedback"></p>
        </div>
      `
    );

    const toggle = modalBody.querySelector("#twofa-toggle");
    const feedback = modalBody.querySelector("#twofa-feedback");
    toggle.addEventListener("change", async function () {
      feedback.textContent = "Saving...";
      try {
        feedback.textContent = await saveTwoFactor(toggle.checked);
      } catch (error) {
        toggle.checked = !toggle.checked;
        feedback.textContent = error.message;
      }
    });
  }

  function showFaqPanel() {
    setModalContent(
      "SnapChef FAQ",
      "Quick answers about scanning, recipes, and account settings.",
      `
        <div class="quick-faq-list">
          <div class="quick-faq-item">
            <strong>How does Scan Fridge work?</strong>
            <p>Upload a fridge photo and SnapChef extracts ingredients you can save and use in recipe suggestions.</p>
          </div>
          <div class="quick-faq-item">
            <strong>Where do saved recipes go?</strong>
            <p>Your saved dishes appear in Saved Recipes and also contribute to Cooking History insights.</p>
          </div>
          <div class="quick-faq-item">
            <strong>What does 2FA do?</strong>
            <p>It adds a second security step to your account settings so access is harder to misuse.</p>
          </div>
          <div class="quick-faq-item">
            <strong>Can I change diet preferences later?</strong>
            <p>Yes. Update your food preferences and allergies anytime from the Profile page.</p>
          </div>
        </div>
      `
    );
  }

  function renderStars(selectedRating) {
    return Array.from({ length: 5 }, function (_, index) {
      const value = index + 1;
      const activeClass = value <= selectedRating ? "is-active" : "";
      return `
        <button type="button" class="rating-star ${activeClass}" data-rating="${value}" aria-label="Rate ${value} out of 5">
          <i data-lucide="star"></i>
        </button>
      `;
    }).join("");
  }

  function bindRatingStars() {
    const submitButton = modalBody.querySelector("#rating-submit");
    const feedback = modalBody.querySelector("#rating-feedback");
    const starRow = modalBody.querySelector(".rating-stars");
    const ratingCaption = modalBody.querySelector(".rating-caption");
    let pendingRating = state.rating;

    starRow.querySelectorAll(".rating-star").forEach(function (button) {
      button.addEventListener("click", function () {
        pendingRating = Number(button.dataset.rating);
        starRow.querySelectorAll(".rating-star").forEach(function (star) {
          star.classList.toggle("is-active", Number(star.dataset.rating) <= pendingRating);
        });
        ratingCaption.textContent = `Selected rating: ${pendingRating}/5`;
        feedback.textContent = "";
      });
    });

    submitButton.addEventListener("click", async function () {
      if (!pendingRating) {
        feedback.textContent = "Please choose a rating first.";
        return;
      }

      feedback.textContent = "Saving your rating...";
      submitButton.disabled = true;

      try {
        const message = await saveRating(pendingRating);
        feedback.textContent = message;
        showRatePanel();
      } catch (error) {
        feedback.textContent = error.message;
      } finally {
        submitButton.disabled = false;
      }
    });
  }

  function showRatePanel() {
    setModalContent(
      "Rate this app",
      "Tell us how SnapChef is working for you.",
      `
        <div class="quick-panel">
          <div class="rating-stars">
            ${renderStars(state.rating)}
          </div>
          <p class="rating-caption">${
            state.rating ? `Your current rating: ${state.rating}/5` : "Choose a rating from 1 to 5."
          }</p>
          <button type="button" class="quick-action-btn" id="rating-submit">
            Submit Rating
          </button>
          <p class="quick-feedback" id="rating-feedback"></p>
        </div>
      `
    );
    bindRatingStars();
  }

  dropdown.addEventListener("click", function (event) {
    const menuItem = event.target.closest(".quick-menu-item");
    if (!menuItem) {
      return;
    }

    closeDropdown();

    if (menuItem.dataset.action === "2fa") {
      showTwoFactorPanel();
    }
    if (menuItem.dataset.action === "faq") {
      showFaqPanel();
    }
    if (menuItem.dataset.action === "rate") {
      showRatePanel();
    }
  });

  modal.addEventListener("click", function (event) {
    if (event.target.closest("[data-close-modal]")) {
      closeModal();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      closeDropdown();
      closeModal();
    }
  });

  document.addEventListener("click", function (event) {
    if (!quickMenuWrap.contains(event.target)) {
      closeDropdown();
    }
  });

  closeDropdown();
  closeModal();
  refreshBadges();

  if (window.lucide) {
    window.lucide.createIcons();
  }

  return {
    closeDropdown,
    closeModal,
    toggleDropdown: function () {
      if (dropdown.classList.contains("is-open")) {
        closeDropdown();
      } else {
        openDropdown();
      }
    },
  };
}

document.addEventListener("DOMContentLoaded", function () {
  const savedTheme = localStorage.getItem("snapchef_theme") || "dark";
  applyTheme(savedTheme);
  const quickMenu = createQuickMenu();

  const toggle = document.getElementById("theme-toggle");
  if (toggle) {
    toggle.addEventListener("click", toggleTheme);
  }

  const body = document.body;
  const sidebar = document.querySelector(".sidebar");
  const menuButton = document.querySelector(".topbar .menu-toggle");

  function closeSidebar() {
    body.classList.remove("sidebar-open");
    if (menuButton) {
      menuButton.setAttribute("aria-expanded", "false");
    }
  }

  function toggleSidebar() {
    const isOpen = body.classList.toggle("sidebar-open");
    if (menuButton) {
      menuButton.setAttribute("aria-expanded", String(isOpen));
    }
  }

  if (sidebar && menuButton) {
    menuButton.addEventListener("click", function (event) {
      event.stopPropagation();
      if (window.innerWidth <= 900) {
        toggleSidebar();
        if (quickMenu) {
          quickMenu.closeDropdown();
        }
      } else if (quickMenu) {
        body.classList.remove("sidebar-open");
        quickMenu.toggleDropdown();
      }
    });

    sidebar.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", closeSidebar);
    });

    document.addEventListener("click", function (event) {
      if (
        window.innerWidth > 900 ||
        !body.classList.contains("sidebar-open") ||
        sidebar.contains(event.target) ||
        menuButton.contains(event.target)
      ) {
        return;
      }

      closeSidebar();
    });

    window.addEventListener("resize", function () {
      if (window.innerWidth > 900) {
        closeSidebar();
      } else if (quickMenu) {
        quickMenu.closeDropdown();
      }
    });

    if (window.innerWidth > 900) {
      closeSidebar();
    }
  }
});
