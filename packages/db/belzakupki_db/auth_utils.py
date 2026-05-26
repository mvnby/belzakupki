"""Вспомогательные утилиты для хеширования и проверки паролей.

Использует PBKDF2-HMAC-SHA256 из стандартной библиотеки Python для обеспечения безопасности
без привязки к бинарным компилируемым зависимостям (таким как bcrypt).
"""
import hashlib
import secrets

def hash_password(password: str) -> str:
    """Хеширует пароль с использованием PBKDF2-HMAC-SHA256 и случайной соли."""
    salt = secrets.token_hex(16)
    iterations = 100000
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        iterations
    )
    return f"pbkdf2_sha256${iterations}${salt}${key.hex()}"

def verify_password(password: str, hashed_password: str) -> bool:
    """Сравнивает сырой пароль с сохраненным хешем."""
    try:
        parts = hashed_password.split('$')
        if len(parts) != 4 or parts[0] != 'pbkdf2_sha256':
            return False
        iterations = int(parts[1])
        salt = parts[2]
        original_key = parts[3]
        
        new_key = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            iterations
        )
        return secrets.compare_digest(new_key.hex(), original_key)
    except Exception:
        return False
