import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { MediaActions } from "../lib/mediaActions";
import type { MediaItem } from "../lib/useChat";
import { formatSize, MediaView } from "./MediaView";

const file = (overrides: Partial<MediaItem>): MediaItem => ({
  id: "m1", kind: "file", title: "Bonjour", path: "/w/NOVA/bonjour.pdf", file_name: "bonjour.pdf", size: 1843, url: "/media/m1",
  ...overrides,
});

const fakeActions = (download: MediaActions["download"] = async () => null): MediaActions => ({
  baseUrl: "http://127.0.0.1:9",
  open: vi.fn(async () => {}),
  download: vi.fn(download),
});

describe("MediaView", () => {
  it("shows a real preview of a PDF with its name, type and size", () => {
    render(<MediaView media={file({})} actions={fakeActions()} />);
    expect(screen.getByTitle("Bonjour")).toHaveAttribute("src", "http://127.0.0.1:9/media/m1");
    expect(screen.getByText("Document PDF · 2 Ko")).toBeInTheDocument();
  });

  it("has no inline preview for Word documents but can still open and download them", async () => {
    const actions = fakeActions(async () => "/home/alice/Téléchargements/cv.docx");
    const cv = file({ title: "CV", file_name: "cv.docx", path: "/w/NOVA/cv.docx" });
    render(<MediaView media={cv} actions={actions} />);
    expect(screen.queryByTitle("CV")).not.toBeInTheDocument();
    expect(screen.getByText(/Document Word/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Ouvrir" }));
    expect(actions.open).toHaveBeenCalledWith(cv);
    await userEvent.click(screen.getByRole("button", { name: "Télécharger" }));
    expect(actions.download).toHaveBeenCalledWith(cv);
    expect(await screen.findByRole("status")).toHaveTextContent("Enregistré : /home/alice/Téléchargements/cv.docx");
  });

  it("reports errors from actions", async () => {
    const actions = fakeActions();
    actions.open = vi.fn(async () => { throw new Error("Ce fichier n'existe plus."); });
    render(<MediaView media={file({})} actions={actions} />);
    await userEvent.click(screen.getByRole("button", { name: "Ouvrir" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Ce fichier n'existe plus.");
  });

  it("formats sizes in French", () => {
    expect(formatSize(512)).toBe("512 o");
    expect(formatSize(5 * 1024 * 1024 + 300000)).toBe("5,3 Mo");
  });
});
