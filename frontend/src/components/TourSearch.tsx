"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import SearchBar from "./SearchBar";
import ResultsPanel from "./ResultsPanel";
import LoadingSkeleton from "./LoadingSkeleton";
import { newChat, continueChat, getChat, stopChat } from "@/lib/api";
import { AgentStatus, ChatContent, ChatInterface, ChatMessage } from "@/types/chat";
import { MapPin } from "lucide-react";

const IDLE_TIMEOUT_MS = 30_000;

interface CompletedTurn {
  userMessage: string;
  thinkingMessages: ChatMessage[];
  result: ChatContent | null;
}

interface Turn {
  userMessage: string;
  agentMessages: ChatMessage[];
  result: ChatContent | null;
  error: string | null;
}

function splitTurns(content: ChatMessage[]): Turn[] {
  const turns: Turn[] = [];
  let userMessage = "";
  let agentMessages: ChatMessage[] = [];

  for (const msg of content) {
    if (msg.actor === "User") {
      userMessage = msg.text as string;
      agentMessages = [];
    } else if (msg.actor === "Agent") {
      agentMessages.push(msg);
      if (msg.agentStatus === "hasReplied") {
        const result: ChatContent | null = typeof msg.text === "object" ? msg.text : null;
        const error: string | null = typeof msg.text === "string" ? msg.text : null;
        turns.push({ userMessage, agentMessages: [...agentMessages], result, error });
        userMessage = "";
        agentMessages = [];
      }
    }
  }

  return turns;
}

