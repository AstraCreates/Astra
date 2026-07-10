"use client";

import { useMemo, useRef, useState } from "react";
import { ArrowUp, AtSign, Paperclip } from "lucide-react";

export type CopilotAgentOption = {
  id: string;
  label: string;
  status?: string;
};

export function extractAgentMentions(value: string, agents: CopilotAgentOption[]): string[] {
  const valid = new Set(agents.map((agent) => agent.id));
  const found = Array.from(value.matchAll(/(?:^|\s)@([a-z0-9_]+)/gi), (match) => match[1].toLowerCase());
  return Array.from(new Set(found.filter((id) => valid.has(id))));
}

export default function AstraCopilotComposer({
  value,
  onChange,
  onSubmit,
  agents,
  disabled = false,
  placeholder = "Ask Astra or @mention an agent",
  contextLabel,
  onAttach,
  attachmentCount = 0,
  autoFocus = false,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string, mentionedAgents: string[]) => void | Promise<void>;
  agents: CopilotAgentOption[];
  disabled?: boolean;
  placeholder?: string;
  contextLabel?: string;
  onAttach?: () => void;
  attachmentCount?: number;
  autoFocus?: boolean;
}) {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionStart, setMentionStart] = useState(-1);
  const [activeIndex, setActiveIndex] = useState(0);

  const filteredAgents = useMemo(() => {
    if (mentionQuery === null) return [];
    const query = mentionQuery.toLowerCase();
    return agents
      .filter((agent) => agent.id.toLowerCase().includes(query) || agent.label.toLowerCase().includes(query))
      .slice(0, 8);
  }, [agents, mentionQuery]);

  const mentions = useMemo(() => extractAgentMentions(value, agents), [agents, value]);

  function updateMentionState(next: string, caret: number) {
    const before = next.slice(0, caret);
    const match = before.match(/(?:^|\s)@([a-z0-9_]*)$/i);
    if (!match) {
      setMentionQuery(null);
      setMentionStart(-1);
      return;
    }
    setMentionQuery(match[1]);
    setMentionStart(caret - match[1].length - 1);
    setActiveIndex(0);
  }

  function selectAgent(agent: CopilotAgentOption) {
    const input = inputRef.current;
    const caret = input?.selectionStart ?? value.length;
    const start = mentionStart >= 0 ? mentionStart : caret;
    const next = `${value.slice(0, start)}@${agent.id} ${value.slice(caret)}`;
    onChange(next);
    setMentionQuery(null);
    setMentionStart(-1);
    requestAnimationFrame(() => {
      const nextCaret = start + agent.id.length + 2;
      inputRef.current?.focus();
      inputRef.current?.setSelectionRange(nextCaret, nextCaret);
    });
  }

  function submit() {
    const clean = value.trim();
    if (!clean || disabled) return;
    void onSubmit(clean, extractAgentMentions(clean, agents));
    setMentionQuery(null);
  }

  return (
    <div className="astra-composer-shell">
      {filteredAgents.length > 0 && (
        <div className="astra-mention-menu" role="listbox" aria-label="Mention an Astra agent">
          <div className="astra-mention-heading">Direct this to</div>
          {filteredAgents.map((agent, index) => (
            <button
              key={agent.id}
              type="button"
              role="option"
              aria-selected={index === activeIndex}
              className={`astra-mention-option${index === activeIndex ? " is-active" : ""}`}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => selectAgent(agent)}
            >
              <span className="astra-agent-mark">{agent.label.slice(0, 1).toUpperCase()}</span>
              <span>
                <b>{agent.label}</b>
                <small>@{agent.id}</small>
              </span>
              {agent.status && <em className={`is-${agent.status}`}>{agent.status}</em>}
            </button>
          ))}
        </div>
      )}

      {mentions.length > 0 && (
        <div className="astra-composer-targets" aria-label="Mentioned agents">
          {mentions.map((id) => (
            <span key={id}><AtSign size={11} />{agents.find((agent) => agent.id === id)?.label ?? id}</span>
          ))}
        </div>
      )}

      <textarea
        ref={inputRef}
        value={value}
        autoFocus={autoFocus}
        disabled={disabled}
        rows={2}
        aria-label="Message Astra"
        placeholder={placeholder}
        onChange={(event) => {
          onChange(event.target.value);
          updateMentionState(event.target.value, event.target.selectionStart);
        }}
        onClick={(event) => updateMentionState(value, event.currentTarget.selectionStart)}
        onKeyDown={(event) => {
          if (filteredAgents.length > 0 && mentionQuery !== null) {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActiveIndex((index) => (index + 1) % filteredAgents.length);
              return;
            }
            if (event.key === "ArrowUp") {
              event.preventDefault();
              setActiveIndex((index) => (index - 1 + filteredAgents.length) % filteredAgents.length);
              return;
            }
            if (event.key === "Enter" || event.key === "Tab") {
              event.preventDefault();
              selectAgent(filteredAgents[activeIndex]);
              return;
            }
            if (event.key === "Escape") {
              event.preventDefault();
              setMentionQuery(null);
              return;
            }
          }
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
      />

      <div className="astra-composer-footer">
        <div className="astra-composer-tools">
          {onAttach && (
            <button type="button" onClick={onAttach} disabled={disabled} aria-label="Attach files" title="Attach files">
              <Paperclip size={16} />
              {attachmentCount > 0 && <span>{attachmentCount}</span>}
            </button>
          )}
          <span><AtSign size={13} /> mention an agent</span>
          {contextLabel && <small>{contextLabel}</small>}
        </div>
        <button type="button" className="astra-composer-submit" onClick={submit} disabled={disabled || !value.trim()} aria-label="Send message">
          <ArrowUp size={17} strokeWidth={2.4} />
        </button>
      </div>
    </div>
  );
}
