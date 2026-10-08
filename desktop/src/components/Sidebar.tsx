import { Check, PanelLeftClose, Pencil, Search, SquarePen, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { ConversationSummary } from "../lib/api";
import { filterConversations, groupConversations } from "../lib/conversationGroups";

type SidebarProps = {
  conversations: ConversationSummary[];
  currentId: string | null;
  busy: boolean;
  onNew: () => void;
  onOpen: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
};

type Editing = { id: string; mode: "rename"; title: string } | { id: string; mode: "delete" } | null;

export const Sidebar = ({ conversations, currentId, busy, onNew, onOpen, onRename, onDelete, onClose }: SidebarProps) => {
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<Editing>(null);
  const groups = useMemo(() => groupConversations(filterConversations(conversations, query)), [conversations, query]);

  const submitRename = () => {
    if (editing?.mode === "rename" && editing.title.trim()) onRename(editing.id, editing.title.trim());
    setEditing(null);
  };

  return (
    <aside className="sidebar" aria-label="Conversations">
      <div className="sidebar-header">
        <span className="sidebar-title">Discussions</span>
        <button className="icon-button" onClick={onClose} title="Masquer la barre latérale" aria-label="Masquer la barre latérale">
          <PanelLeftClose size={18} />
        </button>
      </div>

      <button className="new-conversation" onClick={onNew} disabled={busy}>
        <SquarePen size={17} /> Nouvelle conversation
      </button>

      <label className="sidebar-search">
        <Search size={15} aria-hidden="true" />
        <input aria-label="Rechercher une conversation" placeholder="Rechercher" value={query} onChange={(event) => setQuery(event.target.value)} />
      </label>

      <nav className="conversation-list">
        {conversations.length === 0 && <p className="sidebar-empty">Tes conversations apparaîtront ici.</p>}
        {conversations.length > 0 && groups.length === 0 && <p className="sidebar-empty">Aucun résultat.</p>}
        {groups.map((group) => (
          <section key={group.label}>
            <h3 className="conversation-group">{group.label}</h3>
            <ul>
              {group.conversations.map((conversation) => {
                const active = conversation.id === currentId;
                const isEditing = editing?.id === conversation.id;
                return (
                  <li key={conversation.id} className={`conversation ${active ? "active" : ""}`}>
                    {isEditing && editing.mode === "rename" ? (
                      <form className="conversation-edit" onSubmit={(event) => { event.preventDefault(); submitRename(); }}>
                        <input
                          aria-label="Nouveau titre"
                          autoFocus
                          value={editing.title}
                          onChange={(event) => setEditing({ ...editing, title: event.target.value })}
                          onKeyDown={(event) => event.key === "Escape" && setEditing(null)}
                        />
                        <button type="submit" className="icon-button small" aria-label="Valider le titre"><Check size={15} /></button>
                      </form>
                    ) : isEditing && editing.mode === "delete" ? (
                      <div className="conversation-edit conversation-confirm">
                        <span>Supprimer ?</span>
                        <button className="icon-button small danger" aria-label="Confirmer la suppression" onClick={() => { onDelete(conversation.id); setEditing(null); }}>
                          <Trash2 size={15} />
                        </button>
                        <button className="icon-button small" aria-label="Annuler" onClick={() => setEditing(null)}><X size={15} /></button>
                      </div>
                    ) : (
                      <>
                        <button
                          className="conversation-title"
                          onClick={() => onOpen(conversation.id)}
                          disabled={busy && !active}
                          aria-current={active ? "page" : undefined}
                          title={conversation.title}
                        >
                          {conversation.title}
                        </button>
                        <span className="conversation-actions">
                          <button className="icon-button small" aria-label={`Renommer ${conversation.title}`} onClick={() => setEditing({ id: conversation.id, mode: "rename", title: conversation.title })}>
                            <Pencil size={14} />
                          </button>
                          <button className="icon-button small" aria-label={`Supprimer ${conversation.title}`} onClick={() => setEditing({ id: conversation.id, mode: "delete" })}>
                            <Trash2 size={14} />
                          </button>
                        </span>
                      </>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </nav>
    </aside>
  );
};
