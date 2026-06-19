class RedisHelper:
    @staticmethod
    def chat_key(conversation_id: str) -> str:
        return f"chat:{conversation_id}"
