import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()

# No l, I, 1, O or 0: this gets read aloud or copied off a screen, and a character nobody
# can transcribe becomes a support call and then a weaker password chosen to avoid it.
_HANDOVER_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_HANDOVER_GROUPS = 4
_HANDOVER_GROUP_SIZE = 4


def generate_handover_password() -> str:
    """A one-time password nobody chose.

    Whoever creates an account should not be able to pick what it opens with. Left to a
    person the first password is `12341234aa` on every account in the building, and until
    each owner signs in and replaces it that is a single guess away — which is exactly
    the window a new, unused account sits in.

    Sixteen characters from a 31-symbol alphabet is about 79 bits, grouped so it can be
    read out once and typed once.
    """
    return "-".join("".join(secrets.choice(_HANDOVER_ALPHABET)
                            for _ in range(_HANDOVER_GROUP_SIZE))
                    for _ in range(_HANDOVER_GROUPS))


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def verify_password(hash_: str, pw: str) -> bool:
    try:
        return _hasher.verify(hash_, pw)
    except VerifyMismatchError:
        return False
