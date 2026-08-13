"""Configuração da aplicação, lida de variáveis de ambiente (.env)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração central do serviço, populada a partir do .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Banco de dados
    DATABASE_URL: str

    # Agendamento
    SCAN_CRON: str = "0 8-20 * * 1-5"
    TZ: str = "America/Sao_Paulo"

    # SMTP (MailGrid)
    SMTP_HOST: str
    SMTP_PORT: int = 587
    SMTP_USER: str
    SMTP_PASSWORD: str
    SMTP_TLS: bool = True
    MAIL_FROM: str
    MAIL_TO: str

    # Anexos e retenção
    MAX_ATTACH_MB: int = 15
    RETENTION_DAYS: int = 3

    # Reservado para integração futura com o SaaS Lupa (Django) via JWT.
    # Não usado no MVP.
    JWT_SECRET: str = ""


settings = Settings()
