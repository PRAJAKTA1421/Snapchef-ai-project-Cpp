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

document.addEventListener("DOMContentLoaded", function () {
  const savedTheme = localStorage.getItem("snapchef_theme") || "dark";
  applyTheme(savedTheme);

  const toggle = document.getElementById("theme-toggle");
  if (toggle) {
    toggle.addEventListener("click", toggleTheme);
  }
});
