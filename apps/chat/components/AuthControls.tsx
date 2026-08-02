"use client";

import { useState } from "react";
import { signOut, useSession } from "next-auth/react";
import { LogIn, LogOut } from "lucide-react";
import { AuthModal } from "./AuthModal";

export function AuthControls({ googleEnabled }: { googleEnabled: boolean }) {
  const { data: session, status } = useSession();
  const [open, setOpen] = useState(false);

  if (status === "loading") {
    return <span className="nav-pill">…</span>;
  }

  if (session?.user) {
    return (
      <div className="auth-controls">
        <span className="user-chip" title={session.user.email || undefined}>
          {session.user.image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={session.user.image} alt="" className="user-avatar" />
          ) : (
            <span className="user-avatar fallback">
              {(session.user.name || session.user.email || "?").slice(0, 1).toUpperCase()}
            </span>
          )}
          <span className="user-name">
            {session.user.name || session.user.email}
          </span>
        </span>
        <button
          type="button"
          className="btn-ghost-pill"
          onClick={() => signOut({ callbackUrl: "/" })}
        >
          <LogOut className="h-4 w-4" />
          Sign out
        </button>
      </div>
    );
  }

  return (
    <>
      <button type="button" className="btn-ember-pill" onClick={() => setOpen(true)}>
        <LogIn className="h-4 w-4" />
        Sign in
      </button>
      <AuthModal
        open={open}
        onClose={() => setOpen(false)}
        googleEnabled={googleEnabled}
      />
    </>
  );
}
