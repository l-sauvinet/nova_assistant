import { MapPin, PanelLeftOpen, SquarePen, UserRound } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { AccountScreen } from "./components/AccountScreen";
import { ChatScreen } from "./components/ChatScreen";
import { ModelPicker } from "./components/ModelPicker";
import { ConfirmDialog } from "./components/ConfirmDialog";
import { LocationBanner } from "./components/LocationBanner";
import { Orb, type OrbState } from "./components/Orb";
import { Sidebar } from "./components/Sidebar";
import { FilesScreen } from "./components/files/FilesScreen";
import { HomeScreen } from "./components/HomeScreen";
import { NavRail, type View } from "./components/NavRail";
import { isTauri } from "@tauri-apps/api/core";
import { createApi, type ConversationSummary, type FileEntry, type NovaApi, type Status, type UploadedAttachment } from "./lib/api";
import { loadServerConfig } from "./lib/config";
import { createMediaActions } from "./lib/mediaActions";
import { SECTIONS } from "./lib/sections";
import { useChat } from "./lib/useChat";

const STARTUP_RETRY_MS = 1000;
const SLOW_STARTUP_ATTEMPTS = 5;

const useNovaServer = () => {
  const [api, setApi] = useState<NovaApi | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [startupError, setStartupError] = useState<string | null>(null);
  const [failedAttempts, setFailedAttempts] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    loadServerConfig().then(
      (config) => {
        const client = createApi(config);
        const poll = () =>
          client.status().then(
            (result) => {
              if (cancelled) return;
              setApi(client);
              setStatus(result);
            },
            () => {
              if (cancelled) return;
              setFailedAttempts((count) => count + 1);
              timer = window.setTimeout(poll, STARTUP_RETRY_MS);
            },
          );
        poll();
      },
      (reason: Error) => setStartupError(reason.message),
    );
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, []);

  const refresh = useCallback(async () => {
    if (api) setStatus(await api.status());
  }, [api]);

  return { api, status, startupError, slowStartup: failedAttempts >= SLOW_STARTUP_ATTEMPTS, refresh };
};

const orbStateFor = (chat: ReturnType<typeof useChat>): OrbState => {
  if (!chat.connected) return "offline";
  if (chat.confirmation) return "asking";
  if (chat.items.some((item) => item.kind === "tool" && item.status === "running")) return "working";
  if (chat.busy) return "thinking";
  return "idle";
};

const STATUS_TEXT: Record<OrbState, string> = {
  idle: "Prêt",
  thinking: "Réfléchit…",
  working: "Agit sur l'ordinateur…",
  asking: "Attend ton accord",
  offline: "Reconnexion…",
};

const WIDE_SCREEN = "(min-width: 900px)";

