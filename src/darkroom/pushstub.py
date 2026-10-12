"""The Push API the exam supplies, as the virtual authenticator is.

A tenant that notifies cannot be driven end to end by a headless
browser: turning notifications on means the page asks the browser to
subscribe, and the browser hands that to a real push service (FCM,
Mozilla's autopush, Apple's). There is none in an exam, so the call
fails and every scenario about the control's states dies at the first
click.

The alternative — a flag in the product that fakes a subscription
under exam posture — puts a permanent hazard in production code
(anything that lets a client register an arbitrary push address for a
member) and obliges the tenant to prove the flag's surface is absent
when unset. darkroom already refused that shape for passkeys: nobody
adds a product bridge to drive WebAuthn, the engine asks the browser
for a virtual authenticator. Push gets the same treatment. The EXAM
supplies the missing platform piece; the product never learns it was
a test.

What the stub answers for:

* ``navigator.serviceWorker.register`` fetches the tenant's real
  worker file (so the request lands in its log, and a missing file
  still fails) and resolves with a registration whose ``pushManager``
  is the stub.
* ``pushManager.subscribe`` resolves with a subscription at the
  configured endpoint, carrying a ``p256dh`` and an ``auth`` this
  module generates; ``getSubscription`` reads it back, across a reload
  as a real browser would; ``unsubscribe`` drops it.
* ``Notification.permission`` / ``requestPermission`` answer the
  configured permission, and anything but ``granted`` makes
  ``subscribe`` reject the way a browser does — so "this phone has
  refused" is a reachable state.

The keypair is real: P-256, the curve RFC 8291 encryption is defined
over, which is what the ``p256dh`` name has always meant. The PUBLIC
half and the auth secret are what the stub hands the page, so they
travel to the tenant's server exactly as a browser's would. The
PRIVATE half reaches the drive context deliberately, so a ``command``
step can open what the tenant's server sent to a collector and assert
on the plaintext — without that, the most important criterion a
notifying tenant has (that the body names nothing it shouldn't) is
unprovable.

What it does not do: deliver a notification, show one, or prove a real
browser ever reached a real push service. Those stay outside every
driver and belong beside a gate as manual checks.
"""

from __future__ import annotations

import base64
import json
import secrets

__all__ = [
    "PUSH_DEFAULT_ENDPOINT_HOST",
    "PUSH_PERMISSIONS",
    "key_material",
    "init_script",
    "resolve_options",
]

# a reserved TLD (RFC 2606): the default endpoint can never reach
# anything, which is what a scenario that only drives the control's
# states wants
PUSH_DEFAULT_ENDPOINT_HOST = "https://push.darkroom.invalid"

PUSH_PERMISSIONS = ("granted", "denied", "default")


def _b64url(raw: bytes) -> str:
    """base64url without padding — how Web Push carries key material."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def key_material() -> tuple[str, str, str]:
    """A real subscription's key material: ``(p256dh, auth, private)``.

    ``p256dh`` is the uncompressed P-256 public point (65 bytes) and
    ``auth`` a 16-byte secret, both as a browser would hand them to a
    page; ``private`` is the matching private scalar (32 bytes), for
    the drive's own decryption. All base64url, unpadded.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PublicFormat,
        )
    except ImportError:
        raise _crypto_missing() from None
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    scalar = private.private_numbers().private_value.to_bytes(32, "big")
    return _b64url(public), _b64url(secrets.token_bytes(16)), _b64url(scalar)


def _crypto_missing() -> Exception:
    from .drive import DriveError

    return DriveError(
        "the push browser option needs the crypto extra: "
        "pip install 'darkroom-ai[crypto]'"
    )


