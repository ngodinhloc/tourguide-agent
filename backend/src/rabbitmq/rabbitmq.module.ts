import { Global, Module } from '@nestjs/common';
import { RabbitMQService } from './services/rabbitmq.service';

@Global()
@Module({
  providers: [RabbitMQService],
  exports: [RabbitMQService],
})
export class RabbitMQModule {}
