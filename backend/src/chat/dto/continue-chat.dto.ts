import { IsString, IsNotEmpty } from 'class-validator';

export class ContinueChatDto {
  @IsString()
  @IsNotEmpty()
  message: string;
}
