from scripts._ship_env import SHIP_SECRET_ENV_PREFIX, strip_ship_secret_env


def test_strip_ship_secret_env_removes_only_ship_prefixed_keys() -> None:
    env = {
        "BIDMATE_SHIP_TOKEN": "secret",
        "BIDMATE_SHIP_MANIFEST_DIR": "/private/ship",
        "BIDMATE_SHIPPING_LABEL": "not-secret-prefix",
        "BIDMATE_SHIP": "not-prefix-with-underscore",
        "PATH": "/usr/bin",
        "GITHUB_TOKEN": "preserved-auth",
    }

    assert strip_ship_secret_env(env) == {
        "BIDMATE_SHIPPING_LABEL": "not-secret-prefix",
        "BIDMATE_SHIP": "not-prefix-with-underscore",
        "PATH": "/usr/bin",
        "GITHUB_TOKEN": "preserved-auth",
    }


def test_strip_ship_secret_env_returns_copy_without_mutating_input() -> None:
    env = {f"{SHIP_SECRET_ENV_PREFIX}KILL_SWITCH": "1", "HOME": "/home/runner"}

    stripped = strip_ship_secret_env(env)

    assert stripped == {"HOME": "/home/runner"}
    assert env == {f"{SHIP_SECRET_ENV_PREFIX}KILL_SWITCH": "1", "HOME": "/home/runner"}
    assert stripped is not env
