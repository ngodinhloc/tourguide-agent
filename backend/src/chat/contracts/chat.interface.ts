export enum ChatStatus {
  isActive = 'isActive',
  isStopped = 'isStopped',
}

export enum AgentStatus {
  isThinking = 'isThinking',
  hasReplied = 'hasReplied',
}

export enum ChatActor {
  user = 'User',
  agent = 'Agent',
}

export interface ChatPlace {
  name: string;
  category: string;
  address: string;
  rating: number | null;
  description: string;
  image_url: string | null;
  source_url: string | null;
}

export interface ChatContent {
  location: string;
  narrative: string;
  places: ChatPlace[];
}

export interface ChatMessage {
  actor: ChatActor;
  text: string | ChatContent;
  timestamp: Date;
  agentStatus?: AgentStatus | null;
}

export interface ChatInterface {
  id: string;
  title?: string | null;
  content: ChatMessage[];
  status: ChatStatus;
  agentStatus?: AgentStatus;
}
