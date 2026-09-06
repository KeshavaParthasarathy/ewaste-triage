from server.phone_sessions import PhoneSessionManager


class FakeClock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def test_session_uses_random_token_short_code_bracketed_ipv6_url_and_expiry():
    clock = FakeClock()
    sessions = PhoneSessionManager(now=clock, ttl_seconds=600)

    session = sessions.start(host="2001:db8:1::12", port=9012)

    assert len(session.token) >= 43
    assert session.pairing_code.isdigit() and len(session.pairing_code) == 6
    assert session.upload_url == f"http://[2001:db8:1::12]:9012/phone?token={session.token}"
    clock.advance(601)
    assert sessions.active() is None


def test_successful_activity_refreshes_inactivity_deadline():
    clock = FakeClock()
    sessions = PhoneSessionManager(now=clock, ttl_seconds=600)
    session = sessions.start(host="192.168.1.12", port=9012)

    clock.advance(500)
    refreshed = sessions.touch(session.token)

    assert refreshed is not None
    assert refreshed.created_at == 100.0
    assert refreshed.expires_at == 1200.0
    clock.advance(599)
    assert sessions.active() == refreshed
    clock.advance(2)
    assert sessions.active() is None


def test_stop_and_replacement_revoke_prior_capabilities():
    sessions = PhoneSessionManager(now=FakeClock(), ttl_seconds=600)
    old_session = sessions.start(host="192.168.1.12", port=9012)
    new_session = sessions.start(host="192.168.1.13", port=9013)

    assert not sessions.authorize(old_session.token)
    assert sessions.authorize(new_session.token, new_session.pairing_code)
    assert not sessions.authorize(new_session.token, "000000")
    sessions.stop()
    assert not sessions.authorize(new_session.token)
    assert sessions.active() is None
