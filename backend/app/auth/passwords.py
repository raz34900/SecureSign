from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def verify_password(hash_: str, pw: str) -> bool:
    try:
        return _hasher.verify(hash_, pw)
    except VerifyMismatchError:
        return False
