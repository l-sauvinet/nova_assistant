import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { FileEntry, NovaApi } from "../../lib/api";
import { FileList } from "./FileList";

const pdf: FileEntry = {
  name: "PPS 2026.pdf", path: "/docs/PPS 2026.pdf", is_dir: false, size: 1200, modified: null, extension: "pdf", hidden: false, readable: true,
};
const api = { thumbnailUrl: () => "" } as unknown as NovaApi;

const renderList = (overrides = {}) => {
  const handlers = { onSelect: vi.fn(), onActivate: vi.fn(), onStartRename: vi.fn(), onRename: vi.fn().mockResolvedValue(undefined), onCancelRename: vi.fn() };
  render(<FileList api={api} entries={[pdf]} view="grid" selectedPath={pdf.path} renamingPath={null} {...handlers} {...overrides} />);
  return handlers;
};

describe("FileList renaming", () => {
  it("edits the name in place on the tile, with the extension left out of the selection", async () => {
    const handlers = renderList({ renamingPath: pdf.path });
    const input = screen.getByRole("textbox", { name: /Nouveau nom/ }) as HTMLInputElement;
    expect(input).toHaveFocus();
    expect(input.value.slice(input.selectionStart ?? 0, input.selectionEnd ?? 0)).toBe("PPS 2026");
    await userEvent.keyboard("Bilan{Enter}");
    expect(handlers.onRename).toHaveBeenCalledWith(pdf, "Bilan.pdf");
  });

  it("cancels with Escape without renaming", async () => {
    const handlers = renderList({ renamingPath: pdf.path });
    await userEvent.keyboard("Autre{Escape}");
    expect(handlers.onCancelRename).toHaveBeenCalled();
    expect(handlers.onRename).not.toHaveBeenCalled();
  });

  it("starts renaming with F2", async () => {
    const handlers = renderList();
    screen.getByRole("button", { name: "PPS 2026.pdf" }).focus();
    await userEvent.keyboard("{F2}");
    expect(handlers.onStartRename).toHaveBeenCalledWith(pdf);
  });
});

describe("FileList locked folders", () => {
  it("marks a folder Windows refuses to open", () => {
    const locked = { ...pdf, name: "Utilisateur", path: "/mnt/c/Users/Utilisateur", is_dir: true, extension: "", readable: false };
    renderList({ entries: [locked] });
    expect(screen.getByLabelText("Accès refusé")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Utilisateur/ })).toHaveAttribute("title", "Utilisateur — accès refusé par Windows");
  });
});
