// Interruptor de tema. El atributo data-theme gana sobre la preferencia del
// sistema en ambas direcciones (ver styles.css).
(function () {
  var KEY = "tradingbot-theme";
  try {
    var saved = localStorage.getItem(KEY);
    if (saved) document.documentElement.setAttribute("data-theme", saved);
  } catch (e) { /* modo privado: se usa la preferencia del sistema */ }

  var btn = document.getElementById("theme-toggle");
  if (!btn) return;
  btn.addEventListener("click", function () {
    var isDark = document.documentElement.getAttribute("data-theme") === "dark"
      || (!document.documentElement.hasAttribute("data-theme")
          && window.matchMedia("(prefers-color-scheme: dark)").matches);
    var next = isDark ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem(KEY, next); } catch (e) { /* ignorado */ }
  });
})();
