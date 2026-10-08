import { describe, expect, it } from "vitest";
import { filterConversations, groupConversations } from "./conversationGroups";

const conversation = (id: string, updated_at: string, title = id) => ({ id, title, created_at: updated_at, updated_at });

describe("groupConversations", () => {
  it("groups by recency like the Claude app, most recent first", () => {
    const now = new Date(2026, 8, 29, 12);
    const groups = groupConversations(
      [
        conversation("old", new Date(2026, 5, 1).toISOString()),
        conversation("today", new Date(2026, 8, 29, 9).toISOString()),
        conversation("yesterday", new Date(2026, 8, 28, 20).toISOString()),
        conversation("week", new Date(2026, 8, 25).toISOString()),
        conversation("month", new Date(2026, 8, 10).toISOString()),
      ],
      now,
    );
    expect(groups.map((group) => [group.label, group.conversations.map((item) => item.id)])).toEqual([
      ["Aujourd'hui", ["today"]],
      ["Hier", ["yesterday"]],
      ["7 derniers jours", ["week"]],
      ["30 derniers jours", ["month"]],
      ["Plus ancien", ["old"]],
    ]);
  });

  it("filters by title, ignoring case", () => {
    const list = [conversation("a", "2026-09-29", "Recette de Crêpes"), conversation("b", "2026-09-29", "Météo")];
    expect(filterConversations(list, "crêpes").map((item) => item.id)).toEqual(["a"]);
    expect(filterConversations(list, "  ")).toHaveLength(2);
  });
});
