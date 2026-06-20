import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { ChatController } from './controllers/chat.controller';
import { ChatService } from './services/chat.service';
import { AgentService } from './services/agent.service';
import { ChatGateway } from './gateways/chat.gateway';
import { Conversation } from '../database/entities/conversation.entity';

@Module({
  imports: [TypeOrmModule.forFeature([Conversation])],
  controllers: [ChatController],
  providers: [ChatService, AgentService, ChatGateway],
})
export class ChatModule {}
