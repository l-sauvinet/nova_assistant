import { Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Account, NovaApi } from "../lib/api";
import { openExternal } from "../lib/openExternal";
import { Orb } from "./Orb";

type AccountScreenProps = {
  api: NovaApi;
  onConnected: (account: Account) => void;
};

type Step = { kind: "choose" } | { kind: "email" } | { kind: "code"; email: string; url: string; codeUrl: string };

export const AccountScreen = ({ api, onConnected }: AccountScreenProps) => {
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [step, setStep] = useState<Step>({ kind: "choose" });
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [showCode, setShowCode] = useState(false);

  useEffect(() => {
    api.accounts().then((result) => setAccounts(result.available), (reason: Error) => setError(reason.message));
  }, [api]);

  const attempt = async (action: () => Promise<void>) => {
    setError(null);
    setWorking(true);
    try {
      await action();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setWorking(false);
    }
  };

  const choose = (account: Account) => attempt(async () => onConnected((await api.selectAccount(account.email)).account));

  const remove = (account: Account) =>
    attempt(async () => {
      setAccounts((await api.removeAccount(account.email)).available);
      setRemoving(null);
    });

  const startLogin = () =>
    attempt(async () => {
      const { url, code_url } = await api.startLogin(email.trim());
      setCopied(false);
      setShowCode(false);
      setStep({ kind: "code", email: email.trim(), url, codeUrl: code_url });
    });

  const connectedRef = useRef(onConnected);
  connectedRef.current = onConnected;

  useEffect(() => {
    if (step.kind !== "code" || working) return;
    let stopped = false;
    const timer = window.setInterval(() => {
      api.loginStatus().then(
        ({ account }) => {
          if (stopped || !account) return;
          stopped = true;
          connectedRef.current(account);
        },
        (reason: Error) => {
          if (stopped) return;
          stopped = true;
          setError(reason.message);
          setStep({ kind: "email" });
        },
      );
    }, 2000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [api, step, working]);

  const copyLink = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      setError("Copie impossible : sélectionne le lien ci-dessous et copie-le avec Ctrl+C.");
    }
  };

  const finishLogin = () => attempt(async () => onConnected((await api.finishLogin(code.trim())).account));

  return (
    <main className="centered-screen">
      <div className="card">
        <div className="card-header">
          <Orb state="idle" size={34} />
          <span className="wordmark">NOVA</span>
        </div>
        {step.kind === "choose" && (
          <>
            <h2>Quel compte Claude utiliser ?</h2>
            <p className="muted">Ce choix est gardé jusqu'à ce que tu changes de compte.</p>
            <p className="muted">
              NOVA s'appuie sur <strong>Claude Code</strong>, l'outil en ligne de commande d'Anthropic : il doit être installé
              et connecté à ton abonnement Claude sur cet ordinateur.{" "}
              <button type="button" className="link-button" onClick={() => openExternal("https://claude.com/claude-code")}>
                Pas encore installé ? Clique ici
              </button>
              , puis lance <code>claude</code> une fois dans un terminal pour te connecter.
            </p>
            {accounts === null && !error && <p className="muted">Recherche des comptes connectés…</p>}
            <div className="account-list">
              {accounts?.map((account) =>
                removing === account.email ? (
                  <div key={account.email} className="account-option account-confirm" role="group" aria-label={`Retirer ${account.email}`}>
                    <span>Retirer {account.email} de NOVA ?</span>
                    <span className="muted">NOVA s'en déconnecte pour de bon : il faudra se reconnecter pour le réutiliser.</span>
                    <div className="form-actions">
                      <button type="button" className="button-secondary" disabled={working} onClick={() => setRemoving(null)}>Annuler</button>
                      <button type="button" className="button-secondary danger-button" disabled={working} onClick={() => remove(account)}>Retirer</button>
                    </div>
                  </div>
                ) : (
                  <div key={account.email} className="account-row">
                    <button className="account-option" disabled={working} onClick={() => choose(account)}>
                      <span>{account.email}</span>
                      <span className="muted">{account.everyday_login ? "connexion Claude Code habituelle" : "compte NOVA"}</span>
                    </button>
                    {!account.everyday_login && (
                      <button className="icon-button account-remove" disabled={working} onClick={() => setRemoving(account.email)} aria-label={`Retirer ${account.email}`} title="Retirer ce compte de NOVA">
                        <Trash2 size={16} />
                      </button>
                    )}
                  </div>
                ),
              )}
              <button className="account-option account-add" disabled={working} onClick={() => setStep({ kind: "email" })}>
                + Se connecter avec un autre compte
              </button>
            </div>
          </>
        )}
        {step.kind === "email" && (
          <form onSubmit={(event) => { event.preventDefault(); startLogin(); }}>
            <h2>Ajouter un compte Claude</h2>
            <label htmlFor="account-email">Adresse e-mail du compte</label>
            <input id="account-email" type="email" required autoFocus value={email} onChange={(event) => setEmail(event.target.value)} />
            <div className="form-actions">
              <button type="button" className="button-secondary" onClick={() => setStep({ kind: "choose" })}>Retour</button>
              <button type="submit" className="button-primary" disabled={working || !email.trim()}>
                {working ? "Ouverture…" : "Continuer"}
              </button>
            </div>
          </form>
        )}
        {step.kind === "code" && (
          <form onSubmit={(event) => { event.preventDefault(); finishLogin(); }}>
            <h2>Connexion de {step.email}</h2>
            <p>Ouvre la page de connexion Claude et connecte-toi avec <strong>{step.email}</strong>. NOVA continue tout seul dès que c'est fait.</p>
            <div className="form-actions login-actions">
              <button type="button" className="button-primary" onClick={() => openExternal(step.url)}>Ouvrir dans mon navigateur</button>
              <button type="button" className="button-secondary" onClick={() => copyLink(step.url)}>{copied ? "Lien copié ✓" : "Copier le lien"}</button>
            </div>
            <p className="muted">
              Ton navigateur est déjà connecté à un autre compte Claude ? Copie le lien et colle-le dans une fenêtre privée
              (<kbd>Ctrl</kbd>+<kbd>Maj</kbd>+<kbd>N</kbd>) : pas besoin de te déconnecter.
            </p>
            <input className="login-link" readOnly aria-label="Lien de connexion" value={step.url} onFocus={(event) => event.target.select()} />
            <p className="muted" role="status">En attente de la connexion…</p>
            {!showCode ? (
              <button type="button" className="link-button" onClick={() => setShowCode(true)}>La page affiche un code ?</button>
            ) : (
              <>
                <p className="muted">
                  Colle le code ci-dessous. Si tu n'en as pas, <button type="button" className="link-button" onClick={() => openExternal(step.codeUrl)}>ouvre la page qui en donne un</button>.
                </p>
                <label htmlFor="login-code">Code de connexion</label>
                <input id="login-code" required autoFocus value={code} onChange={(event) => setCode(event.target.value)} />
              </>
            )}
            <div className="form-actions">
              <button type="button" className="button-secondary" onClick={() => setStep({ kind: "email" })}>Retour</button>
              {showCode && (
                <button type="submit" className="button-primary" disabled={working || !code.trim()}>
                  {working ? "Vérification…" : "Se connecter"}
                </button>
              )}
            </div>
          </form>
        )}
        {error && <p className="error-text" role="alert">{error}</p>}
      </div>
    </main>
  );
};
