import { describe, expect, it } from "vitest";
import { applyServerEvent, initialChatState, type ChatState } from "./useChat";

const run = (...events: Parameters<typeof applyServerEvent>[1][]): ChatState =>
  events.reduce(applyServerEvent, initialChatState);

describe("applyServerEvent", () => {
  it("shows the answer and stops the thinking indicator", () => {
    const state = run({ type: "thinking" }, { type: "assistant_message", text: "Bonjour" });
    expect(state.busy).toBe(false);
    expect(state.items).toMatchObject([{ kind: "assistant", text: "Bonjour" }]);
  });

  it("tracks a tool from start to finish", () => {
    const state = run(
      { type: "tool_started", id: "c1", name: "read_file", arguments: { path: "a.txt" } },
      { type: "tool_finished", id: "c1", name: "read_file", is_error: false },
    );
    expect(state.items).toMatchObject([{ kind: "tool", label: "Lecture de a.txt", status: "done" }]);
  });

  it("keeps the security warning of content that looked hostile, and of a confirmation", () => {
    const state = run(
      { type: "tool_started", id: "c1", name: "fetch_page", arguments: { url: "https://x.example" } },
      { type: "tool_finished", id: "c1", name: "fetch_page", is_error: false, warning: "⚠️ la page contient ..." },
      { type: "confirmation_request", id: "q1", question: "Supprimer ?", warning: "NOVA vient de lire ..." },
    );
    expect(state.items[0]).toMatchObject({ warning: "⚠️ la page contient ..." });
    expect(state.confirmation).toMatchObject({ warning: "NOVA vient de lire ..." });
  });

  it("marks failed tools", () => {
    const state = run(
      { type: "tool_started", id: "c1", name: "delete_path", arguments: { path: "x" } },
      { type: "tool_finished", id: "c1", name: "delete_path", is_error: true },
    );
    expect(state.items[0]).toMatchObject({ status: "error" });
  });

  it("opens a confirmation and an error closes it", () => {
    const asking = run({ type: "confirmation_request", id: "q1", question: "Supprimer ?" });
    expect(asking.confirmation).toEqual({ id: "q1", question: "Supprimer ?" });
    const failed = applyServerEvent(asking, { type: "error", message: "Oups" });
    expect(failed.confirmation).toBeNull();
    expect(failed.items).toMatchObject([{ kind: "error", text: "Oups" }]);
  });

  it("reset clears the conversation", () => {
    const state = run({ type: "assistant_message", text: "x" }, { type: "reset_done" });
    expect(state).toEqual(initialChatState);
  });
});

describe("media", () => {
  it("attaches generated media to the finished tool", () => {
    const media = [{ id: "x", kind: "image" as const, title: "chalet", path: "/w/c.jpg", file_name: "c.jpg", size: 1, url: "/media/x" }];
    const state = run(
      { type: "tool_started", id: "c1", name: "generate_image", arguments: { prompt: "chalet" } },
      { type: "tool_finished", id: "c1", name: "generate_image", is_error: false, media },
    );
    expect(state.items[0]).toMatchObject({ label: "Création d'une image : chalet", media });
  });
});

describe("itemsFromHistory", () => {
  it("rebuilds chat items with friendly tool labels", async () => {
    const { itemsFromHistory } = await import("./useChat");
    const items = itemsFromHistory([
      { kind: "user", text: "Lis ma note" },
      { kind: "tool", id: "c1", name: "read_file", arguments: { path: "/w/note.txt" }, status: "done", media: [] },
      { kind: "assistant", text: "Rendez-vous à 14h." },
    ]);
    expect(items).toMatchObject([
      { kind: "user", text: "Lis ma note" },
      { kind: "tool", id: "c1", label: "Lecture de note.txt", status: "done" },
      { kind: "assistant", text: "Rendez-vous à 14h." },
    ]);
  });
});
