
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
    content: str = Field(default="", max_length=65536)
    images: list[str] = Field(default_factory=list, max_length=10)

    model_config = ConfigDict(extra="ignore")

class DashboardChatPayload(BaseModel):
    model: str | None = Field(default=None, max_length=128, pattern=r"^[a-zA-Z0-9_\-\.:/]+$")
    messages: list[ChatMessagePayload] = Field(default_factory=list, max_length=100)
    prompt: str | None = Field(default=None, max_length=65536)
    images: list[str] = Field(default_factory=list, max_length=10)
    think: bool = False
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    stream: bool = True

    model_config = ConfigDict(extra="ignore")

class HistoryQuery(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    model: str | None = Field(default=None, max_length=128)
