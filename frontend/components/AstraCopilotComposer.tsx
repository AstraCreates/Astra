"use client";

import { useMemo, useRef, useState } from "react";
import { ArrowUp, AtSign, LoaderCircle, Mic, MicOff, Paperclip } from "lucide-react";
import { transcribeAudio } from "@/lib/api";
import { extractCopilotMentions, type CopilotMention, type CopilotMentionOption } from "@/lib/copilot-mentions";

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
  onSubmitMentions,
  agents,
  mentionOptions = [],
  disabled = false,
  placeholder = "Ask Astra or @mention an agent",
  contextLabel,
  onAttach,
  attachmentCount = 0,
  autoFocus = false,
  founderId,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit?: (value: string, mentionedAgents: string[]) => void | Promise<void>;
  onSubmitMentions?: (value: string, mentions: CopilotMention[]) => void | Promise<void>;
  agents: CopilotAgentOption[];
  mentionOptions?: CopilotMentionOption[];
  disabled?: boolean;
  placeholder?: string;
  contextLabel?: string;
  onAttach?: () => void;
  attachmentCount?: number;
  autoFocus?: boolean;
  founderId?: string;
}) {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const recordingChunksRef = useRef<Blob[]>([]);
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionStart, setMentionStart] = useState(-1);
  const [activeIndex, setActiveIndex] = useState(0);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [voiceError, setVoiceError] = useState("");

  const legacyMentionOptions = useMemo<CopilotMentionOption[]>(() => agents.map((agent) => ({
    kind: "squad",
    id: agent.id,
    token: agent.id,
    label: agent.label,
    group: "Agents",
    subtitle: agent.id,
  })), [agents]);
  const allMentionOptions = mentionOptions.length > 0 ? mentionOptions : legacyMentionOptions;

  const filteredMentionOptions = useMemo(() => {
    if (mentionQuery === null) return [];
    const query = mentionQuery.toLowerCase();
    return allMentionOptions
      .filter((option) => option.token.toLowerCase().includes(query) || option.label.toLowerCase().includes(query) || option.subtitle?.toLowerCase().includes(query))
      .slice(0, 8);
  }, [allMentionOptions, mentionQuery]);

  const mentions = useMemo(() => extractCopilotMentions(value, allMentionOptions), [allMentionOptions, value]);

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

  function selectMention(option: CopilotMentionOption) {
    const input = inputRef.current;
    const caret = input?.selectionStart ?? value.length;
    const start = mentionStart >= 0 ? mentionStart : caret;
    const next = `${value.slice(0, start)}@${option.token} ${value.slice(caret)}`;
    onChange(next);
    setMentionQuery(null);
    setMentionStart(-1);
    requestAnimationFrame(() => {
      const nextCaret = start + option.token.length + 2;
      inputRef.current?.focus();
      inputRef.current?.setSelectionRange(nextCaret, nextCaret);
    });
  }

  function submit() {
    const clean = value.trim();
    if (!clean || disabled) return;
    const structured = extractCopilotMentions(clean, allMentionOptions);
    if (onSubmitMentions) void onSubmitMentions(clean, structured);
    else void onSubmit?.(clean, structured.filter((mention) => mention.kind === "squad").map((mention) => mention.id));
    setMentionQuery(null);
  }

  async function toggleRecording() {
    if (recording) {
      recorderRef.current?.stop();
      return;
    }
    if (!founderId) {
      setVoiceError("Voice is unavailable until your workspace is signed in.");
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setVoiceError("This browser does not support microphone recording.");
      return;
    }
    setVoiceError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recordingChunksRef.current = [];
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) recordingChunksRef.current.push(event.data);
      };
      recorder.onerror = () => {
        stream.getTracks().forEach((track) => track.stop());
        recorderRef.current = null;
        setRecording(false);
        setVoiceError("Microphone recording failed. Please try again.");
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        recorderRef.current = null;
        setRecording(false);
        const blob = new Blob(recordingChunksRef.current, { type: recorder.mimeType || "audio/webm" });
        recordingChunksRef.current = [];
        if (!blob.size) {
          setVoiceError("No audio was captured.");
          return;
        }
        setTranscribing(true);
        try {
          const extension = blob.type.includes("mp4") ? "m4a" : "webm";
          const result = await transcribeAudio(founderId, new File([blob], `speech.${extension}`, { type: blob.type }));
          if (!result.ok || !result.text.trim()) {
            setVoiceError(result.error || "No speech was detected.");
            return;
          }
          const separator = value.trim() ? " " : "";
          onChange(`${value}${separator}${result.text.trim()}`);
          requestAnimationFrame(() => inputRef.current?.focus());
        } catch {
          setVoiceError("Could not transcribe that recording.");
        } finally {
          setTranscribing(false);
        }
      };
      recorder.start();
      setRecording(true);
    } catch {
      setVoiceError("Microphone access was blocked. Check your browser permission and try again.");
    }
  }

  return (
    <div className="astra-composer-shell">
      {filteredMentionOptions.length > 0 && (
        <div className="astra-mention-menu" role="listbox" aria-label="Mention a squad, squad member, or Library file">
          <div className="astra-mention-heading">Mention a squad, teammate, or Library file</div>
          {filteredMentionOptions.map((option, index) => (
            <button
              key={`${option.kind}:${option.id}`}
              type="button"
              role="option"
              aria-selected={index === activeIndex}
              className={`astra-mention-option${index === activeIndex ? " is-active" : ""}`}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => selectMention(option)}
            >
              <span className="astra-agent-mark">{option.kind === "library_file" ? "#" : option.label.slice(0, 1).toUpperCase()}</span>
              <span>
                <b>{option.label}</b>
                <small>{option.group}{option.subtitle ? ` · ${option.subtitle}` : ""}</small>
              </span>
            </button>
          ))}
        </div>
      )}

      {mentions.length > 0 && (
        <div className="astra-composer-targets" aria-label="Selected mentions">
          {mentions.map((mention) => (
            <span key={`${mention.kind}:${mention.id}`}><AtSign size={11} />{mention.label}</span>
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
          if (filteredMentionOptions.length > 0 && mentionQuery !== null) {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActiveIndex((index) => (index + 1) % filteredMentionOptions.length);
              return;
            }
            if (event.key === "ArrowUp") {
              event.preventDefault();
              setActiveIndex((index) => (index - 1 + filteredMentionOptions.length) % filteredMentionOptions.length);
              return;
            }
            if (event.key === "Enter" || event.key === "Tab") {
              event.preventDefault();
              selectMention(filteredMentionOptions[activeIndex]);
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
          {founderId && (
            <button type="button" onClick={() => void toggleRecording()} disabled={disabled || transcribing} aria-label={recording ? "Stop recording" : "Record voice message"} title={recording ? "Stop recording" : "Record voice message"} className={recording ? "is-recording" : undefined}>
              {transcribing ? <LoaderCircle size={16} className="astra-composer-spin" /> : recording ? <MicOff size={16} /> : <Mic size={16} />}
            </button>
          )}
          <span><AtSign size={13} /> mention a squad, teammate, or file</span>
          {contextLabel && <small>{contextLabel}</small>}
        </div>
        <button type="button" className="astra-composer-submit" onClick={submit} disabled={disabled || !value.trim()} aria-label="Send message">
          <span className="astra-composer-submit-label">Ask Astra</span>
          <ArrowUp size={17} strokeWidth={2.4} />
        </button>
      </div>
      {(recording || transcribing || voiceError) && <div className={`astra-composer-voice-status${voiceError ? " is-error" : ""}`} role="status">{voiceError || (transcribing ? "Transcribing recording…" : "Recording… click the microphone to stop")}</div>}
    </div>
  );
}
