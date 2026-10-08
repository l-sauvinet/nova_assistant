import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { FileEntry, NovaApi } from "../../lib/api";
import type { MediaActions } from "../../lib/mediaActions";
import { FilePreviewPanel } from "./FilePreviewPanel";

const locked: FileEntry = {
  name: "Utilisateur", path: "/mnt/c/Users/Utilisateur", is_dir: true, size: null, modified: null, extension: "", hidden: false, readable: false,
};

const renderPanel = (requestAccess: () => Promise<unknown>) => {
  const api = { requestAccess: vi.fn(requestAccess), previewFile: vi.fn() } as unknown as NovaApi;
  const onOpenFolder = vi.fn();
  render(
    <FilePreviewPanel
      api={api} mediaActions={{} as MediaActions} entry={locked}
      onClose={vi.fn()} onOpenFolder={onOpenFolder} onAskNova={vi.fn()} onStartRename={vi.fn()} onTrash={vi.fn()}
    />,
  );
  return { api, onOpenFolder };
};

describe("FilePreviewPanel on a locked folder", () => {
  it("asks Windows for access and then opens the folder", async () => {
    const { api, onOpenFolder } = renderPanel(() => Promise.resolve({ entry: { ...locked, readable: true } }));
    await userEvent.click(screen.getByRole("button", { name: /Demander l'accès/ }));
    expect(api.requestAccess).toHaveBeenCalledWith(locked.path);
    expect(onOpenFolder).toHaveBeenCalledWith(locked.path);
  });

  it("explains a refusal and stays put", async () => {
    const { onOpenFolder } = renderPanel(() => Promise.reject(new Error("Accès non accordé : la fenêtre de Windows a été refusée.")));
    await userEvent.click(screen.getByRole("button", { name: /Demander l'accès/ }));
    expect(await screen.findByText(/Accès non accordé/)).toBeInTheDocument();
    expect(onOpenFolder).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /Demander l'accès/ })).toBeEnabled();
  });
});
