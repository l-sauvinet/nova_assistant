import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Sidebar } from "./Sidebar";

const today = new Date().toISOString();
const conversations = [
  { id: "a", title: "Recette de crêpes", created_at: today, updated_at: today },
  { id: "b", title: "Météo à Chambéry", created_at: today, updated_at: today },
];

const renderSidebar = (overrides = {}) => {
  const handlers = { onNew: vi.fn(), onOpen: vi.fn(), onRename: vi.fn(), onDelete: vi.fn(), onClose: vi.fn() };
  render(<Sidebar conversations={conversations} currentId="a" busy={false} {...handlers} {...overrides} />);
  return handlers;
};

describe("Sidebar", () => {
  it("lists conversations under their date group and marks the current one", () => {
    renderSidebar();
    expect(screen.getByText("Aujourd'hui")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recette de crêpes" })).toHaveAttribute("aria-current", "page");
  });

  it("opens a conversation and starts a new one", async () => {
    const handlers = renderSidebar();
    await userEvent.click(screen.getByRole("button", { name: "Météo à Chambéry" }));
    await userEvent.click(screen.getByRole("button", { name: /Nouvelle conversation/ }));
    expect(handlers.onOpen).toHaveBeenCalledWith("b");
    expect(handlers.onNew).toHaveBeenCalled();
  });

  it("renames inline", async () => {
    const handlers = renderSidebar();
    await userEvent.click(screen.getByRole("button", { name: "Renommer Météo à Chambéry" }));
    const input = screen.getByLabelText("Nouveau titre");
    await userEvent.clear(input);
    await userEvent.type(input, "Météo{Enter}");
    expect(handlers.onRename).toHaveBeenCalledWith("b", "Météo");
  });

  it("asks before deleting", async () => {
    const handlers = renderSidebar();
    await userEvent.click(screen.getByRole("button", { name: "Supprimer Météo à Chambéry" }));
    expect(handlers.onDelete).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Confirmer la suppression" }));
    expect(handlers.onDelete).toHaveBeenCalledWith("b");
  });

  it("searches by title", async () => {
    renderSidebar();
    await userEvent.type(screen.getByLabelText("Rechercher une conversation"), "crêpes");
    expect(screen.queryByText("Météo à Chambéry")).not.toBeInTheDocument();
    expect(screen.getByText("Recette de crêpes")).toBeInTheDocument();
  });

  it("invites to start when there is no conversation yet", () => {
    renderSidebar({ conversations: [], currentId: null });
    expect(screen.getByText("Tes conversations apparaîtront ici.")).toBeInTheDocument();
  });
});
