from typing import Any

from pydantic import BaseModel, ConfigDict, Field

ALLOWED_SETTINGS = {"think", "save_chat_history", "preview_thinking", "theme", "auto_scroll"}

class SettingsPayload(BaseModel):
    think: bool | None = None
    save_chat_history: bool | None = None
    preview_thinking: str | None = Field(None, pattern=r"^(summary|full|hidden)$")
    theme: str | None = Field(None, pattern=r"^(light|dark|system)$")
    auto_scroll: bool | None = None

    model_config = ConfigDict(extra="forbid")

class ModelfilePayload(BaseModel):
    system_prompt: str | None = None
    num_ctx: float | int | str | None = None
    num_predict: float | int | str | None = None
    temperature: float | int | str | None = None
    top_k: float | int | str | None = None
    top_p: float | int | str | None = None
    repeat_penalty: float | int | str | None = None

    model_config = ConfigDict(extra="forbid")

class UnloadPayload(BaseModel):
    model: str = Field(..., max_length=128)

class ProposeCommandPayload(BaseModel):
    command: str = Field(..., max_length=4096)
    working_dir: str | None = None

class ExecuteCommandPayload(BaseModel):
    command: str = Field(..., max_length=4096)
    working_dir: str | None = None
    approval_token: str = Field(..., min_length=16, max_length=128)
    user_authorization: str | None = None
    approved: bool | None = None

class ChatMessagePayload(BaseModel):
    role: str = Field(..., pattern=r"^(user|assistant|system)$")
    content: str = ""
    images: list[str] = Field(default_factory=list)

class DashboardChatPayload(BaseModel):
    model: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    prompt: str | None = None
    images: list[str] = Field(default_factory=list)
    think: bool = False
