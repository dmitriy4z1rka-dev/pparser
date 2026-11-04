"""Create local credentials once. Never replace an existing installation's secrets."""
import os
import secrets
from pathlib import Path

from customize_crm import main as customize

ROOT = Path(__file__).resolve().parent.parent
customize()
target = ROOT / ".env"
if target.exists():
    print(".env уже существует; пароли сохранены. Настройки CRM обновлены.")
else:
    values = {
        "ADMIN_USER": "admin", "ADMIN_PASSWORD": secrets.token_urlsafe(24),
        "DB_PASSWORD": secrets.token_urlsafe(24), "DB_ROOT_PASSWORD": secrets.token_urlsafe(32),
        "ESPO_API_KEY": secrets.token_hex(24),
        "ESPO_PUBLIC_URL": "http://localhost:8080", "LEADGEN_PUBLIC_URL": "http://localhost:8090",
    }
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    print("Создан .env со служебными секретами (права 0600). Локальный интерфейс открывается без входа.")
print("Запуск: docker compose up -d --build")
print("Сбор компаний: http://localhost:8090 · CRM: http://localhost:8080")
