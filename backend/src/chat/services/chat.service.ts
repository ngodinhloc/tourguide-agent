import { Injectable, NotFoundException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { v4 as uuidv4 } from 'uuid';
import { RedisService } from '../../redis/services/redis.service';
import { Conversation } from '../../database/entities/conversation.entity';
import { ChatInterface, ChatStatus, ChatActor, ChatMessage, AgentStatus } from '../contracts/chat.interface';
import { AgentService } from './agent.service';

@Injectable()
export class ChatService {
  constructor(
    @InjectRepository(Conversation)
    private readonly conversationRepo: Repository<Conversation>,
    private readonly redisService: RedisService,
    private readonly agentService: AgentService,
  ) {}

  private redisKey(id: string): string {
    return `chat:${id}`;
  }

  async newChat(message: string): Promise<{ id: string }> {
    const id = uuidv4();
    const chatObject: ChatInterface = {
      id,
      title: message,
      content: [{ actor: ChatActor.user, text: message, timestamp: new Date() }],
      status: ChatStatus.isActive,
      agentStatus: AgentStatus.isThinking,
    };
    const conversation = this.conversationRepo.create({
      uuid: id,
      title: message,
      content: chatObject.content as unknown as Record<string, unknown>,
    });
    await this.conversationRepo.save(conversation);
    await this.redisService.setJson(this.redisKey(id), chatObject);
    this.agentService.call(id, message);
    return { id };
  }

  async continueChat(id: string, message: string): Promise<{ accepted: true }> {
    const conversation = await this.conversationRepo.findOne({ where: { uuid: id } });
    if (!conversation) {
      throw new NotFoundException(`Conversation ${id} not found`);
    }

    const content = conversation.content as unknown as ChatMessage[];
    const existingMessages: ChatMessage[] = Array.isArray(content)
      ? content
      : [];

    const newMessage: ChatMessage = {
      actor: ChatActor.user,
      text: message,
      timestamp: new Date(),
    };

    const chatObject: ChatInterface = {
      id,
      title: conversation.title ?? null,
      content: [...existingMessages, newMessage],
      status: ChatStatus.isActive,
      agentStatus: AgentStatus.isThinking,
    };

    await this.redisService.setJson(this.redisKey(id), chatObject);
    this.agentService.call(id, message);
    return { accepted: true };
  }

  async stopChat(id: string): Promise<{ stopped: true }> {
    const current = await this.redisService.getJson<ChatInterface>(this.redisKey(id));
    if (!current) {
      throw new NotFoundException(`Conversation ${id} not found`);
    }

    const chatObject: ChatInterface = {
      ...current,
      status: ChatStatus.isStopped,
    };

    await this.conversationRepo.save({
      uuid: id,
      title: chatObject.title ?? undefined,
      content: chatObject as unknown as Record<string, unknown>,
    });

    await this.redisService.del(this.redisKey(id));
    return { stopped: true };
  }

  async getChat(id: string): Promise<ChatInterface> {
    const cached = await this.redisService.getJson<ChatInterface>(this.redisKey(id));
    if (cached) return cached;

    const conversation = await this.conversationRepo.findOne({ where: { uuid: id } });
    if (!conversation) {
      throw new NotFoundException(`Conversation ${id} not found`);
    }
    return conversation.content as unknown as ChatInterface;
  }

  async getHistory(): Promise<{ id: string; title: string; createdAt: Date }[]> {
    const conversations = await this.conversationRepo.find({
      order: { createdAt: 'DESC' },
      select: { uuid: true, title: true, createdAt: true },
    });
    return conversations.map((c) => ({ id: c.uuid, title: c.title ?? '', createdAt: c.createdAt }));
  }
}
