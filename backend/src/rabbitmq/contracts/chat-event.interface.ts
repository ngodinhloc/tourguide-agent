import { ChatMessage } from '../../chat/contracts/chat.interface';

export interface ChatEvent {
  conversationId: string;
  message: string;
  history: ChatMessage[];
}
