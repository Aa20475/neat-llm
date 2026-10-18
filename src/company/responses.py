"""Reject unfinished provider responses before treating them as agent results."""


class IncompleteResponse(ValueError):
    pass


def require_complete_response(message, *, max_tokens=None, finish_reason=None):
    reason = finish_reason or message.response_metadata.get("finish_reason")
    usage = message.usage_metadata or {}
    if reason in ("length", "max_tokens") or (
        reason is None and max_tokens and usage.get("output_tokens", 0) >= max_tokens
    ):
        raise IncompleteResponse(
            "The model reached its response token limit before finishing. "
            "Saved project files and the partial trace are preserved; this task is incomplete."
        )
    if reason == "content_filter":
        raise IncompleteResponse("The provider filtered the response before completion.")
    if not message.text.strip() and not message.tool_calls:
        raise IncompleteResponse("The model returned no final answer or tool call.")
