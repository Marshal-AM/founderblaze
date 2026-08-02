"use client";

import { useCallback, useEffect, useState } from "react";
import Image from "next/image";
import { useSession } from "next-auth/react";
import { PanelLeft } from "lucide-react";
import { AuthControls } from "./AuthControls";
import { AuthModal } from "./AuthModal";
import { AssetsDialog } from "./AssetsDialog";
import { ChatWorkspace } from "./ChatWorkspace";
import { ThreadSidebar, type ThreadSummary } from "./ThreadSidebar";

export function AgentApp({ googleEnabled }: { googleEnabled: boolean }) {
  const { data: session } = useSession();
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [loadingThreads, setLoadingThreads] = useState(false);
  const [assetsOpen, setAssetsOpen] = useState(false);
  const [authOpen, setAuthOpen] = useState(false);
  const [leftOpen, setLeftOpen] = useState(true);

  const refreshThreads = useCallback(async () => {
    if (!session?.user) {
      setThreads([]);
      return;
    }
    setLoadingThreads(true);
    try {
      const res = await fetch("/api/history");
      const data = await res.json();
      setThreads(data.threads || []);
    } catch {
      setThreads([]);
    } finally {
      setLoadingThreads(false);
    }
  }, [session?.user]);

  useEffect(() => {
    void refreshThreads();
  }, [refreshThreads]);

  function onNewChat() {
    setThreadId(null);
  }

  const gridClass = ["workspace-grid", !leftOpen ? "left-collapsed" : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="app-shell grid-bg locked">
      <header className="app-header">
        <div className="app-header-inner">
          <div className="brand-mark">
            <Image
              src="/founderblaze-logo.png"
              alt="FounderBlaze"
              width={210}
              height={42}
              className="brand-logo"
              priority
            />
          </div>
          <AuthControls googleEnabled={googleEnabled} />
        </div>
      </header>

      <main className="workspace">
        <div className={gridClass}>
          {leftOpen ? (
            <ThreadSidebar
              threads={threads}
              activeThreadId={threadId}
              onSelect={setThreadId}
              onNew={onNewChat}
              onOpenAssets={() => setAssetsOpen(true)}
              onCollapse={() => setLeftOpen(false)}
              loading={loadingThreads}
            />
          ) : (
            <button
              type="button"
              className="sidebar-rail"
              onClick={() => setLeftOpen(true)}
              title="Show chats"
              aria-label="Show chats"
            >
              <PanelLeft className="h-4 w-4" />
            </button>
          )}

          <ChatWorkspace
            threadId={threadId}
            onThreadChange={setThreadId}
            onHistoryChanged={refreshThreads}
            onRequestSignIn={() => setAuthOpen(true)}
          />
        </div>
      </main>

      <AssetsDialog open={assetsOpen} onClose={() => setAssetsOpen(false)} />
      <AuthModal
        open={authOpen}
        onClose={() => setAuthOpen(false)}
        googleEnabled={googleEnabled}
      />
    </div>
  );
}
