import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { HttpModule } from '@nestjs/axios';
import { ChatController } from './controllers/chat.controller';
import { ChatService } from './services/chat.service';
import { AgentService } from './services/agent.service';
import { Conversation } from '../database/entities/conversation.entity';

@Module({
  imports: [
    TypeOrmModule.forFeature([Conversation]),
    HttpModule.registerAsync({
      useFactory: () => ({
        timeout: 120_000,
        maxRedirects: 0,
      }),
    }),
  ],
  controllers: [ChatController],
  providers: [ChatService, AgentService],
})
export class ChatModule {}
