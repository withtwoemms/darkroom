"""The Push API the exam supplies: its options, its keys, its script.

The option's worth rests on two claims, and both are checked here.
The key material is real — the public half is a P-256 point a sender
can encrypt to and the private half opens what comes back, so a
tenant's server is talking to something indistinguishable from a
browser's subscription. And the private half never reaches the page:
it goes to the drive context alone, which is what lets a `command`
step read a payload the page could not.
"""

import base64
import hmac
import json
import os
import struct
from hashlib import sha256

import pytest

from darkroom.adapter import loads_adapter
from darkroom.drive import Context, DriveError
from darkroom.pushstub import (
    PUSH_DEFAULT_ENDPOINT_HOST,
    drive_values,
    init_script,
    key_material,
    resolve_options,
)

cryptography = pytest.importorskip("cryptography")


def b64url_decode(text: str) -> bytes:
    assert "=" not in text, "web push key material is base64url, unpadded"
    assert "+" not in text and "/" not in text, "base64url, not standard base64"
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def noop(text: str) -> str:
    return text


class TestKeyMaterial:
    def test_the_public_half_is_an_uncompressed_p256_point(self):
        p256dh, auth, private = key_material()
        point = b64url_decode(p256dh)
        # 0x04 then two 32-byte coordinates: what a browser hands a page
        assert len(point) == 65
        assert point[0] == 0x04
        assert len(b64url_decode(auth)) == 16
        assert len(b64url_decode(private)) == 32

    def test_the_private_half_matches_the_public_one(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PublicFormat,
        )

        p256dh, _, private = key_material()
        derived = ec.derive_private_key(
            int.from_bytes(b64url_decode(private), "big"), ec.SECP256R1()
        )
        assert derived.public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint
        ) == b64url_decode(p256dh)

    def test_without_the_crypto_extra_it_says_which_extra(self, monkeypatch):
        import sys

        monkeypatch.setitem(
            sys.modules, "cryptography.hazmat.primitives.asymmetric", None
        )
        with pytest.raises(DriveError, match=r"crypto extra.*darkroom-ai\[crypto\]"):
            key_material()

    def test_each_session_gets_its_own(self):
        first, second = key_material(), key_material()
        assert first[0] != second[0] and first[1] != second[1]

    def test_a_sender_can_encrypt_to_it_and_the_drive_can_open_it(self):
        """RFC 8291 end to end — the reason the private half is published.

        A tenant's server encrypts to the subscription it was handed;
        the drive opens the body with ``{push.private}`` and
        ``{push.auth}`` and reads the plaintext. If the curve or the
        encoding were wrong this is where it would show.
        """
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PublicFormat,
        )

        def expand(prk, info, length):
            return hmac.new(prk, info + b"\x01", sha256).digest()[:length]

        def derive(auth_secret, shared, ua_public, as_public, salt):
            prk_key = hmac.new(auth_secret, shared, sha256).digest()
            ikm = expand(
                prk_key, b"WebPush: info\x00" + ua_public + as_public, 32
            )
            prk = hmac.new(salt, ikm, sha256).digest()
            return (
                expand(prk, b"Content-Encoding: aes128gcm\x00", 16),
                expand(prk, b"Content-Encoding: nonce\x00", 12),
            )

        p256dh, auth, private = key_material()
        ua_public, auth_secret = b64url_decode(p256dh), b64url_decode(auth)

        # the sender's side
        sender = ec.generate_private_key(ec.SECP256R1())
        as_public = sender.public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint
        )
        salt = os.urandom(16)
        cek, nonce = derive(
            auth_secret,
            sender.exchange(
                ec.ECDH(),
                ec.EllipticCurvePublicKey.from_encoded_point(
                    ec.SECP256R1(), ua_public
                ),
            ),
            ua_public,
            as_public,
            salt,
        )
        sealed = AESGCM(cek).encrypt(nonce, b"someone is asking\x02", None)
        body = (
            salt
            + struct.pack("!L", 4096)
            + bytes([len(as_public)])
            + as_public
            + sealed
        )

        # the drive's side, holding only what the context published
        receiver = ec.derive_private_key(
            int.from_bytes(b64url_decode(private), "big"), ec.SECP256R1()
        )
        salt_in, idlen = body[:16], body[20]
        as_public_in, sealed_in = body[21 : 21 + idlen], body[21 + idlen :]
        cek_in, nonce_in = derive(
            auth_secret,
            receiver.exchange(
                ec.ECDH(),
                ec.EllipticCurvePublicKey.from_encoded_point(
                    ec.SECP256R1(), as_public_in
                ),
            ),
            receiver.public_key().public_bytes(
                Encoding.X962, PublicFormat.UncompressedPoint
            ),
            as_public_in,
            salt_in,
        )
        opened = AESGCM(cek_in).decrypt(nonce_in, sealed_in, None)
        assert opened.rstrip(b"\x02") == b"someone is asking"


