"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { PanelLeft, PanelRight, Plus, MessageSquare } from "lucide-react";
import { getHistory } from "@/lib/api";
import { ConversationSummary } from "@/types/chat";

export default function Sidebar() {
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(true);
  const [history, setHistory] = useState<ConversationSummary[]>([]);

  useEffect(() => {
    const refresh = () => getHistory().then(setHistory).catch(() => {});
    refresh();
    window.addEventListener("chat-completed", refresh);
    return () => window.removeEventListener("chat-completed", refresh);
  }, []);

  function handleNewChat() {
    router.push(`/?session=${Date.now()}`);
  }

  return (
    <aside
      className={`flex flex-col h-screen shrink-0 border-r border-zinc-200 bg-zinc-50 transition-all duration-200 dark:border-zinc-800 dark:bg-zinc-950 ${
        isOpen ? "w-64" : "w-14"
      }`}
    >
      <div className="flex items-center gap-2 border-b border-zinc-200 p-3 dark:border-zinc-800">
        <button
          onClick={() => setIsOpen((v) => !v)}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-zinc-500 hover:bg-zinc-200 hover:text-zinc-800 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
          aria-label={isOpen ? "Collapse sidebar" : "Expand sidebar"}
        >
          {isOpen ? <PanelLeft size={16} /> : <PanelRight size={16} />}
        </button>
        {isOpen && (
          <button
            onClick={handleNewChat}
            className="flex flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-200 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            <Plus size={15} />
            New Chat
          </button>
        )}
      </div>

      <nav className="flex-1 overflow-y-auto p-2">
        {isOpen && history.length > 0 && (
          <p className="mb-1 px-2 text-xs font-semibold uppercase tracking-wider text-zinc-400 dark:text-zinc-600">
            History
          </p>
        )}
        {history.map((item) => (
          <button
            key={item.id}
            title={item.title || "Untitled"}
            onClick={() => router.push(`/?chat=${item.id}`)}
            className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm text-zinc-600 hover:bg-zinc-200 dark:text-zinc-400 dark:hover:bg-zinc-800"
          >
            <MessageSquare size={14} className="shrink-0 text-zinc-400 dark:text-zinc-600" />
            {isOpen && (
              <span className="truncate">{item.title || "Untitled"}</span>
            )}
          </button>
        ))}
      </nav>
    </aside>
  );
}
