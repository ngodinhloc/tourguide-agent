import { ChatInterface, ConversationSummary } from "@/types/chat";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...options, cache: "no-store" });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail?.message ?? `Request failed: ${res.status}`);
  }
  return res.json();
}

export async function continueChat(id: string, message: string): Promise<{ accepted: true }> {
  return request(`/api/chat/${id}/cont`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
}

export async function newChat(message: string): Promise<{ id: string }> {
  return request("/api/chat/new", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
}

export async function pollChat(id: string): Promise<ChatInterface> {
  return request(`/api/chat/${id}`);
}

export async function stopChat(id: string): Promise<void> {
  await request(`/api/chat/${id}/stop`, { method: "POST" });
}

export async function getHistory(): Promise<ConversationSummary[]> {
  return request("/api/chat/history");
}
