import { Injectable, Logger, OnModuleInit, OnModuleDestroy } from '@nestjs/common';
import * as amqp from 'amqplib';
import type { ChatEvent } from '../contracts/chat-event.interface';

const QUEUE = 'tour-guide.chat';

@Injectable()
export class RabbitMQService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(RabbitMQService.name);
  private connection: amqp.ChannelModel | null = null;
  private channel: amqp.Channel | null = null;

  async onModuleInit() {
    const url = process.env.RABBITMQ_URL ?? 'amqp://guest:guest@localhost:5672/';
    this.connection = await amqp.connect(url);
    this.channel = await this.connection.createChannel();
    await this.channel.assertQueue(QUEUE, { durable: true });
    this.logger.log(`Connected to RabbitMQ, queue: ${QUEUE}`);
  }

  async onModuleDestroy() {
    await this.channel?.close();
    await this.connection?.close();
  }

  publish(event: ChatEvent): void {
    if (!this.channel) {
      this.logger.error('RabbitMQ channel not ready');
      return;
    }
    this.channel.sendToQueue(QUEUE, Buffer.from(JSON.stringify(event)), { persistent: true });
  }
}
