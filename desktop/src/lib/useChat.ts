import { useCallback, useEffect, useRef, useState } from "react";
import type { ConversationSummary, StoredItem, UploadedAttachment } from "./api";
import { describeTool } from "./toolLabels";

export type MediaItem = {
  id: string;
  kind: "image" | "svg" | "html" | "file";
  title: string;
  path: string;
  file_name: string;
  size: number;
  url: string;
  warning?: string;
};

export type ChatItem =
  | { kind: "user"; id: string; text: string; attachments?: MediaItem[] }
  | { kind: "assistant"; id: string; text: string }
  | { kind: "error"; id: string; text: string }
  | { kind: "tool"; id: string; label: string; status: "running" | "done" | "error"; media?: MediaItem[]; warning?: string };

export type ConfirmationRequest = { id: string; question: string; warning?: string | null };

export type ServerEvent =
  | { type: "thinking" }
  | { type: "assistant_message"; text: string }
  | { type: "error"; message: string }
  | { type: "tool_started"; id: string; name: string; arguments: Record<string, unknown> }
  | { type: "tool_finished"; id: string; name: string; is_error: boolean; media?: MediaItem[]; warning?: string }
  | { type: "confirmation_request"; id: string; question: string; warning?: string | null }
  | { type: "reset_done" }
  | { type: "conversation_saved"; conversation: ConversationSummary }
  | { type: "conversation_titled"; conversation: ConversationSummary };

export type ChatState = { items: ChatItem[]; busy: boolean; confirmation: ConfirmationRequest | null };

export const initialChatState: ChatState = { items: [], busy: false, confirmation: null };

let sequence = 0;
const nextId = () => `item-${++sequence}`;

export const applyServerEvent = (state: ChatState, event: ServerEvent): ChatState => {
  switch (event.type) {
    case "thinking":
      return { ...state, busy: true };
    case "assistant_message":
      return { ...state, busy: false, items: [...state.items, { kind: "assistant", id: nextId(), text: event.text }] };
    case "error":
      return { ...state, busy: false, confirmation: null, items: [...state.items, { kind: "error", id: nextId(), text: event.message }] };
    case "tool_started":
      return {
        ...state,
        items: [...state.items, { kind: "tool", id: event.id, label: describeTool(event.name, event.arguments), status: "running" }],
      };
    case "tool_finished":
      return {
        ...state,
        items: state.items.map((item) =>
          item.kind === "tool" && item.id === event.id
            ? { ...item, status: event.is_error ? "error" : "done", media: event.media, warning: event.warning }
            : item,
        ),
      };
    case "confirmation_request":
      return { ...state, confirmation: { id: event.id, question: event.question, warning: event.warning } };
    case "reset_done":
      return initialChatState;
    case "conversation_saved":
    case "conversation_titled":
      return state;
  }
};

export const itemsFromHistory = (stored: StoredItem[]): ChatItem[] =>
  stored.map((item) =>
    item.kind === "tool"
      ? { kind: "tool", id: item.id, label: describeTool(item.name, item.arguments), status: item.status, media: item.media, warning: item.warning }
      : item.kind === "user"
        ? { kind: "user", id: nextId(), text: item.text, attachments: item.attachments }
        : { kind: item.kind, id: nextId(), text: item.text },
  );

export const useChat = (
  chatUrl: string,
  onConversationSaved?: (conversation: ConversationSummary) => void,
  onConversationTitled?: (conversation: ConversationSummary) => void,
) => {
  const [state, setState] = useState<ChatState>(initialChatState);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const savedRef = useRef(onConversationSaved);
  savedRef.current = onConversationSaved;
  const titledRef = useRef(onConversationTitled);
  titledRef.current = onConversationTitled;

  useEffect(() => {
    let closedByUs = false;
    let retryTimer: number | undefined;

    const connect = () => {
      const socket = new WebSocket(chatUrl);
      socketRef.current = socket;
      socket.onopen = () => setConnected(true);
      socket.onmessage = (message) => {
        const event: ServerEvent = JSON.parse(message.data);
        if (event.type === "conversation_saved") savedRef.current?.(event.conversation);
        if (event.type === "conversation_titled") titledRef.current?.(event.conversation);
        setState((current) => applyServerEvent(current, event));
      };
      socket.onclose = () => {
        setConnected(false);
        setState((current) => ({ ...current, busy: false, confirmation: null }));
        if (!closedByUs) retryTimer = window.setTimeout(connect, 1500);
      };
    };

    connect();
    return () => {
      closedByUs = true;
      window.clearTimeout(retryTimer);
      const socket = socketRef.current;
      if (socket?.readyState === WebSocket.CONNECTING) {
        socket.onopen = () => socket.close();
      } else {
        socket?.close();
      }
    };
  }, [chatUrl]);

  const send = useCallback((payload: object) => socketRef.current?.send(JSON.stringify(payload)), []);

  const sendMessage = useCallback(
    (text: string, attachments: UploadedAttachment[] = []) => {
      const shown = attachments.map((upload) => upload.attachment);
      setState((current) => ({ ...current, busy: true, items: [...current.items, { kind: "user", id: nextId(), text, attachments: shown }] }));
      send({ type: "user_message", text, attachments: attachments.map((upload) => upload.upload_id) });
    },
    [send],
  );

  const confirmationRef = useRef<ConfirmationRequest | null>(null);
  confirmationRef.current = state.confirmation;

  const answerConfirmation = useCallback(
    (approved: boolean) => {
      const confirmation = confirmationRef.current;
      if (!confirmation) return;
      send({ type: "confirmation_answer", id: confirmation.id, approved });
      setState((current) => ({ ...current, confirmation: null }));
    },
    [send],
  );

  const reset = useCallback(() => send({ type: "reset" }), [send]);
  const clear = useCallback(() => setState(initialChatState), []);
  const load = useCallback((stored: StoredItem[]) => setState({ ...initialChatState, items: itemsFromHistory(stored) }), []);

  return { ...state, connected, sendMessage, answerConfirmation, reset, clear, load };
};
