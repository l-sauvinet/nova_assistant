import { describe, expect, it } from "vitest";
import { describeTool } from "./toolLabels";

describe("describeTool", () => {
  it("never shows the raw command, only the plain-language explanation", () => {
    const script = "python3 << 'EOF'\nfrom reportlab.lib.pagesizes import A4\n...\nEOF";
    expect(describeTool("run_command", { command: script, explanation: "Créer le PDF du cours de droit pénal" })).toBe(
      "Créer le PDF du cours de droit pénal",
    );
    expect(describeTool("run_command", { command: script })).toBe("Action sur l'ordinateur");
  });

  it("shows short file names instead of full paths", () => {
    expect(describeTool("read_file", { path: "/mnt/c/Users/alice/Documents/cours.pdf" })).toBe("Lecture de cours.pdf");
    expect(describeTool("list_directory", { path: "C:\\Users\\alice\\Desktop\\" })).toBe("Ouverture du dossier Desktop");
    expect(describeTool("list_directory", {})).toBe("Ouverture du dossier de travail");
  });

  it("shows the site name for web pages", () => {
    expect(describeTool("fetch_page", { url: "https://www.meteofrance.com/previsions?x=1" })).toBe("Lecture de meteofrance.com");
    expect(describeTool("web_search", { query: "météo" })).toBe("Recherche sur internet : météo");
  });

  it("keeps labels short", () => {
    const label = describeTool("generate_image", { prompt: "a".repeat(300) });
    expect(label.length).toBeLessThanOrEqual(90);
    expect(label.endsWith("…")).toBe(true);
  });

  it("never exposes internal tool names", () => {
    expect(describeTool("send_mail", {})).toBe("Action en cours");
  });
});
