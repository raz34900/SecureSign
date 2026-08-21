"""The one place a customer's data encryption key is minted, unwrapped or destroyed."""
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models_db import CustomerKey
from backend.app.security import envelope


def key_for(db: Session, customer_id: str) -> bytes:
    """The customer's data encryption key, creating one on first use.

    Callers get the bare key and must not store it. It exists to encrypt or decrypt one
    image and then go out of scope.
    """
    settings = get_settings()
    row = db.get(CustomerKey, customer_id)
    if row is None:
        dek = envelope.new_dek()
        db.add(CustomerKey(customer_id=customer_id,
                           wrapped_dek=envelope.wrap_dek(dek, settings.pii_enc_key)))
        db.flush()
        return dek
    return envelope.unwrap_dek(row.wrapped_dek, settings.pii_enc_key)


def existing_key_for(db: Session, customer_id: str) -> bytes | None:
    """None when there is no key — either nothing was ever encrypted for this customer,
    or the key was destroyed and the images are gone for good."""
    row = db.get(CustomerKey, customer_id)
    if row is None:
        return None
    return envelope.unwrap_dek(row.wrapped_dek, get_settings().pii_enc_key)


def destroy(db: Session, customer_id: str) -> bool:
    """Crypto-shredding. Returns whether there was a key to destroy.

    The ciphertext is deliberately left alone. Overwriting rows would only reach the live
    database, while dropping the key reaches every copy of that ciphertext that has ever
    been taken, which is the only erasure a backup cannot quietly undo.
    """
    row = db.get(CustomerKey, customer_id)
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True