function buildWsUrl(): string {
  const base = process.env.NEXT_PUBLIC_WS_URL;
  if (base) return `${base}/ws`;
  if (typeof window !== "undefined") {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.hostname}:8000/ws`;
  }
  return "ws://localhost:8000/ws";
}

export default function TourSearch() {
  const searchParams = useSearchParams();
  const session = searchParams.get("session");
  const chatId = searchParams.get("chat");

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ChatContent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isThinkingIdle, setIsThinkingIdle] = useState(false);
  const [userMessage, setUserMessage] = useState<string | null>(null);
  const [completedTurns, setCompletedTurns] = useState<CompletedTurn[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const idleTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeIdRef = useRef<string | null>(null);
  const conversationIdRef = useRef<string | null>(null);
  const agentStatusRef = useRef<AgentStatus | null>(null);
  const prevThinkingCountRef = useRef(0);
  const agentMessageOffsetRef = useRef(0);
  const conversationEndRef = useRef<HTMLDivElement | null>(null);

  function disconnectWs() {
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.close();
      wsRef.current = null;
    }
  }

  function cancelIdleTimer() {
    if (idleTimeoutRef.current) {
      clearTimeout(idleTimeoutRef.current);
      idleTimeoutRef.current = null;
    }
  }

  function endConversation() {
    disconnectWs();
    cancelIdleTimer();
    activeIdRef.current = null;
    agentStatusRef.current = null;
    setLoading(false);
  }

  // New chat button — full reset
  useEffect(() => {
    disconnectWs();
    cancelIdleTimer();
    activeIdRef.current = null;
    conversationIdRef.current = null;
    agentStatusRef.current = null;
    prevThinkingCountRef.current = 0;
    agentMessageOffsetRef.current = 0;
    setLoading(false);
    setResult(null);
    setError(null);
    setMessages([]);
    setIsThinkingIdle(false);
    setUserMessage(null);
    setCompletedTurns([]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  // Load history chat
  useEffect(() => {
    if (!chatId) return;
    disconnectWs();
    cancelIdleTimer();
    activeIdRef.current = null;
    conversationIdRef.current = null;
    agentStatusRef.current = null;
    prevThinkingCountRef.current = 0;
    agentMessageOffsetRef.current = 0;
    setResult(null);
    setError(null);
    setMessages([]);
    setIsThinkingIdle(false);
    setLoading(true);
    setCompletedTurns([]);

    getChat(chatId)
      .then((chat) => {
        const turns = splitTurns(chat.content);
        if (turns.length === 0) return;

        const lastTurn = turns[turns.length - 1];
        const prevTurns = turns.slice(0, -1);

        setUserMessage(lastTurn.userMessage);
        setMessages(lastTurn.agentMessages);
        if (lastTurn.result) setResult(lastTurn.result);
        else if (lastTurn.error) setError(lastTurn.error);

        setCompletedTurns(
          prevTurns.map((t: Turn) => ({
            userMessage: t.userMessage,
            thinkingMessages: t.agentMessages.filter((m: ChatMessage) => m.agentStatus === "isThinking"),
            result: t.result,
          }))
        );

        agentMessageOffsetRef.current = prevTurns.reduce((acc: number, t: Turn) => acc + t.agentMessages.length, 0);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load conversation.");
      })
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId]);

  const resetIdleTimer = useCallback(() => {
    if (!activeIdRef.current) return;
    cancelIdleTimer();
    idleTimeoutRef.current = setTimeout(async () => {
      const id = activeIdRef.current;
      if (!id) return;
      if (agentStatusRef.current !== "hasReplied") {
        resetIdleTimer();
        return;
      }
      endConversation();
      try {
        await stopChat(id);
      } catch {
        // best-effort
      }
    }, IDLE_TIMEOUT_MS);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const events = ["mousemove", "keydown", "click", "touchstart"] as const;
    events.forEach((e) => window.addEventListener(e, resetIdleTimer));
    return () => {
      events.forEach((e) => window.removeEventListener(e, resetIdleTimer));
      disconnectWs();
      cancelIdleTimer();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetIdleTimer]);

  function subscribeToChat(id: string) {
    disconnectWs();

    const ws = new WebSocket(buildWsUrl());
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ event: "subscribe", data: id }));
    };

    ws.onmessage = (evt) => {
      try {
        const { event: type, data } = JSON.parse(evt.data as string) as {
          event: string;
          data: ChatInterface | string;
        };

        if (type === "error") {
          endConversation();
          setError(typeof data === "string" ? data : "Agent error.");
          return;
        }

        if (type !== "chat-update") return;
        const chat = data as ChatInterface;

        agentStatusRef.current = chat.agentStatus ?? null;

        const allAgentMessages = chat.content.filter((m) => m.actor === "Agent");
        const currentTurnMessages = allAgentMessages.slice(agentMessageOffsetRef.current);
        const thinkingCount = currentTurnMessages.filter((m) => m.agentStatus === "isThinking").length;
        setIsThinkingIdle(thinkingCount === prevThinkingCountRef.current);
        prevThinkingCountRef.current = thinkingCount;
        setMessages(currentTurnMessages);

        if (chat.agentStatus === "hasReplied") {
          endConversation();
          const finalMsg = [...chat.content].reverse().find((m) => m.agentStatus === "hasReplied");
          if (finalMsg && typeof finalMsg.text === "object") {
            setResult(finalMsg.text);
          } else {
            setError(typeof finalMsg?.text === "string" ? finalMsg.text : "The agent did not return a response.");
          }
          stopChat(id).catch(() => {});
          window.dispatchEvent(new CustomEvent("chat-completed"));
        }
      } catch {
        // ignore parse errors
      }
    };

    ws.onerror = () => {
      endConversation();
      setError("Connection error. Please try again.");
    };

    ws.onclose = (evt) => {
      if (!evt.wasClean && activeIdRef.current === id) {
        endConversation();
        setError("Connection lost. Please try again.");
      }
    };
  }

  async function handleSearch(message: string) {
    disconnectWs();
    cancelIdleTimer();
    prevThinkingCountRef.current = 0;
    agentMessageOffsetRef.current = 0;
    setLoading(true);
    setError(null);
    setResult(null);
    setMessages([]);
    setIsThinkingIdle(false);
    setUserMessage(message);
    setCompletedTurns([]);

    try {
      const { id } = await newChat(message);
      activeIdRef.current = id;
      conversationIdRef.current = id;
      resetIdleTimer();
      subscribeToChat(id);
    } catch (err) {
      setLoading(false);
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    }
  }

  async function handleContinue(message: string) {
    const id = conversationIdRef.current ?? chatId;
    if (!id) return;

    if (userMessage) {
      setCompletedTurns((prev: CompletedTurn[]) => [
        ...prev,
        {
          userMessage,
          thinkingMessages: messages.filter((m: ChatMessage) => m.agentStatus === "isThinking"),
          result,
        },
      ]);
    }

    agentMessageOffsetRef.current += messages.length;

    disconnectWs();
    cancelIdleTimer();
    prevThinkingCountRef.current = 0;
    setLoading(true);
    setError(null);
    setResult(null);
    setMessages([]);
    setIsThinkingIdle(false);
    setUserMessage(message);

    try {
      await continueChat(id, message);
      activeIdRef.current = id;
      resetIdleTimer();
      subscribeToChat(id);
    } catch (err) {
      setLoading(false);
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    }
  }

  const thinkingMessages = messages.filter((m: ChatMessage) => m.agentStatus === "isThinking");
  const hasConversation = userMessage !== null || completedTurns.length > 0;
  const currentConversationId = conversationIdRef.current ?? chatId;

  useEffect(() => {
    conversationEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, result, isThinkingIdle, completedTurns]);

  if (!hasConversation) {
    return (
      <div className="flex h-full flex-col items-center bg-zinc-50 px-4 pt-16 dark:bg-zinc-950">
        <div className="flex w-full max-w-2xl flex-col items-center gap-6 text-center">
          <div className="flex items-center gap-2 text-indigo-600 dark:text-indigo-400">
            <MapPin size={28} />
            <span className="text-2xl font-bold tracking-tight">Tour Guide Agent</span>
          </div>
          <p className="max-w-md text-sm text-zinc-500 dark:text-zinc-400">
            Enter any city or destination to discover the best attractions, restaurants, and hotels powered by AI.
          </p>
          <SearchBar onSearch={handleSearch} loading={loading} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-zinc-50 dark:bg-zinc-950">
      {/* Scrollable conversation area */}
      <div className="flex-1 overflow-y-auto px-4 py-8">
        <div className="mx-auto max-w-3xl space-y-6">

          {/* Completed turns */}
          {completedTurns.map((turn: CompletedTurn, i: number) => (
            <div key={i} className="space-y-4">
              <div className="flex items-start">
                <div className="max-w-xl rounded-2xl rounded-tl-none bg-indigo-600 px-4 py-3 text-sm text-white shadow-sm">
                  {turn.userMessage}
                </div>
              </div>
              {turn.thinkingMessages.length > 0 && (
                <ul className="space-y-1.5 rounded-xl bg-zinc-900 p-4 font-mono text-sm dark:bg-zinc-950">
                  {turn.thinkingMessages.map((m, j) => (
                    <li key={j} className="flex items-center gap-3 text-zinc-300 dark:text-zinc-400">
                      <span className="shrink-0 text-xs text-zinc-500">
                        {new Date(m.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                      </span>
                      <span className="text-indigo-400">$</span>
                      {typeof m.text === "string" ? m.text : ""}
                    </li>
                  ))}
                </ul>
              )}
              {turn.result && <ResultsPanel result={turn.result} />}
              <hr className="border-zinc-200 dark:border-zinc-800" />
            </div>
          ))}

          {/* Current turn */}
          {userMessage && (
            <>
              <div className="flex items-start">
                <div className="max-w-xl rounded-2xl rounded-tl-none bg-indigo-600 px-4 py-3 text-sm text-white shadow-sm">
                  {userMessage}
                </div>
              </div>

              {/* Tool call block */}
              {(thinkingMessages.length > 0 || (isThinkingIdle && loading)) && (
                <ul className="space-y-1.5 rounded-xl bg-zinc-900 p-4 font-mono text-sm dark:bg-zinc-950">
                  {thinkingMessages.map((m: ChatMessage, i: number) => (
                    <li key={i} className="flex items-center gap-3 text-zinc-300 dark:text-zinc-400">
                      <span className="shrink-0 text-xs text-zinc-500">
                        {new Date(m.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                      </span>
                      <span className="text-indigo-400">$</span>
                      {typeof m.text === "string" ? m.text : ""}
                    </li>
                  ))}
                  {isThinkingIdle && loading && (
                    <li className="flex items-center gap-3 animate-pulse text-zinc-500 dark:text-zinc-600">
                      <span className="text-indigo-400">$</span>
                      Thinking...
                    </li>
                  )}
                </ul>
              )}

              {/* Loading skeleton */}
              {loading && <LoadingSkeleton />}

              {/* Error */}
              {error && (
                <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-400">
                  {error}
                </div>
              )}

              {/* Result */}
              {result && !loading && <ResultsPanel result={result} />}
            </>
          )}

          <div ref={conversationEndRef} />
        </div>
      </div>

      {/* Search bar pinned to bottom */}
      <div className="border-t border-zinc-200 bg-zinc-50 px-4 py-4 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="mx-auto max-w-3xl">
          <SearchBar
            onSearch={currentConversationId ? handleContinue : handleSearch}
            loading={loading}
          />
        </div>
      </div>
    </div>
  );
}
