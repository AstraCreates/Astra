"use client";

import { useEffect, useState, type PointerEvent as ReactPointerEvent } from "react";
import { MessageCircle, PanelLeftClose, PanelLeftOpen, Plus } from "lucide-react";
import type { CompanyChatThread } from "@/lib/company-os";

const DEFAULT_WIDTH = 260;
const MIN_WIDTH = 200;
const MAX_WIDTH = 400;

function relativeTime(iso: string): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return "Just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export default function ChatThreadList({
  chats, activeThreadId, onSelect, onCreate, onDelete,
}: {
  chats: CompanyChatThread[];
  activeThreadId: string;
  onSelect: (threadId: string) => void;
  onCreate: () => void;
  onDelete: (threadId: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const [pendingDeleteId, setPendingDeleteId] = useState("");

  useEffect(() => {
    const saved = window.localStorage.getItem("astra-chat-sidebar-width");
    if (!saved) return;
    const value = Number(saved);
    if (Number.isFinite(value)) setWidth(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, value)));
  }, []);

  useEffect(() => {
    window.localStorage.setItem("astra-chat-sidebar-width", String(width));
  }, [width]);

  useEffect(() => {
    if (!pendingDeleteId) return;
    const timer = window.setTimeout(() => setPendingDeleteId(""), 3000);
    return () => window.clearTimeout(timer);
  }, [pendingDeleteId]);

  const startResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = width;
    // Mirrors CompanyHome's right-rail resizer, direction flipped: this
    // sidebar is on the left, so width grows as the pointer moves right.
    const move = (pointer: PointerEvent) => setWidth(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth + pointer.clientX - startX)));
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop, { once: true });
  };

  const handleDeleteClick = (event: React.MouseEvent, threadId: string) => {
    event.stopPropagation();
    if (pendingDeleteId !== threadId) {
      setPendingDeleteId(threadId);
      return;
    }
    setPendingDeleteId("");
    onDelete(threadId);
  };

  return (
    <>
      <div style={{ width: 44, flexShrink: 0, height: "100vh", display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 18, borderRight: "1px solid var(--bd)", background: "var(--bg-sunken)" }}>
        <button type="button" aria-label={open ? "Hide chat list" : "Show chat list"} onClick={() => setOpen(!open)}
          style={{ width: 30, height: 30, display: "grid", placeItems: "center", background: "transparent", border: "1px solid var(--bd)", borderRadius: 7, color: "var(--fm)", cursor: "pointer" }}>
          {open ? <PanelLeftClose size={14} /> : <PanelLeftOpen size={14} />}
        </button>
      </div>
      {open && <>
        <aside className="chat-thread-list" style={{ width, flexShrink: 0, height: "100vh", overflowY: "auto", borderRight: "1px solid var(--bd)", padding: "18px 8px 30px", background: "var(--bg-sunken)" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 8px", marginBottom: 10 }}>
            <h2 className="sec-label" style={{ margin: 0 }}>Chats</h2>
            <button type="button" onClick={onCreate} title="New chat"
              style={{ width: 24, height: 24, display: "grid", placeItems: "center", background: "transparent", border: "1px solid var(--bd)", borderRadius: 6, color: "var(--fg)", cursor: "pointer" }}>
              <Plus size={14} />
            </button>
          </div>
          {chats.length === 0 ? (
            <div className="empty" style={{ padding: "20px 8px" }}>
              <MessageCircle size={18} color="var(--fm)" />
              <div className="empty-title" style={{ marginTop: 8 }}>No chats yet</div>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {chats.map(chat => (
                <div key={chat.id} className={`nl${chat.id === activeThreadId ? " on" : ""}`}
                  style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}
                  onClick={() => onSelect(chat.id)}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{chat.title}</div>
                    {chat.updatedAt && <div style={{ fontSize: 10, color: "var(--fm)", marginTop: 1 }}>{relativeTime(chat.updatedAt)}</div>}
                  </div>
                  {chat.id !== "default" && (
                    <button type="button" onClick={(event) => handleDeleteClick(event, chat.id)}
                      onPointerDown={(event) => event.stopPropagation()}
                      title={pendingDeleteId === chat.id ? "Click again to confirm" : "Delete chat"}
                      style={{ flexShrink: 0, width: 20, height: 20, display: "grid", placeItems: "center", background: "transparent", border: 0, borderRadius: 5, color: pendingDeleteId === chat.id ? "var(--red)" : "var(--fm)", cursor: "pointer", fontSize: 9, fontWeight: 700 }}>
                      {pendingDeleteId === chat.id ? "DEL?" : "✕"}
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </aside>
        <div className="chat-thread-list-resizer" role="separator" aria-orientation="vertical" aria-label="Resize chat list" tabIndex={0}
          onPointerDown={startResize}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") setWidth(w => Math.max(MIN_WIDTH, w - 20));
            if (event.key === "ArrowRight") setWidth(w => Math.min(MAX_WIDTH, w + 20));
          }} />
      </>}
      <style>{`
        .chat-thread-list-resizer { width: 9px; flex: 0 0 9px; cursor: col-resize; position: relative; background: transparent; touch-action: none; }
        .chat-thread-list-resizer::after { content: ""; position: absolute; inset: 0 3px; background: var(--bd); transition: background .14s, width .14s; }
        .chat-thread-list-resizer:hover::after, .chat-thread-list-resizer:focus-visible::after { background: var(--accent); width: 3px; }
        @media (max-width: 860px) { .chat-thread-list, .chat-thread-list-resizer { display: none !important; } }
      `}</style>
    </>
  );
}
