# owner: Khoi (P1-3 password hashing, jwt creation, and get_current_user dependency)
from models import User


def hash_password(plain_password: str) -> str:
    raise NotImplementedError


def verify_password(plain_password: str, hashed_password: str) -> bool:
    raise NotImplementedError


def create_access_token(user_id: int) -> str:
    raise NotImplementedError
