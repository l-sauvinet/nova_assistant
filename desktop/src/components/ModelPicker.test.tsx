import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { NovaApi } from "../lib/api";
import { ModelPicker } from "./ModelPicker";

const options = [
  { id: "haiku", label: "Haiku", description: "Rapide et économe" },
  { id: "opus", label: "Opus", description: "Le plus capable, consomme davantage" },
];

const makeApi = (current: string | null, extra = {}) =>
  ({
    models: vi.fn().mockResolvedValue({ current, options }),
    selectModel: vi.fn().mockResolvedValue({ current: "opus", options }),
    ...extra,
  }) as unknown as NovaApi;

describe("ModelPicker", () => {
  it("shows the current model and switches to another one", async () => {
    const api = makeApi("haiku");
    render(<ModelPicker api={api} disabled={false} onError={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: /Haiku/ }));
    await userEvent.click(screen.getByRole("option", { name: /Opus/ }));
    expect(api.selectModel).toHaveBeenCalledWith("opus");
    expect(await screen.findByRole("button", { name: /Opus/ })).toBeInTheDocument();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("is locked while NOVA answers", async () => {
    render(<ModelPicker api={makeApi("haiku")} disabled onError={vi.fn()} />);
    expect(await screen.findByRole("button", { name: /Haiku/ })).toBeDisabled();
  });

  it("stays hidden when the provider offers no choice", async () => {
    const api = { models: vi.fn().mockResolvedValue({ current: null, options: [] }) } as unknown as NovaApi;
    const { container } = render(<ModelPicker api={api} disabled={false} onError={vi.fn()} />);
    await vi.waitFor(() => expect(api.models).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("reports a refused choice", async () => {
    const onError = vi.fn();
    const api = makeApi("haiku", { selectModel: vi.fn().mockRejectedValue(new Error("Modèle inconnu")) });
    render(<ModelPicker api={api} disabled={false} onError={onError} />);
    await userEvent.click(await screen.findByRole("button", { name: /Haiku/ }));
    await userEvent.click(screen.getByRole("option", { name: /Opus/ }));
    expect(onError).toHaveBeenCalledWith("Modèle inconnu");
  });
});
