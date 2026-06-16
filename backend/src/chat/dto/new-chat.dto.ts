import { IsString, IsNotEmpty } from 'class-validator';

export class NewChatDto {
  @IsString()
  @IsNotEmpty()
  message: string;
}