const Workspace = ({ api, status, onRefresh }: { api: NovaApi; status: Status; onRefresh: () => void }) => {
  const [view, setView] = useState<View>(() => {
    const requested = window.location.hash.slice(1);
    return SECTIONS.some((section) => section.id === requested) ? (requested as View) : "home";
  });
  const [queuedUploads, setQueuedUploads] = useState<UploadedAttachment[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(() => window.matchMedia?.(WIDE_SCREEN).matches ?? true);
  const [notice, setNotice] = useState<string | null>(null);

  const refreshConversations = useCallback(async () => {
    const result = await api.conversations();
    setConversations(result.conversations);
    setCurrentId(result.current);
  }, [api]);

  const chat = useChat(
    api.chatUrl,
    (saved) => {
      setCurrentId(saved.id);
      setConversations((list) => [saved, ...list.filter((item) => item.id !== saved.id)]);
    },
    (titled) => setConversations((list) => list.map((item) => (item.id === titled.id ? { ...item, title: titled.title } : item))),
  );
  const mediaActions = useMemo(() => createMediaActions(api), [api]);
  const [locationDismissed, setLocationDismissed] = useState(false);
  const orbState = orbStateFor(chat);
  const currentTitle = conversations.find((item) => item.id === currentId)?.title;

  useEffect(() => {
    refreshConversations().catch(() => undefined);
  }, [refreshConversations]);

  const attempt = async (action: () => Promise<void>) => {
    setNotice(null);
    try {
      await action();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const closeSidebarOnSmallScreens = () => {
    if (!window.matchMedia?.(WIDE_SCREEN).matches) setSidebarOpen(false);
  };

  const startNew = () =>
    attempt(async () => {
      await api.newConversation();
      chat.clear();
      setCurrentId(null);
      closeSidebarOnSmallScreens();
    });

  const navigate = (next: View) => {
    if (next === "chat" && view !== "chat" && currentId !== null && !chat.busy) {
      attempt(async () => {
        await api.newConversation();
        chat.clear();
        setCurrentId(null);
      });
    }
    setView(next);
  };

  const open = (id: string) =>
    attempt(async () => {
      if (id === currentId) return closeSidebarOnSmallScreens();
      const { items } = await api.openConversation(id);
      chat.load(items);
      setCurrentId(id);
      closeSidebarOnSmallScreens();
    });

  const rename = (id: string, title: string) =>
    attempt(async () => {
      const { conversation } = await api.renameConversation(id, title);
      setConversations((list) => list.map((item) => (item.id === id ? conversation : item)));
    });

  const remove = (id: string) =>
    attempt(async () => {
      await api.deleteConversation(id);
      setConversations((list) => list.filter((item) => item.id !== id));
      if (id === currentId) {
        chat.clear();
        setCurrentId(null);
      }
    });

  const switchAccount = () =>
    attempt(async () => {
      await api.switchAccount();
      chat.clear();
      onRefresh();
    });

  const askNovaAbout = (entry: FileEntry) =>
    attempt(async () => {
      const upload = await api.attachFile(entry.path);
      setQueuedUploads((current) => [...current, upload]);
      navigate("chat");
    });

  return (
    <div className="app-frame">
      <NavRail view={view} orbState={orbState} canLogOut={status.needs_account} onNavigate={navigate} onLogOut={switchAccount} />
      <div className="section-view" hidden={view !== "home"}>
        <HomeScreen status={status} orbState={orbState} onOpen={navigate} />
      </div>
      <div className="section-view" hidden={view !== "files"}>
        <FilesScreen api={api} mediaActions={mediaActions} onAskNova={askNovaAbout} />
      </div>
    <div className={`app-shell section-view ${sidebarOpen ? "sidebar-open" : ""}`} hidden={view !== "chat"}>
      {sidebarOpen && (
        <Sidebar
          conversations={conversations}
          currentId={currentId}
          busy={chat.busy}
          onNew={startNew}
          onOpen={open}
          onRename={rename}
          onDelete={remove}
          onClose={() => setSidebarOpen(false)}
        />
      )}
      {sidebarOpen && <div className="sidebar-scrim" onClick={() => setSidebarOpen(false)} aria-hidden="true" />}
      <div className="workspace">
        <header className="topbar">
          <div className="identity">
            {!sidebarOpen && (
              <>
                <button className="icon-button" onClick={() => setSidebarOpen(true)} title="Afficher les conversations" aria-label="Afficher les conversations">
                  <PanelLeftOpen size={18} />
                </button>
                <Orb state={orbState} size={26} />
              </>
            )}
            <span className="conversation-heading" title={currentTitle}>{currentTitle ?? "Nouvelle conversation"}</span>
            <span className={`status-text status-${orbState}`}>{STATUS_TEXT[orbState]}</span>
          </div>
          <div className="topbar-actions">
            {status.location && (
              <span className="chip" title={status.location.label}>
                <MapPin size={14} aria-hidden="true" /> {status.location.city || status.location.label}
              </span>
            )}
            {status.account && (
              <span className="chip" title="Compte Claude utilisé">
                <UserRound size={14} aria-hidden="true" /> {status.account.email}
              </span>
            )}
            {!sidebarOpen && (
              <button className="icon-button" onClick={startNew} disabled={chat.busy} title="Nouvelle conversation" aria-label="Nouvelle conversation">
                <SquarePen size={18} />
              </button>
            )}
          </div>
        </header>
        {notice && <div className="banner" role="alert">{notice}<button className="link-button" onClick={() => setNotice(null)}>OK</button></div>}
        {!status.location && !locationDismissed && (
          <LocationBanner api={api} onSaved={() => onRefresh()} onClose={() => setLocationDismissed(true)} />
        )}
        <ChatScreen items={chat.items} busy={chat.busy} connected={chat.connected} mediaActions={mediaActions}
          onSend={chat.sendMessage}
          onUpload={api.upload}
          queuedUploads={queuedUploads}
          onQueuedConsumed={() => setQueuedUploads([])}
          modelPicker={<ModelPicker api={api} disabled={chat.busy} onError={setNotice} />}
        />
      </div>
    </div>
      {chat.confirmation && <ConfirmDialog request={chat.confirmation} onAnswer={chat.answerConfirmation} />}
    </div>
  );
};

const SplashScreen = ({ children }: { children?: ReactNode }) => (
  <main className="centered-screen">
    <div className="splash">
      <Orb state="thinking" size={96} />
      <p className="wordmark wordmark-large">NOVA</p>
      {children}
    </div>
  </main>
);

export const App = () => {
  const { api, status, startupError, slowStartup, refresh } = useNovaServer();
  const needsAccount = useMemo(() => status?.needs_account && !status.account, [status]);

  if (startupError) {
    return <SplashScreen><p className="error-text">{startupError}</p></SplashScreen>;
  }
  if (!api || !status) {
    return (
      <SplashScreen>
        <p className="muted">Démarrage…</p>
        {slowStartup && (
          <p className="error-text" role="alert">
            {isTauri()
              ? "Le moteur de NOVA met du temps à répondre. S'il ne démarre pas, ferme et relance l'application."
              : "Le moteur de NOVA ne répond pas. Lance-le dans un terminal : cd ~/perso/nova/desktop && npm run engine:dev"}
          </p>
        )}
      </SplashScreen>
    );
  }
  if (needsAccount) {
    return <AccountScreen api={api} onConnected={() => refresh()} />;
  }
  return <Workspace api={api} status={status} onRefresh={() => refresh()} />;
};
