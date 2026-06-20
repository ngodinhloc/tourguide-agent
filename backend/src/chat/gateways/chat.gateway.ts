import { WebSocketGateway, WebSocketServer, SubscribeMessage, OnGatewayDisconnect } from '@nestjs/websockets';
import { Injectable } from '@nestjs/common';
import { Server, WebSocket } from 'ws';
import { RedisService } from '../../redis/services/redis.service';
import { ChatInterface, AgentStatus } from '../contracts/chat.interface';

const POLL_INTERVAL_MS = 500;
const MAX_POLLS = 180; // 90 s timeout

@Injectable()
@WebSocketGateway({ path: '/ws' })
export class ChatGateway implements OnGatewayDisconnect {
  @WebSocketServer() server: Server;

  private readonly subscriptions = new Map<WebSocket, NodeJS.Timeout>();

  constructor(private readonly redisService: RedisService) {}

  @SubscribeMessage('subscribe')
  handleSubscribe(client: WebSocket, chatId: string): void {
    this.clearSubscription(client);

    let polls = 0;

    const intervalId = setInterval(async () => {
      if (++polls > MAX_POLLS) {
        this.clearSubscription(client);
        client.send(JSON.stringify({ event: 'error', data: 'Timed out waiting for agent.' }));
        return;
      }

      try {
        const chat = await this.redisService.getJson<ChatInterface>(`chat:${chatId}`);
        if (!chat) return;

        client.send(JSON.stringify({ event: 'chat-update', data: chat }));

        if (chat.agentStatus === AgentStatus.hasReplied) {
          this.clearSubscription(client);
        }
      } catch {
        // Redis transient error — keep polling
      }
    }, POLL_INTERVAL_MS);

    this.subscriptions.set(client, intervalId);
  }

  handleDisconnect(client: WebSocket): void {
    this.clearSubscription(client);
  }

  private clearSubscription(client: WebSocket): void {
    const existing = this.subscriptions.get(client);
    if (existing) {
      clearInterval(existing);
      this.subscriptions.delete(client);
    }
  }
}
