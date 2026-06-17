export type ChatStatus = "isActive" | "isStopped";
export type AgentStatus = "isThinking" | "hasReplied";
export type ChatActor = "User" | "Agent";

export interface ChatPlace {
  name: string;
  category: "attraction" | "restaurant" | "hotel";
  address: string;
  rating: number | null;
  description: string;
  image_url: string | null;
  source_url: string | null;
}

export interface ChatResult {
  location: string;
  narrative: string;
  places: ChatPlace[];
}

export interface ChatMessage {
  actor: ChatActor;
  text: string;
  timestamp: string;
  agentStatus?: AgentStatus | null;
  type: "text" | "json";
}

export interface ChatInterface {
  id: string;
  title?: string | null;
  content: ChatMessage[];
  status: ChatStatus;
  agentStatus?: AgentStatus;
}

export interface ConversationSummary {
  id: string;
  title: string;
  createdAt: string;
}
