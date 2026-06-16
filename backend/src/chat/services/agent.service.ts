import { Injectable, Logger } from '@nestjs/common';
import { HttpService } from '@nestjs/axios';

@Injectable()
export class AgentService {
  private readonly logger = new Logger(AgentService.name);
  private readonly aiAgentUrl: string;

  constructor(private readonly httpService: HttpService) {
    this.aiAgentUrl = process.env.AI_AGENT_URL ?? 'http://localhost:8001';
  }

  call(id: string, message: string): void {
    this.httpService
      .post(`${this.aiAgentUrl}/api/chat`, { message, conversationId: id })
      .subscribe({
        error: (err: unknown) => {
          const errorMessage = err instanceof Error ? err.message : String(err);
          this.logger.error(`AI call failed for conversation ${id}: ${errorMessage}`);
        },
      });
  }
}
