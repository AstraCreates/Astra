"use client";

import type { RefObject } from "react";

type CopilotAction = { tool: string; label: string; detail?: string; tone?: "info" | "success" | "warn" };
type CopilotAttachment = { filename: string; kind: string; truncated: boolean; summary?: string };

type CopilotMessage = {
  role: string;
  content: string;
  actions?: CopilotAction[];
};

export default function CopilotDock({
  open,
  busy,
  messages,
  placeholder,
  emptyText,
  inputRef,
  onToggle,
  onSend,
  onFocus,
  attachments,
  uploading = false,
  fileInputRef,
  onAttachClick,
  onFileChange,
  onRemoveAttachment,
}: {
  open: boolean;
  busy: boolean;
  messages: CopilotMessage[];
  placeholder: string;
  emptyText: string;
  inputRef: RefObject<HTMLInputElement | null>;
  onToggle: () => void;
  onSend: () => void;
  onFocus: () => void;
  attachments?: CopilotAttachment[];
  uploading?: boolean;
  fileInputRef?: RefObject<HTMLInputElement | null>;
  onAttachClick?: () => void;
  onFileChange?: (files: FileList | null) => void;
  onRemoveAttachment?: (index: number) => void;
}) {
  const hasAttachments = Boolean(attachments && attachments.length > 0);

  return (
    <div className={`copilot-dock ${open ? "is-open" : ""}`}>
      {open && (
        <div className="copilot-thread">
          {messages.length === 0 && <div className="copilot-empty">{emptyText}</div>}
          {messages.map((message, index) => (
            <div key={index} className={`copilot-row ${message.role === "founder" ? "is-founder" : "is-astra"}`}>
              {message.role !== "founder" && <span className="copilot-avatar">A</span>}
              <div className="copilot-bubble">
                {message.content}
                {message.actions && message.actions.length > 0 && (
                  <div className="copilot-actions" aria-label="Copilot actions">
                    {message.actions.map((action, actionIndex) => (
                      <div key={`${action.tool}-${actionIndex}`} className={`copilot-action-card is-${action.tone || "info"}`}>
                        <div className="copilot-action-label">{action.label}</div>
                        {action.detail && <div className="copilot-action-detail">{action.detail}</div>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {busy && (
            <div className="copilot-row is-astra">
              <span className="copilot-avatar">A</span>
              <div className="copilot-thinking"><span /><span /><span /></div>
            </div>
          )}
        </div>
      )}

      <div className="steer-wrap">
        <button className="steer-send copilot-toggle" aria-label="Toggle copilot" title="Copilot chat" onClick={onToggle}>
          {open ? "▾" : "✦"}
        </button>
        {onAttachClick && fileInputRef && onFileChange && (
          <>
            <button
              className="steer-send copilot-attach"
              aria-label="Attach file"
              title="Attach file"
              disabled={uploading || busy}
              onClick={onAttachClick}
            >
              {uploading ? "…" : "+"}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              hidden
              onChange={(event) => onFileChange(event.target.files)}
            />
          </>
        )}
        <input
          ref={inputRef}
          className="steer-inp"
          aria-label="Ask or direct Astra"
          placeholder={placeholder}
          disabled={busy}
          onFocus={onFocus}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              onSend();
            }
          }}
        />
        <button className="steer-send copilot-submit" aria-label="Send" onClick={onSend} disabled={busy}>
          ↑
        </button>
      </div>

      {hasAttachments && onRemoveAttachment && attachments && (
        <div className="copilot-attachment-tray" aria-label="Attached files">
          {attachments.map((file, index) => (
            <button
              key={`${file.filename}-${index}`}
              className="copilot-attachment-chip"
              title={file.summary || file.filename}
              onClick={() => onRemoveAttachment(index)}
            >
              <span>{file.filename}</span>
              <small>{file.kind}{file.truncated ? " · clipped" : ""}</small>
              <b>×</b>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
