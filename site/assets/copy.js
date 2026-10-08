// "Copy" buttons next to commands. Labels follow the page language.
const labels = document.documentElement.lang === "fr"
  ? { idle: "Copier", done: "Copié !", failed: "Sélectionne le texte" }
  : { idle: "Copy", done: "Copied!", failed: "Select the text" };

for (const button of document.querySelectorAll("[data-copy]")) {
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      button.textContent = labels.done;
    } catch {
      button.textContent = labels.failed;
    }
    setTimeout(() => (button.textContent = labels.idle), 2000);
  });
}
