"""伺服器設定：全部來自環境變數（前綴 BUZZER_）或 .env 檔。"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "BUZZER_"
DEFAULT_HOST = "127.0.0.1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    teacher_password: SecretStr | None = None
    host: str = DEFAULT_HOST
    port: int = Field(default=8000, ge=1, le=65535)
    data_dir: Path = Path("./data")

    max_questions: int = Field(default=500, ge=1, le=100_000)

    google_client_secrets: Path | None = None   # 未設定時為 <資料目錄>/google-client-secret.json
    google_token_file: Path | None = None       # 未設定時為 <資料目錄>/google-token.json
    google_timeout_seconds: float = Field(default=10, gt=0, le=300)

    label_no: str = "題號"
    label_question: str = "題目"
    label_answer: str = "作答"

    # 老師登入：全體共用一個失敗計數（與 SpecKit 組一致）
    login_max_failures: int = Field(default=5, ge=1, le=1000)
    login_lock_seconds: int = Field(default=300, ge=1, le=86_400)
    # 輸入組別代碼：以視窗為單位的鎖定，加上全體最近 60 秒的失敗上限（與 SpecKit 組一致）
    lockout_max_failures: int = Field(default=5, ge=1, le=1000)
    lockout_seconds: int = Field(default=60, ge=1, le=86_400)
    join_global_max_failures: int = Field(default=60, ge=1, le=100_000)
    token_ttl_hours: int = Field(default=8, ge=1, le=24 * 30)

    # 搶答活動
    max_teams: int = Field(default=20, ge=1, le=1000)
    team_name_max: int = Field(default=20, ge=1, le=1000)
    max_answer_length: int = Field(default=200, ge=1, le=100_000)
    fairness_enabled: bool = True
    cooldown_seconds: int = Field(default=10, ge=1, le=600)
    cooldown_lead: int = Field(default=2, ge=1, le=100)
    ws_auth_timeout_seconds: float = Field(default=5, ge=0.1, le=60)

    @field_validator("label_no", "label_question", "label_answer", "host")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @model_validator(mode="after")
    def _labels_distinct(self) -> "Settings":
        labels = [self.label_no, self.label_question, self.label_answer]
        if len(set(labels)) != len(labels):
            raise ValueError("labels must be distinct")
        return self

    @property
    def google_client_secrets_path(self) -> Path:
        return self.google_client_secrets or Path(self.data_dir) / "google-client-secret.json"

    @property
    def google_token_path(self) -> Path:
        return self.google_token_file or Path(self.data_dir) / "google-token.json"

    @property
    def token_ttl_seconds(self) -> int:
        return self.token_ttl_hours * 3600

    def has_teacher_password(self) -> bool:
        if self.teacher_password is None:
            return False
        return self.teacher_password.get_secret_value().strip() != ""


_LABEL_FIELDS = ("label_no", "label_question", "label_answer")


def env_name(field: str) -> str:
    return f"{ENV_PREFIX}{field.upper()}"


def invalid_setting_names(error: ValidationError) -> list[str]:
    """把驗證錯誤轉成環境變數名稱清單（不含任何設定值）。"""
    names: set[str] = set()
    for item in error.errors():
        loc = item.get("loc") or ()
        if loc and isinstance(loc[0], str):
            names.add(env_name(loc[0]))
        else:  # 跨欄位驗證（例如表頭標籤重複）
            names.update(env_name(f) for f in _LABEL_FIELDS)
    return sorted(names)


MISSING_PASSWORD_MESSAGE = (
    f"未設定老師密碼（{env_name('teacher_password')}），伺服器無法啟動"
)


class StartupError(RuntimeError):
    """伺服器無法啟動；訊息為繁體中文且不含機敏值。"""