def resolve_options(option, interpolate) -> dict | None:
    """The ``[browser] push`` option, resolved for a session.

    ``option`` is what the exposure (or the adapter's browser defaults)
    declared: absent, ``true`` for the defaults, or a table carrying
    ``endpoint`` and/or ``permission``. ``interpolate`` resolves drive
    values in the endpoint, so it can address a declared service.
    Returns the session's push configuration, or None when unasked.
    """
    from .drive import DriveError

    if option is None or option is False:
        return None
    if option is True:
        table: dict = {}
    elif isinstance(option, dict):
        table = dict(option)
    else:
        raise DriveError(
            f"[browser] push must be true or a table, got {type(option).__name__}"
        )
    unknown = set(table) - {"endpoint", "permission"}
    if unknown:
        raise DriveError(
            f"[browser] push does not know {', '.join(sorted(unknown))} "
            "(it takes endpoint, permission)"
        )
    permission = str(table.get("permission", "granted"))
    if permission not in PUSH_PERMISSIONS:
        raise DriveError(
            f"[browser] push permission must be one of "
            f"{', '.join(PUSH_PERMISSIONS)}, got '{permission}'"
        )
    default_endpoint = f"{PUSH_DEFAULT_ENDPOINT_HOST}/{secrets.token_urlsafe(16)}"
    endpoint = interpolate(str(table.get("endpoint", default_endpoint)))
    p256dh, auth, private = key_material()
    return {
        "endpoint": endpoint,
        "p256dh": p256dh,
        "auth": auth,
        "private": private,
        "permission": permission,
    }


def drive_values(push: dict) -> dict[str, str]:
    """The ``{push.*}`` placeholders a resolved configuration publishes."""
    return {
        "push.endpoint": push["endpoint"],
        "push.p256dh": push["p256dh"],
        "push.auth": push["auth"],
        "push.private": push["private"],
    }


# The private half is deliberately absent from what the page can see:
# the stub is handed only the public point, the auth secret, and the
# permission.
def init_script(push: dict) -> str:
    """The init script installing the stub, for one session's keys.

    Playwright evaluates this before any page script on every document
    in the context, so a page that reaches for the Push API on load
    finds the stub already there.
    """
    config = json.dumps(
        {
            "endpoint": push["endpoint"],
            "p256dh": push["p256dh"],
            "auth": push["auth"],
            "permission": push["permission"],
        }
    )
    return _TEMPLATE.replace("__DARKROOM_PUSH_CONFIG__", config)


