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
      content: [{ actor: ChatActor.user, text: message, timestamp: new Date(), type: 'text' }],
      status: ChatStatus.isActive,
      agentStatus: AgentStatus.isThinking,
    };
    const conversation = this.conversationRepo.create({
      uuid: id,
      title: message,
      content: chatObject.content as unknown as Record<string, unknown>[],
    });
    await this.conversationRepo.save(conversation);
    await this.redisService.setJson(this.redisKey(id), chatObject);
    this.agentService.call(id, message, []);
    return { id };
  }

  async continueChat(id: string, message: string): Promise<{ accepted: true }> {
    let existingMessages: ChatMessage[];
    let title: string | null = null;

    const cached = await this.redisService.getJson<ChatInterface>(this.redisKey(id));
    if (cached) {
      existingMessages = cached.content ?? [];
      title = cached.title ?? null;
    } else {
      const conversation = await this.conversationRepo.findOne({ where: { uuid: id } });
      if (!conversation) {
        throw new NotFoundException(`Conversation ${id} not found`);
      }
      existingMessages = conversation.content as unknown as ChatMessage[];
      title = conversation.title ?? null;
    }

    const newMessage: ChatMessage = {
      actor: ChatActor.user,
      text: message,
      timestamp: new Date(),
      type: 'text',
    };

    const chatObject: ChatInterface = {
      id,
      title,
      content: [...existingMessages, newMessage],
      status: ChatStatus.isActive,
      agentStatus: AgentStatus.isThinking,
    };

    await this.redisService.setJson(this.redisKey(id), chatObject);
    this.agentService.call(id, message, existingMessages);
    return { accepted: true };
  }

  async stopChat(id: string): Promise<{ stopped: true }> {
    const current = await this.redisService.getJson<ChatInterface>(this.redisKey(id));
    if (!current) {
      throw new NotFoundException(`Conversation ${id} not found`);
    }

    await this.conversationRepo.save({
      uuid: id,
      title: current.title ?? undefined,
      content: current.content as unknown as Record<string, unknown>[],
    });

    await this.redisService.del(this.redisKey(id));
    return { stopped: true };
  }

  async getChat(id: string): Promise<ChatInterface> {
    const cached = await this.redisService.getJson<ChatInterface>(this.redisKey(id));
    if (cached) {
      if (cached.agentStatus === AgentStatus.hasReplied) {
        this.conversationRepo.update(
          { uuid: id },
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          { content: cached.content } as any,
        ).catch(() => {});
      }
      return cached;
    }

    const conversation = await this.conversationRepo.findOne({ where: { uuid: id } });
    if (!conversation) {
      throw new NotFoundException(`Conversation ${id} not found`);
    }

    return {
      id: conversation.uuid,
      title: conversation.title,
      content: conversation.content as unknown as ChatMessage[],
      status: ChatStatus.isStopped,
      agentStatus: AgentStatus.hasReplied,
    };
  }

  async getHistory(): Promise<{ id: string; title: string; createdAt: Date }[]> {
    const conversations = await this.conversationRepo.find({
      order: { createdAt: 'DESC' },
      select: { uuid: true, title: true, createdAt: true },
    });
    return conversations.map((c) => ({ id: c.uuid, title: c.title ?? '', createdAt: c.createdAt }));
  }
}
