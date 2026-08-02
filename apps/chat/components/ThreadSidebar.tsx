"use client";

import { FolderOpen, MessageSquarePlus, PanelLeftClose, Plus } from "lucide-react";
import { useSession } from "next-auth/react";

export type ThreadSummary = {
  id: string;
  title: string;
  updated_at: string;
};

type Props = {
  threads: ThreadSummary[];
  activeThreadId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onOpenAssets: () => void;
  onCollapse: () => void;
  loading?: boolean;
};

export function ThreadSidebar({
  threads,
  activeThreadId,
  onSelect,
  onNew,
  onOpenAssets,
  onCollapse,
  loading,
}: Props) {
  const { data: session } = useSession();
  const signedIn = Boolean(session?.user);

  return (
    <aside className="panel-card sidebar-panel">
      <div className="panel-header">
        <div>
          <p className="panel-kicker">History</p>
          <p className="panel-title">Chats</p>
        </div>
        <div className="panel-header-actions">
          <button
            type="button"
            className="icon-btn"
            onClick={onNew}
            title="New chat"
            aria-label="New chat"
          >
            <Plus className="h-4 w-4" />
          </button>
          <button
            type="button"
            className="icon-btn"
            onClick={onCollapse}
            title="Collapse sidebar"
            aria-label="Collapse sidebar"
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>
        </div>
      </div>

      <button type="button" className="assets-btn" onClick={onOpenAssets}>
        <FolderOpen className="h-4 w-4" />
        My assets
        {!signedIn ? <span className="assets-hint">sign in</span> : null}
      </button>

      <div className="thread-list">
        {!signedIn ? (
          <div className="sidebar-empty">
            <MessageSquarePlus className="h-5 w-5" />
            <p>Sign in to keep generation history across visits.</p>
          </div>
        ) : loading ? (
          <p className="sidebar-muted">Loading…</p>
        ) : threads.length === 0 ? (
          <div className="sidebar-empty">
            <p>No chats yet. Start one in the center.</p>
          </div>
        ) : (
          threads.map((t) => (
            <button
              key={t.id}
              type="button"
              className={
                t.id === activeThreadId ? "thread-row active" : "thread-row"
              }
              onClick={() => onSelect(t.id)}
            >
              <span className="thread-title">{t.title}</span>
              <span className="thread-date mono">
                {new Date(t.updated_at).toLocaleDateString()}
              </span>
            </button>
          ))
        )}
      </div>
    </aside>
  );
}
