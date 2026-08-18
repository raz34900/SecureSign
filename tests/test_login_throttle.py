"""Sign-in throttling.

Without this, a password is only as good as the number of guesses an attacker is willing
to make, and the engineering account is reachable from the public entrypoint. The limit
is keyed on the account rather than the caller because the API cannot see the caller:
behind Docker every request arrives from the nginx container.
"""
from backend.app.auth.throttle import MAX_ATTEMPTS, WINDOW_SECONDS
from conftest import login


def wrong(client, org="BA11", username="clerk1"):
    return login(client, org, username, password="not-the-password")


def test_a_run_of_wrong_passwords_is_cut_off(client, seeded):
    for attempt in range(MAX_ATTEMPTS):
        assert wrong(client).status_code == 401, f"blocked early at attempt {attempt + 1}"

    refused = wrong(client)
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
    assert 0 < int(refused.headers["retry-after"]) <= WINDOW_SECONDS


def test_the_right_password_is_refused_too_once_the_run_is_cut_off(client, seeded):
    """The point of the limit. If the correct password still worked, an attacker who
    found it on the last guess would be let in."""
    for _ in range(MAX_ATTEMPTS):
        wrong(client)
    assert login(client, "BA11", "clerk1").status_code == 429


def test_signing_in_correctly_ends_the_run(client, seeded):
    for _ in range(MAX_ATTEMPTS - 1):
        assert wrong(client).status_code == 401
    assert login(client, "BA11", "clerk1").status_code == 200

    client.cookies.clear()
    for _ in range(MAX_ATTEMPTS - 1):
        assert wrong(client).status_code == 401, "the allowance was not reset"


def test_one_account_cannot_lock_another_out(client, seeded):
    for _ in range(MAX_ATTEMPTS + 1):
        wrong(client, username="clerk1")
    assert wrong(client, username="rep1", org="SB44").status_code == 401
    assert login(client, "SB44", "rep1").status_code == 200


def test_an_account_that_does_not_exist_throttles_identically(client, seeded):
    """Throttling only real accounts would answer 429 for names that exist and 401 for
    names that do not, which tells an attacker which usernames are worth attacking."""
    for _ in range(MAX_ATTEMPTS):
        assert login(client, "BA11", "ghost", password="whatever").status_code == 401
    assert login(client, "BA11", "ghost", password="whatever").status_code == 429


def test_the_store_cannot_be_grown_without_bound(client, seeded):
    """The endpoint is unauthenticated, so an attacker choosing a fresh username every
    time must not be able to consume memory."""
    from backend.app.auth import throttle

    for index in range(throttle.MAX_TRACKED + 50):
        throttle.record_failure("BA11", f"user{index}")
    assert len(throttle._failures) <= throttle.MAX_TRACKED


def test_a_flood_of_junk_usernames_cannot_unlock_a_victim(client, seeded):
    """The store is bounded, so something has to give when it fills. It must not be a
    locked account: a locked account stops generating attempts, so under an
    evict-the-oldest policy it ages out fastest and a flood of junk clears any lock.
    Reproduced against the earlier policy — victim went from 899 seconds to 0."""
    from backend.app.auth import throttle

    for _ in range(throttle.MAX_ATTEMPTS):
        wrong(client)
    locked = throttle.retry_after("BA11", "clerk1")
    assert locked > 0

    for index in range(throttle.MAX_TRACKED + 100):
        throttle.record_failure("XX99", f"junk{index}")

    assert throttle.retry_after("BA11", "clerk1") > 0, "the flood unlocked the victim"
    assert len(throttle._failures) <= throttle.MAX_TRACKED


def test_a_saturated_store_refuses_rather_than_forgets(client, seeded):
    """Full means full. Refusing new accounts while a flood is in progress is a cost;
    letting the flood through unthrottled is worse."""
    from backend.app.auth import throttle

    for index in range(throttle.MAX_TRACKED):
        throttle.record_failure("XX99", f"junk{index}")
    assert throttle.retry_after("BA11", "someone-new") == throttle.WINDOW_SECONDS
