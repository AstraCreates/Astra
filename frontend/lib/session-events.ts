"use client";

import { useEffect, useRef } from "react";
import { streamGoal, type StreamSubscription } from "@/lib/api";

// SSE payloads are backend-defined and intentionally heterogeneous.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type SessionEvent = { type?: string; [key: string]: any };

type Listener = {
  onOpen?: () => void;
  onEvent?: (event: SessionEvent) => void;
  onError?: (error: unknown) => void;
};

type SessionEventStore = {
  source: StreamSubscription | null;
  listeners: Set<Listener>;
};

const stores = new Map<string, SessionEventStore>();

function getStore(sessionId: string): SessionEventStore {
  let store = stores.get(sessionId);
  if (!store) {
    store = { source: null, listeners: new Set() };
    stores.set(sessionId, store);
  }
  return store;
}

function ensureConnected(sessionId: string, store: SessionEventStore) {
  if (store.source) return;
  const source = streamGoal(sessionId);
  store.source = source;
  source.onopen = () => {
    for (const listener of store.listeners) listener.onOpen?.();
  };
  source.onerror = (error) => {
    for (const listener of store.listeners) listener.onError?.(error);
  };
  source.onmessage = (message) => {
    try {
      const event = JSON.parse(message.data) as SessionEvent;
      if (event.type === "ping") return;
      for (const listener of store.listeners) listener.onEvent?.(event);
    } catch (error) {
      for (const listener of store.listeners) listener.onError?.(error);
    }
  };
}

export function subscribeSessionEvents(sessionId: string, listener: Listener): () => void {
  const store = getStore(sessionId);
  store.listeners.add(listener);
  ensureConnected(sessionId, store);
  return () => {
    store.listeners.delete(listener);
    if (store.listeners.size === 0) {
      store.source?.close();
      stores.delete(sessionId);
    }
  };
}

export function useSessionEventStream(
  sessionId: string | null | undefined,
  listener: Listener,
  options: { enabled?: boolean } = {},
): void {
  const enabled = options.enabled ?? true;
  const listenerRef = useRef(listener);

  useEffect(() => {
    listenerRef.current = listener;
  }, [listener]);

  useEffect(() => {
    if (!sessionId || !enabled) return;
    return subscribeSessionEvents(sessionId, {
      onOpen: () => {
        listenerRef.current.onOpen?.();
      },
      onEvent: (event) => listenerRef.current.onEvent?.(event),
      onError: (error) => {
        listenerRef.current.onError?.(error);
      },
    });
  }, [enabled, sessionId]);
}
