"""API tests with a fake landmark detector and a controllable clock."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.config import load_config
from app.landmarks import FaceObservation
from app.server import create_app
from tests.synthetic import jpeg_bytes, synthetic_face

CONFIG = load_config(Path(__file__).resolve().parents[1] / "configs/default.yaml")
OPEN = synthetic_face(ear=0.30)
CLOSED = synthetic_face(ear=0.05)


class FakeLandmarks:
    """Returns whatever face the test sets in `self.face` (None = no face)."""

    def __init__(self):
        self.face = OPEN
        self.face_count = 1

    def detect(self, rgb):
        if self.face is None:
            return None
        return FaceObservation(landmarks=self.face, face_count=self.face_count)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def fake():
    return FakeLandmarks()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def client(fake, clock):
    return TestClient(create_app(CONFIG, fake, clock=clock))


def send_frame(ws, data=None):
    ws.send_bytes(data if data is not None else jpeg_bytes())
    return ws.receive_json()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_index_serves_camera_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "getUserMedia" in response.text


def test_websocket_sends_client_config_first(client):
    with client.websocket_connect("/ws") as ws:
        message = ws.receive_json()
    assert message["type"] == "config"
    assert message["camera"]["max_fps"] == CONFIG.camera.max_fps
    assert message["alerts"]["sound"] is True


def test_open_eyes_frame(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        result = send_frame(ws)
    assert result["type"] == "result"
    assert result["state"] == "AWAKE"
    assert result["ear"] == pytest.approx(0.30)
    assert result["face_count"] == 1
    assert result["alert"] is False
    assert result["low_light"] is False
    assert result["warning_reasons"] == []


def test_prolonged_closure_raises_alert(client, fake, clock):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        fake.face = CLOSED
        assert send_frame(ws)["state"] == "EYES_CLOSED"
        clock.now += 2.0
        result = send_frame(ws)
    assert result["state"] == "DROWSINESS_WARNING"
    assert result["alert"] is True
    assert result["warning_reasons"] == ["continuous_closure"]


def test_websocket_reports_both_warning_reasons(client, fake, clock):
    fake.face = CLOSED
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        for _ in range(33):  # 16 s of closed eyes at 2 fps: PERCLOS has enough data
            result = send_frame(ws)
            clock.now += 0.5
    assert result["state"] == "DROWSINESS_WARNING"
    assert result["perclos"] == 1.0
    assert result["warning_reasons"] == ["continuous_closure", "perclos"]


def test_each_connection_has_its_own_state(client, fake, clock):
    fake.face = CLOSED
    with client.websocket_connect("/ws") as first:
        first.receive_json()
        send_frame(first)
        clock.now += 2.0
        assert send_frame(first)["state"] == "DROWSINESS_WARNING"
    with client.websocket_connect("/ws") as second:
        second.receive_json()
        assert send_frame(second)["state"] == "EYES_CLOSED"


def test_no_face(client, fake):
    fake.face = None
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        result = send_frame(ws)
    assert result["state"] == "NO_FACE_DETECTED"
    assert result["ear"] is None


def test_dark_frame_is_flagged(client, fake):
    fake.face = None
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        result = send_frame(ws, jpeg_bytes(value=5))
    assert result["low_light"] is True


def test_invalid_frame_returns_error_and_keeps_connection(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        error = send_frame(ws, b"not an image")
        assert error == {"type": "error", "message": "frame is not a decodable image"}
        assert send_frame(ws)["type"] == "result"


def test_text_message_is_rejected(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_text("hello")
        assert ws.receive_json()["type"] == "error"
        assert send_frame(ws)["type"] == "result"


def test_get_settings(client):
    response = client.get("/api/settings")

    assert response.status_code == 200

    data = response.json()

    assert data["detection"]["ear_threshold"] == 0.18
    assert data["detection"]["min_closed_seconds"] == 1.5
    assert data["detection"]["perclos"]["enabled"] is True
    assert data["alerts"]["sound"] is True

    assert "model_path" not in data["detection"]
    assert "server" not in data


def test_settings_api_save_and_reset(monkeypatch, tmp_path, fake):
    from fastapi.testclient import TestClient

    from app.config import load_config
    from app.server import create_app

    settings_file = tmp_path / "settings.yaml"
    monkeypatch.setenv("APP_SETTINGS_PATH", str(settings_file))

    config = load_config("configs/default.yaml")
    app = create_app(config, fake)
    client = TestClient(app)

    # Geçerli ayarı kaydet.
    response = client.patch(
        "/api/settings",
        json={"ear_threshold": 0.23},
    )

    assert response.status_code == 200
    assert response.json()["detection"]["ear_threshold"] == 0.23
    assert settings_file.exists()

    # Kaydedilen ayar GET üzerinden okunabilmeli.
    response = client.get("/api/settings")
    assert response.status_code == 200
    assert response.json()["detection"]["ear_threshold"] == 0.23

    # Geçersiz değer reddedilmeli.
    response = client.patch(
        "/api/settings",
        json={"ear_threshold": 0.90},
    )
    assert response.status_code == 422

    # Hatalı istek önceki geçerli ayarı değiştirmemeli.
    response = client.get("/api/settings")
    assert response.json()["detection"]["ear_threshold"] == 0.23

    # Başlangıç ayarlarına dön.
    response = client.post("/api/settings/reset")
    assert response.status_code == 200

    response = client.get("/api/settings")
    assert response.json()["detection"]["ear_threshold"] == (config.detection.ear_threshold)


def test_settings_update_while_websocket_connected(monkeypatch, tmp_path, fake):
    from fastapi.testclient import TestClient

    from app.config import load_config
    from app.server import create_app

    settings_file = tmp_path / "settings.yaml"
    monkeypatch.setenv("APP_SETTINGS_PATH", str(settings_file))

    config = load_config("configs/default.yaml")
    app = create_app(config, fake)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        initial = ws.receive_json()
        assert initial["type"] == "config"

        response = client.patch(
            "/api/settings",
            json={"ear_threshold": 0.23},
        )

        assert response.status_code == 200
        assert response.json()["config_version"] == 1

        response = client.get("/api/settings")
        assert response.json()["detection"]["ear_threshold"] == 0.23


def test_websocket_uses_updated_ear_threshold(monkeypatch, tmp_path, fake, clock):
    settings_file = tmp_path / "settings.yaml"
    monkeypatch.setenv("APP_SETTINGS_PATH", str(settings_file))

    config = load_config("configs/default.yaml")
    app = create_app(config, fake, clock=clock)
    client = TestClient(app)

    # İki eşik arasında kalan bir EAR değeri seçiyoruz.
    fake.face = synthetic_face(ear=0.20)

    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "config"

        # Başlangıç eşiği 0.18, EAR 0.20:
        # Gözler açık kabul edilmeli.
        before = send_frame(ws)

        assert before["type"] == "result"
        assert before["ear"] == pytest.approx(0.20)
        assert before["state"] == "AWAKE"

        # WebSocket açıkken eşiği 0.23'e yükselt.
        response = client.patch(
            "/api/settings",
            json={"ear_threshold": 0.23},
        )

        assert response.status_code == 200
        assert response.json()["config_version"] == 1

        # Aynı EAR değeri, yeni eşikle kapalı sayılmalı.
        after = send_frame(ws)

        assert after["type"] == "result"
        assert after["ear"] == pytest.approx(0.20)
        assert after["state"] == "EYES_CLOSED"

        # Kaydetme sırasında kamera bağlantısı kopmamalı.
        assert settings_file.exists()