_TEMPLATE = r"""
(() => {
  const CFG = __DARKROOM_PUSH_CONFIG__;
  const STORE = '__darkroom_push__';

  // A real browser keeps the registration and its subscription in the
  // profile, so a reload finds them. Mirror that: the stub's state
  // outlives the document it was installed in.
  const load = () => {
    let raw = null;
    try { raw = window.localStorage.getItem(STORE); } catch (e) {}
    if (raw) { try { return JSON.parse(raw) || {}; } catch (e) {} }
    return window.__darkroomPushState || {};
  };
  const save = (patch) => {
    const next = Object.assign(load(), patch);
    try { window.localStorage.setItem(STORE, JSON.stringify(next)); } catch (e) {}
    window.__darkroomPushState = next;
    return next;
  };

  const decode = (text) => {
    const b64 = text.replace(/-/g, '+').replace(/_/g, '/');
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4);
    const binary = atob(padded);
    const out = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
    return out;
  };
  const encode = (source) => {
    // an applicationServerKey arrives as an ArrayBuffer or a view
    const view = source instanceof ArrayBuffer
      ? new Uint8Array(source)
      : (source.buffer
          ? new Uint8Array(source.buffer, source.byteOffset, source.byteLength)
          : source);
    const bytes = new Uint8Array(view);
    let binary = '';
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  };
  const fail = (name, message) => {
    try { return new DOMException(message, name); } catch (e) {
      const err = new Error(message);
      err.name = name;
      return err;
    }
  };
  const seen = (title, options) => {
    window.__darkroomNotifications = window.__darkroomNotifications || [];
    window.__darkroomNotifications.push({ title: title, options: options || {} });
  };

  const subscription = (state) => ({
    endpoint: CFG.endpoint,
    expirationTime: null,
    options: {
      userVisibleOnly: !!state.userVisibleOnly,
      applicationServerKey: state.applicationServerKey
        ? decode(state.applicationServerKey).buffer
        : null,
    },
    getKey(name) {
      if (name === 'p256dh') return decode(CFG.p256dh).buffer;
      if (name === 'auth') return decode(CFG.auth).buffer;
      return null;
    },
    toJSON() {
      return {
        endpoint: CFG.endpoint,
        expirationTime: null,
        keys: { p256dh: CFG.p256dh, auth: CFG.auth },
      };
    },
    unsubscribe() {
      save({ subscribed: false, userVisibleOnly: false, applicationServerKey: null });
      return Promise.resolve(true);
    },
  });

  const pushManager = {
    supportedContentEncodings: ['aes128gcm'],
    subscribe(options) {
      options = options || {};
      if (CFG.permission !== 'granted') {
        return Promise.reject(fail(
          'NotAllowedError',
          'Registration failed - permission denied'
        ));
      }
      const key = options.applicationServerKey;
      const state = save({
        subscribed: true,
        userVisibleOnly: !!options.userVisibleOnly,
        applicationServerKey: key
          ? (typeof key === 'string' ? key : encode(key))
          : null,
      });
      return Promise.resolve(subscription(state));
    },
    getSubscription() {
      const state = load();
      return Promise.resolve(state.subscribed ? subscription(state) : null);
    },
    permissionState() {
      return Promise.resolve(CFG.permission);
    },
  };

  const registrationFor = (scriptURL, scope) => ({
    scope: scope,
    scriptURL: scriptURL,
    updateViaCache: 'imports',
    installing: null,
    waiting: null,
    active: {
      state: 'activated',
      scriptURL: scriptURL,
      postMessage() {},
      addEventListener() {},
      removeEventListener() {},
    },
    pushManager: pushManager,
    showNotification(title, options) {
      seen(title, options);
      return Promise.resolve();
    },
    getNotifications() { return Promise.resolve([]); },
    update() { return Promise.resolve(); },
    unregister() { return Promise.resolve(true); },
    addEventListener() {},
    removeEventListener() {},
  });

  const booted = load();
  let registration = booted.registeredURL
    ? registrationFor(booted.registeredURL, booted.scope)
    : null;

  const container = {
    get controller() { return registration ? registration.active : null; },
    get ready() {
      if (registration) return Promise.resolve(registration);
      return new Promise((resolve) => {
        const tick = () => {
          if (registration) resolve(registration);
          else setTimeout(tick, 25);
        };
        tick();
      });
    },
    register(scriptURL, options) {
      const url = new URL(scriptURL, location.href).href;
      const scope = new URL((options && options.scope) || './', url).href;
      // the tenant's own worker file is still served and fetched — it
      // simply is not what answers for push here
      return fetch(url, { credentials: 'same-origin' }).then((response) => {
        if (!response || !response.ok) {
          throw new TypeError(
            'Failed to register a ServiceWorker: the script ' + url +
            ' returned ' + (response ? response.status : 'no response')
          );
        }
        save({ registeredURL: url, scope: scope });
        registration = registration || registrationFor(url, scope);
        return registration;
      });
    },
    getRegistration() { return Promise.resolve(registration || undefined); },
    getRegistrations() { return Promise.resolve(registration ? [registration] : []); },
    startMessages() {},
    addEventListener() {},
    removeEventListener() {},
  };
  Object.defineProperty(navigator, 'serviceWorker', {
    value: container,
    configurable: true,
  });

  function Notification(title, options) {
    this.title = title;
    Object.assign(this, options || {});
    seen(title, options);
  }
  Notification.prototype.close = function () {};
  Notification.prototype.addEventListener = function () {};
  Notification.prototype.removeEventListener = function () {};
  Notification.maxActions = 2;
  Notification.requestPermission = function (callback) {
    const answer = Promise.resolve(CFG.permission);
    if (typeof callback === 'function') answer.then(callback);
    return answer;
  };
  Object.defineProperty(Notification, 'permission', {
    get: () => CFG.permission,
    configurable: true,
  });
  Object.defineProperty(window, 'Notification', {
    value: Notification,
    writable: true,
    configurable: true,
  });

  if (!('PushManager' in window)) window.PushManager = function () {};
  if (!('PushSubscription' in window)) window.PushSubscription = function () {};

  // a page that asks the Permissions API instead must get the same answer
  if (navigator.permissions && navigator.permissions.query) {
    const query = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = (descriptor) => {
      const name = descriptor && descriptor.name;
      if (name === 'notifications' || name === 'push') {
        return Promise.resolve({
          name: name,
          state: CFG.permission === 'default' ? 'prompt' : CFG.permission,
          onchange: null,
          addEventListener() {},
          removeEventListener() {},
        });
      }
      return query(descriptor);
    };
  }
})();
"""
