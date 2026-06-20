import { Injectable, Logger } from '@nestjs/common';
import { RabbitMQService } from '../../rabbitmq/services/rabbitmq.service';
import type { ChatEvent } from '../../rabbitmq/contracts/chat-event.interface';
import { ChatMessage } from '../contracts/chat.interface';

@Injectable()
export class AgentService {
  private readonly logger = new Logger(AgentService.name);

  constructor(private readonly rabbitMQService: RabbitMQService) {}

  call(id: string, message: string, history: ChatMessage[] = []): void {
    try {
      const event: ChatEvent = { conversationId: id, message, history };
      this.rabbitMQService.publish(event);
    } catch (err) {
      this.logger.error(`Failed to publish to RabbitMQ for conversation ${id}: ${err}`);
    }
  }
}
