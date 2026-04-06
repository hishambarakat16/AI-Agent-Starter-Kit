from typing import Any, Dict
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from langfuse import get_client
lf = get_client()

def load_langfuse_prompt_and_config(prompt: str) -> Dict[str, Any]:
    p = lf.get_prompt(prompt, type="chat")
    
    langchain_prompt = ChatPromptTemplate.from_messages(p.get_langchain_prompt())
    langchain_prompt.metadata = {"langfuse_prompt": p}
    
    return {
        "prompt": langchain_prompt,
        "model": p.config.get("model"),
        "temperature": p.config.get("temperature"),
    }