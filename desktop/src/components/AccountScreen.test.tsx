import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { NovaApi } from "../lib/api";
import { AccountScreen } from "./AccountScreen";

const WORK = { email: "bob@work.example", everyday_login: true };
const PERSONAL = { email: "alice@example.com", everyday_login: false };

const makeApi = (overrides = {}) =>
  ({
    accounts: vi.fn().mockResolvedValue({ current: null, available: [WORK, PERSONAL] }),
    startLogin: vi.fn().mockResolvedValue({ url: "https://claude.com/cai/oauth/authorize?redirect_uri=localhost", code_url: "https://claude.com/cai/oauth/authorize?code=true" }),
    loginStatus: vi.fn().mockResolvedValue({ account: null }),
    removeAccount: vi.fn().mockResolvedValue({ available: [WORK] }),
    ...overrides,
  }) as unknown as NovaApi;

afterEach(() => vi.useRealTimers());

describe("AccountScreen", () => {
  it("connects by itself once the sign-in finishes in the browser", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const api = makeApi();
    const onConnected = vi.fn();
    render(<AccountScreen api={api} onConnected={onConnected} />);
    await userEvent.click(await screen.findByRole("button", { name: /autre compte/ }));
    await userEvent.type(screen.getByLabelText("Adresse e-mail du compte"), PERSONAL.email);
    await userEvent.click(screen.getByRole("button", { name: "Continuer" }));
    expect(await screen.findByText("En attente de la connexion…")).toBeInTheDocument();
    expect(screen.getByLabelText("Lien de connexion")).toHaveValue("https://claude.com/cai/oauth/authorize?redirect_uri=localhost");
    expect(screen.queryByLabelText("Code de connexion")).not.toBeInTheDocument();

    vi.mocked(api.loginStatus).mockResolvedValue({ account: PERSONAL });
    await act(() => vi.advanceTimersByTimeAsync(2100));
    expect(onConnected).toHaveBeenCalledWith(PERSONAL);
  });

  it("removes a NOVA account after confirmation, never the everyday login", async () => {
    const api = makeApi();
    render(<AccountScreen api={api} onConnected={vi.fn()} />);
    await screen.findByText(PERSONAL.email);
    expect(screen.queryByRole("button", { name: `Retirer ${WORK.email}` })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: `Retirer ${PERSONAL.email}` }));
    await userEvent.click(screen.getByRole("button", { name: "Retirer" }));
    expect(api.removeAccount).toHaveBeenCalledWith(PERSONAL.email);
    expect(screen.queryByText(PERSONAL.email)).not.toBeInTheDocument();
  });
});
