"""Local Crusoe configuration, without credentials in printable objects."""

from dataclasses import dataclass, field
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    model: str
    base_url: str = "https://api.inference.crusoecloud.com/v1"
    max_tokens: int = 1024
    timeout: float = 45

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        api_key = os.environ.get("CRUSOE_API_KEY", "")
        model = os.environ.get("CRUSOE_MODEL", "")
        if not api_key or not model:
            raise ValueError("Set CRUSOE_API_KEY and CRUSOE_MODEL in .env or the environment")
        result = cls(
            api_key=api_key,
            model=model,
            base_url=os.environ.get("CRUSOE_BASE_URL", cls.base_url).rstrip("/"),
            max_tokens=int(os.environ.get("CRUSOE_MAX_TOKENS", "1024")),
            timeout=float(os.environ.get("CRUSOE_TIMEOUT_SECONDS", "45")),
        )
        if not result.base_url.startswith("https://"):
            raise ValueError("Crusoe inference must use HTTPS")
        if not 1 <= result.max_tokens <= 8192 or not 0 < result.timeout <= 120:
            raise ValueError("Invalid token or timeout limit")
        return result

    def chat_model(self) -> ChatOpenAI:
        return ChatOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            temperature=0,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
            max_retries=0,
            use_responses_api=False,
            tiktoken_model_name="cl100k_base",
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
