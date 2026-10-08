import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ChatScreen } from "./ChatScreen";
import type { MediaActions } from "../lib/mediaActions";

const { openExternal } = vi.hoisted(() => ({ openExternal: vi.fn(async (_url: string) => {}) }));
vi.mock("../lib/openExternal", () => ({ openExternal }));

const actions: MediaActions = { baseUrl: "http://127.0.0.1:9", open: async () => {}, download: async () => null };
const upload = vi.fn(async (file: File) => ({
  upload_id: `up-${file.name}`,
  attachment: { id: "m", kind: "file" as const, title: file.name, path: `/u/${file.name}`, file_name: file.name, size: file.size, url: "/media/m" },
}));

describe("ChatScreen", () => {
  it("sends with Enter and clears the box", async () => {
    const onSend = vi.fn();
    render(<ChatScreen items={[]} busy={false} connected mediaActions={actions} onSend={onSend} onUpload={upload} />);
    const box = screen.getByLabelText("Message pour NOVA");
    await userEvent.type(box, "Salut{Enter}");
    expect(onSend).toHaveBeenCalledWith("Salut", []);
    expect(box).toHaveValue("");
  });

  it("Shift+Enter adds a new line instead of sending", async () => {
    const onSend = vi.fn();
    render(<ChatScreen items={[]} busy={false} connected mediaActions={actions} onSend={onSend} onUpload={upload} />);
    await userEvent.type(screen.getByLabelText("Message pour NOVA"), "a{Shift>}{Enter}{/Shift}b");
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Message pour NOVA")).toHaveValue("a\nb");
  });

  it("does not send while NOVA is busy", async () => {
    const onSend = vi.fn();
    render(<ChatScreen items={[]} busy connected mediaActions={actions} onSend={onSend} onUpload={upload} />);
    await userEvent.type(screen.getByLabelText("Message pour NOVA"), "Salut{Enter}");
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByText("NOVA réfléchit…")).toBeInTheDocument();
  });

  it("renders markdown answers and tool activity", () => {
    render(
      <ChatScreen
        busy={false}
        connected
        mediaActions={actions}
        onSend={() => {}}
        onUpload={upload}
        items={[
          { kind: "tool", id: "t", label: "Lecture de a.txt", status: "done" },
          { kind: "assistant", id: "a", text: "Il fait **20°C**" },
        ]}
      />,
    );
    expect(screen.getByText("Lecture de a.txt")).toBeInTheDocument();
    expect(screen.getByText("20°C").tagName).toBe("STRONG");
  });

  it("shows generated images and HTML artifacts from the local server", () => {
    render(
      <ChatScreen
        busy={false}
        connected
        mediaActions={actions}
        onSend={() => {}}
        onUpload={upload}
        items={[
          {
            kind: "tool", id: "t", label: "Génération", status: "done",
            media: [
              { id: "abc", kind: "image", title: "chalet", path: "/w/images/chalet.jpg", file_name: "chalet.jpg", size: 2048, url: "/media/abc" },
              { id: "def", kind: "html", title: "Graphique", path: "/w/artifacts/g.html", file_name: "g.html", size: 100, url: "/media/def" },
            ],
          },
        ]}
      />,
    );
    expect(screen.getByRole("img", { name: "chalet" })).toHaveAttribute("src", "http://127.0.0.1:9/media/abc");
    const frame = screen.getByTitle("Graphique");
    expect(frame).toHaveAttribute("src", "http://127.0.0.1:9/media/def");
    expect(frame).toHaveAttribute("sandbox", "allow-scripts");
  });

  it("attaches files with the paperclip and sends them with the message", async () => {
    const onSend = vi.fn();
    render(<ChatScreen items={[]} busy={false} connected mediaActions={actions} onSend={onSend} onUpload={upload} />);
    const file = new File(["rdv 14h"], "note.txt", { type: "text/plain" });
    await userEvent.upload(screen.getByTestId("file-input"), file);
    expect(await screen.findByText("note.txt")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Envoyer" }));
    expect(onSend).toHaveBeenCalledWith("", [expect.objectContaining({ upload_id: "up-note.txt" })]);
    expect(screen.queryByText("note.txt")).not.toBeInTheDocument();
  });

  it("lets the user remove an attachment before sending", async () => {
    render(<ChatScreen items={[]} busy={false} connected mediaActions={actions} onSend={() => {}} onUpload={upload} />);
    await userEvent.upload(screen.getByTestId("file-input"), new File(["x"], "brouillon.docx"));
    await userEvent.click(await screen.findByRole("button", { name: "Retirer brouillon.docx" }));
    expect(screen.queryByText("brouillon.docx")).not.toBeInTheDocument();
  });

  it("shows attachments in sent messages", () => {
    render(
      <ChatScreen
        busy={false}
        connected
        mediaActions={actions}
        onSend={() => {}}
        onUpload={upload}
        items={[{
          kind: "user", id: "u", text: "Que vois-tu ?",
          attachments: [{ id: "p", kind: "image", title: "photo.jpg", path: "/u/photo.jpg", file_name: "photo.jpg", size: 10, url: "/media/p" }],
        }]}
      />,
    );
    expect(screen.getByRole("img", { name: "photo.jpg" })).toHaveAttribute("src", "http://127.0.0.1:9/media/p");
    expect(screen.getByText("Que vois-tu ?")).toBeInTheDocument();
  });

  it("opens answer links in the browser, never in NOVA's window, and drops other link kinds", async () => {
    openExternal.mockClear();
    const text = "[la météo](https://meteo.example/paris) et [clic](javascript:alert(1)) et [fichier](file:///C:/x.exe)";
    render(<ChatScreen items={[{ kind: "assistant", id: "a", text }]} busy={false} connected mediaActions={actions} onSend={vi.fn()} onUpload={upload} />);
    const link = screen.getByRole("link", { name: "la météo" });
    expect(link).toHaveAttribute("title", "https://meteo.example/paris");
    await userEvent.click(link);
    expect(openExternal).toHaveBeenCalledWith("https://meteo.example/paris");
    expect(screen.getAllByRole("link")).toHaveLength(1);
    expect(screen.getByText("clic").tagName).toBe("SPAN");
  });

  it("shows the security warning of a hostile page read by a tool", () => {
    const items = [{ kind: "tool" as const, id: "t", label: "Lecture de la page", status: "done" as const, warning: "⚠️ la page contient des instructions adressées à l'IA." }];
    render(<ChatScreen items={items} busy={false} connected mediaActions={actions} onSend={vi.fn()} onUpload={upload} />);
    expect(screen.getByRole("alert")).toHaveTextContent("NOVA ne suivra pas ses instructions");
  });
});
