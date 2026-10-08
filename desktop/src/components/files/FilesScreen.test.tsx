import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { FileEntry, NovaApi } from "../../lib/api";
import type { MediaActions } from "../../lib/mediaActions";
import { FilesScreen } from "./FilesScreen";

const folder: FileEntry = { name: "Photos", path: "/home/Photos", is_dir: true, size: null, modified: null, extension: "", hidden: false, readable: true };

const api = {
  places: vi.fn().mockResolvedValue({ places: [{ label: "Accueil", path: "/home", icon: "home", group: "Ce PC" }] }),
  listFolder: vi.fn().mockResolvedValue({ path: "/home", name: "home", parent: "/", entries: [folder], truncated: false }),
  thumbnailUrl: () => "",
} as unknown as NovaApi;

describe("FilesScreen preview pane", () => {
  it("keeps its place before and after a click so the grid never shifts under a double-click", async () => {
    render(<FilesScreen api={api} mediaActions={{} as MediaActions} onAskNova={vi.fn()} />);
    expect(screen.getByRole("complementary", { name: "Aperçu" })).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Photos" }));
    expect(screen.getByRole("complementary", { name: "Aperçu de Photos" })).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Aperçu" })).not.toBeInTheDocument();
  });

  it("can be hidden", async () => {
    render(<FilesScreen api={api} mediaActions={{} as MediaActions} onAskNova={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Masquer le volet d'aperçu" }));
    await userEvent.click(await screen.findByRole("button", { name: "Photos" }));
    expect(screen.queryByRole("complementary", { name: /Aperçu/ })).not.toBeInTheDocument();
  });
});