class TestResolveOptions:
    def test_unasked_is_no_configuration(self):
        assert resolve_options(None, noop) is None
        assert resolve_options(False, noop) is None

    def test_true_takes_the_defaults(self):
        push = resolve_options(True, noop)
        assert push["permission"] == "granted"
        assert push["endpoint"].startswith(PUSH_DEFAULT_ENDPOINT_HOST + "/")

    def test_the_default_endpoint_can_reach_nothing(self):
        # a reserved TLD: a scenario that only drives the control's
        # states never addresses a real host by accident
        assert resolve_options(True, noop)["endpoint"].startswith("https://push.darkroom.invalid/")
        assert resolve_options(True, noop)["endpoint"] != resolve_options(True, noop)["endpoint"]

    def test_the_endpoint_resolves_drive_values(self):
        # a declared service's address is already a drive value when the
        # session is built, so the endpoint can point at a collector
        ctx = Context({"collector.host": "127.0.0.1", "collector.port": "32790"})
        push = resolve_options(
            {"endpoint": "http://{collector.host}:{collector.port}/push/one"},
            ctx.interpolate,
        )
        assert push["endpoint"] == "http://127.0.0.1:32790/push/one"

    def test_an_endpoint_naming_nothing_the_drive_knows_is_an_error(self):
        with pytest.raises(DriveError, match="unknown placeholder"):
            resolve_options(
                {"endpoint": "http://{collector.host}/push"}, Context().interpolate
            )

    @pytest.mark.parametrize("permission", ["granted", "denied", "default"])
    def test_the_three_permission_states(self, permission):
        assert resolve_options({"permission": permission}, noop)["permission"] == permission

    def test_an_unknown_permission_is_refused(self):
        with pytest.raises(DriveError, match="permission must be one of"):
            resolve_options({"permission": "maybe"}, noop)

    def test_an_unknown_field_is_refused(self):
        with pytest.raises(DriveError, match="does not know subscribed"):
            resolve_options({"subscribed": True}, noop)

    def test_a_scalar_other_than_true_is_refused(self):
        with pytest.raises(DriveError, match="must be true or a table"):
            resolve_options("yes", noop)

    def test_the_context_gets_the_endpoint_and_both_halves(self):
        push = resolve_options(True, noop)
        values = drive_values(push)
        assert set(values) == {
            "push.endpoint",
            "push.p256dh",
            "push.auth",
            "push.private",
        }
        assert values["push.private"] == push["private"]


class TestInitScript:
    def test_the_page_is_handed_the_public_half_and_never_the_private(self):
        push = resolve_options(True, noop)
        script = init_script(push)
        assert push["p256dh"] in script
        assert push["auth"] in script
        assert push["endpoint"] in script
        # the drive's ear, not the page's: the private half is what
        # makes a payload readable, and the page has no business with it
        assert push["private"] not in script

    def test_the_configuration_is_embedded_as_json(self):
        push = resolve_options({"permission": "denied"}, noop)
        script = init_script(push)
        start = script.index("{", script.index("const CFG ="))
        end = script.index("};", start)
        config = json.loads(script[start : end + 1])
        assert config == {
            "endpoint": push["endpoint"],
            "p256dh": push["p256dh"],
            "auth": push["auth"],
            "permission": "denied",
        }

    def test_it_covers_the_surface_a_notifying_page_reaches_for(self):
        script = init_script(resolve_options(True, noop))
        for member in (
            "serviceWorker",
            "register",
            "pushManager",
            "subscribe",
            "getSubscription",
            "unsubscribe",
            "permissionState",
            "requestPermission",
            "showNotification",
            "toJSON",
            "getKey",
        ):
            assert member in script, member


class TestBrowserDefaults:
    def test_push_rides_the_browser_table_like_webauthn(self, tmp_path):
        adapter = loads_adapter(
            """
            [project]
            name = "notifier"

            [browser.defaults]
            webauthn = true
            push = { permission = "granted" }
            """,
            root=tmp_path,
        )
        assert adapter.browser_options(None)["push"] == {"permission": "granted"}
        # an exposure about the refused state overrides the whole table
        overridden = adapter.browser_options({"push": {"permission": "denied"}})
        assert overridden["push"] == {"permission": "denied"}
        assert overridden["webauthn"] is True
