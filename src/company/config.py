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
    max_tokens: int | None = None
    timeout: float = 45
    enable_thinking: bool | None = None
    reasoning_effort: str | None = None

    def __post_init__(self):
        if self.max_tokens is not None and (type(self.max_tokens) is not int or self.max_tokens < 1):
            raise ValueError("Output token limit must be a positive integer or None")
        # GLM-5.3 always reasons. The disabled-thinking setting mixed reasoning
        # into answer content in a Crusoe probe; enable it and use low effort.
        glm53 = self.model.rsplit("/", 1)[-1].lower().startswith("glm-5.3")
        if self.enable_thinking is None:
            object.__setattr__(self, "enable_thinking", glm53)
        if self.reasoning_effort is None and glm53 and self.enable_thinking:
            object.__setattr__(self, "reasoning_effort", "low")

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        api_key = os.environ.get("CRUSOE_API_KEY", "")
        model = os.environ.get("CRUSOE_MODEL", "")
        if not api_key or not model:
            raise ValueError("Set CRUSOE_API_KEY and CRUSOE_MODEL in .env or the environment")
        token_setting = os.environ.get("CRUSOE_MAX_TOKENS", "").strip().lower()
        result = cls(
            api_key=api_key,
            model=model,
            base_url=os.environ.get("CRUSOE_BASE_URL", cls.base_url).rstrip("/"),
            max_tokens=None if token_setting in ("", "none", "unlimited") else int(token_setting),
            timeout=float(os.environ.get("CRUSOE_TIMEOUT_SECONDS", "45")),
        )
        if not result.base_url.startswith("https://"):
            raise ValueError("Crusoe inference must use HTTPS")
        if not 0 < result.timeout <= 120:
            raise ValueError("Invalid timeout limit")
        return result

    def chat_model(self) -> ChatOpenAI:
        template = {"enable_thinking": self.enable_thinking}
        if self.reasoning_effort:
            template["reasoning_effort"] = self.reasoning_effort
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
            extra_body={"chat_template_kwargs": template},
        )
