# drowsiness-detector

PC/laptop kamerasından gelen görüntüde **göz kapanmasına dayalı uyuklama belirtilerini** gerçek
zamanlı tespit eden Python servisi. Tarayıcı kamerayı açar, kareleri WebSocket ile servise
gönderir; servis MediaPipe ile yüz noktalarını bulur, göz açıklık oranını (EAR) hesaplar ve
zamana dayalı bir durum makinesiyle sonuç döner.

> Bu araç tıbbi teşhis koymaz ve uykuyu garanti şekilde tespit etmez; sadece göz kapanmasına
> dayalı bir uyarı üretir.

- Docker imajı: `ghcr.io/alabora33/drowsiness-detector:<sürüm>` (linux/amd64)
- Debian kurulum ve dağıtım kılavuzu: [docs/DEPLOYMENT_DEBIAN.md](docs/DEPLOYMENT_DEBIAN.md)

## Mimari

```
Tarayıcı (http://localhost:8000)                    Python servisi (FastAPI, Docker içinde)
getUserMedia → canvas → JPEG ──── WebSocket /ws ───► kare doğrulama (app/frames.py)
     ▲                                                 → MediaPipe FaceLandmarker (app/landmarks.py)
     │                                                 → EAR (app/metrics.py)
     └──── JSON sonuç (durum, EAR, PERCLOS, sebep) ◄── → zamana dayalı durum makinesi (app/detector.py)
```

**Neden kamera tarayıcıda?** WSL2 çekirdeğinde varsayılan USB kamera sürücüsü yok ve Docker
Desktop Windows kamerasını container'a aktaramıyor. Tarayıcı kamerayı host üzerinde açtığı için
aynı yöntem Windows + WSL2 + Docker Desktop'ta ve doğal Debian'da `--device` gerektirmeden
çalışır. Tespit tamamen Python tarafında yapılır; görüntü harici bir servise gönderilmez.

| Modül | Görevi |
|---|---|
| `app/config.py` | YAML okuma ve doğrulama (bilinmeyen/tekrarlanan anahtar, strict tipler, aralıklar) |
| `app/frames.py` | Gelen JPEG'i çözme, boyut/geçerlilik kontrolü, parlaklık ölçümü |
| `app/landmarks.py` | MediaPipe FaceLandmarker (başlangıçta bir kez yüklenir); birden fazla yüzde en büyüğü |
| `app/metrics.py` | EAR = (\|p2−p6\| + \|p3−p5\|) / (2·\|p1−p4\|), piksel koordinatlarında |
| `app/detector.py` | Bağlantı başına durum makinesi ve PERCLOS |
| `app/server.py` | `GET /health`, `GET /` (kamera sayfası), `WS /ws` |
| `app/main.py` | Giriş noktası; `--healthcheck` ile container sağlık kontrolü |
| `app/static/index.html` | Framework'süz tek sayfa arayüz |

### Tespit mantığı

| Durum | Anlamı |
|---|---|
| `AWAKE` | Gözler açık |
| `EYES_CLOSED` | Gözler kapalı ama uyarı eşiğine ulaşılmadı (normal göz kırpma dahil) |
| `DROWSINESS_WARNING` | Uyarı; sebebi `warning_reasons` alanında |
| `NO_FACE_DETECTED` | Yüz yok (kısa kayıplar `no_face_grace_seconds` kadar yok sayılır) |

- **Göz kapalı:** iki gözün ortalama EAR'ı `ear_threshold` altında.
- **`continuous_closure`:** kesintisiz kapanma `min_closed_seconds`'a ulaştı. Süreler kare
  sayısıyla değil gerçek zamanla ölçülür (fps'den bağımsız). Kapanma, gözler
  `min_open_seconds` boyunca açık kalmadan bitmez; böylece tek tük gürültülü kareler sayacı sıfırlamaz.
- **`perclos`:** son `window_seconds` içinde gözlerin kapalı geçen süre oranı `threshold`'u aştı
  (pencerenin en az yarısı dolunca hesaplanır). Bu uyarı gözler açıldıktan sonra da oran
  düşene kadar sürebilir. İki sebep aynı anda aktif olabilir.
- Ortalama parlaklık `low_light_threshold` altındaysa sonuçta `low_light: true` döner.

## Hızlı başlangıç (Docker)

Yayınlanmış bir sürümü çalıştırmak (ayrıntılar ve Docker kurulumu için
[Debian kılavuzu](docs/DEPLOYMENT_DEBIAN.md)):

```bash
docker run -d --name drowsiness -p 127.0.0.1:8000:8000 ghcr.io/alabora33/drowsiness-detector:0.1.0
```

Sonra tarayıcıda **http://localhost:8000** adresini açın, **Başlat**'a basın ve kamera iznini verin.
`127.0.0.1:` ön eki servisi sadece bu makineye açar; kimlik doğrulama olmadığı için yerel ağa
açmayın.

Kaynaktan imaj build etmek:

```bash
docker build --build-arg CONFIG_PATH=configs/default.yaml -t drowsiness-detector:local .
docker run -d --name drowsiness -p 127.0.0.1:8000:8000 drowsiness-detector:local
```

## Konfigürasyon

Tüm ayarlar YAML dosyasındadır; varsayılanlar kodda değil `configs/default.yaml` içindedir.
Her alan zorunludur; bilinmeyen veya tekrarlanan anahtar, yanlış tip (`max_faces: true` gibi)
ve aralık dışı değerler açık bir hata mesajıyla reddedilir.

| Profil | Amaç |
|---|---|
| `configs/default.yaml` | Dengeli: eşik 0.18, 1.5 sn kesintisiz kapanma, PERCLOS %30 / 30 sn |
| `configs/sensitive.yaml` | Daha erken uyarı: eşik 0.21, 0.8 sn, PERCLOS %20 / 20 sn |
| `configs/night-driving.yaml` | Gece sürüşü (deneysel): eşik 0.20, 1.2 sn, açılma toleransı 0.25 sn |

Üç katman vardır:

1. **Build sırasında (imaja gömülür):** `--build-arg CONFIG_PATH=configs/<dosya>.yaml`. Yol build
   context içinde olmalı (`.dockerignore` sadece `configs/` ve `tests/fixtures/*.yaml`
   dosyalarına izin verir). Dosya build sırasında doğrulanır; geçersizse **build başarısız
   olur**. Seçilen yol `io.github.alabora33.drowsiness-detector.config` etiketine yazılır.
2. **Çalışma anında (yeniden build etmeden):** başka bir dosyayı bağlayıp `APP_CONFIG` ile gösterin.
   Geçersizse container `Startup failed: ...` mesajıyla exit 2 verir.
   ```bash
   docker run -d --name drowsiness -p 127.0.0.1:8000:8000 \
     -v "$PWD/my.yaml:/config/my.yaml:ro" -e APP_CONFIG=/config/my.yaml \
     ghcr.io/alabora33/drowsiness-detector:0.1.0
   ```
3. **Ortam değişkeni:** sadece `APP_CONFIG` (dosya yolu). Eşikler ortam değişkeniyle verilmez.

Bir dosyayı önceden doğrulamak: `python -m app.config --check configs/night-driving.yaml`

| Alan | Aralık | Açıklama |
|---|---|---|
| `server.host` / `server.port` | – / 1–65535 | Dinlenen adres/port (container içinde `0.0.0.0:8000`) |
| `camera.max_fps` | 0–30 | Tarayıcının saniyede gönderebileceği en fazla kare |
| `camera.frame_width` / `frame_height` | 160–1920 / 120–1080 | Kare boyutu |
| `camera.jpeg_quality` | 0.3–1.0 | Tarayıcıdaki JPEG kalitesi |
| `detection.model_path` | – | MediaPipe model dosyası |
| `detection.max_faces` | 1–5 | Aranan en fazla yüz; en büyüğü takip edilir |
| `detection.min_face_confidence` | 0–1 | Yüz algılama güveni |
| `detection.ear_threshold` | 0.05–0.4 | Bunun altındaki EAR "kapalı" sayılır |
| `detection.min_closed_seconds` | 0.2–10 | Kesintisiz kapanma uyarı süresi |
| `detection.min_open_seconds` | 0–2 | Kapanmanın bitmesi için gereken kesintisiz açıklık |
| `detection.no_face_grace_seconds` | 0–10 | Yok sayılan kısa yüz kaybı |
| `detection.low_light_threshold` | 0–255 | Düşük ışık bayrağı için ortalama parlaklık |
| `detection.perclos.enabled` / `window_seconds` / `threshold` | – / 5–300 / 0–1 | PERCLOS ayarları |
| `alerts.enabled` / `alerts.sound` | – | Uyarı ve tarayıcı bip sesi |
| `logging.level` | DEBUG, INFO, WARNING, ERROR | Log seviyesi |

## Tarayıcı ve WebSocket

- Kamera API'si sadece **güvenli bağlamda** çalışır: `http://localhost` veya HTTPS. Sayfayı yerel
  ağ IP'siyle (`http://192.168.x.x:8000`) açarsanız tarayıcı kamerayı vermez; uzak bir sunucu için
  SSH tüneli kullanın (Debian kılavuzu).
- Arayüz aynı anda tek kare gönderir (bir sonucu almadan yenisini göndermez) ve hedef FPS
  `camera.max_fps` ile sınırlıdır. İzin reddi, kamera bulunamaması, kamera ve sunucu kopması
  ekranda gösterilir.
- Protokol (`/ws`): bağlantıda sunucu önce `{"type": "config", ...}` gönderir. İstemci her kare
  için ikili JPEG yollar; sunucu şu biçimde yanıtlar:
  ```json
  {"type": "result", "state": "DROWSINESS_WARNING", "ear": 0.05, "closed_seconds": 5.0,
   "perclos": 0.333, "face_count": 1, "alert": true,
   "warning_reasons": ["continuous_closure", "perclos"], "low_light": false, "processing_ms": 4.1}
  ```
  Geçersiz kare veya metin mesajında `{"type": "error", "message": "..."}` döner, bağlantı açık kalır.
- Durum geçişleri sebepleriyle loglanır:
  `State EYES_CLOSED -> DROWSINESS_WARNING (ear=0.05, closed=1.50s, perclos=None, reasons=continuous_closure)`

## Sağlık kontrolü

- `GET /health` → `{"status": "ok", "version": "..."}`
- İmajın `HEALTHCHECK`'i `python -m app.main --healthcheck` çalıştırır (portu config'ten okur):
  30 sn aralık, 30 sn açılış süresi (bu sürede 2 sn'de bir), 3 deneme.
  ```bash
  docker inspect --format '{{.State.Health.Status}}' drowsiness
  ```
- Container root olmayan `app` kullanıcısıyla (uid 10001) çalışır.

## Yerel geliştirme

Python 3.13 ile test edildi (Debian 13). Gerekli sistem paketleri ve ayrıntılar Debian
kılavuzunda.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m app.main            # configs/default.yaml ile, http://localhost:8000
APP_CONFIG=configs/sensitive.yaml .venv/bin/python -m app.main
```

## Testler

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -v                       # birim + API/WebSocket + entegrasyon testleri
.venv/bin/pytest -m "not integration"     # MediaPipe native kütüphaneleri olmadan
./scripts/container_smoke.sh drowsiness-detector:local   # container uçtan uca testi
```

| Katman | Ne doğrulanıyor | Nerede |
|---|---|---|
| Birim | Config doğrulama, EAR, durum makinesi, PERCLOS, uyarı sebepleri, kare doğrulama, release sürüm kontrolü (sahte registry) | Yerel + CI |
| API / WebSocket | Sahte landmark dedektörü ve kontrol edilebilir saat ile `/health`, `/`, `/ws` | Yerel + CI |
| Entegrasyon | Gerçek MediaPipe modeli + gerçek fotoğraf (`tests/fixtures/portrait.jpg`) | Yerel + CI |
| Container | İmaj build, `scripts/smoke_test.py` (10 kontrol), HEALTHCHECK, profil seçimi, geçersiz config reddi | Yerel + CI |
| Gerçek webcam | Manuel kabul testi (Windows 11 + WSL2 + Docker Desktop): kesintisiz kapanma ve PERCLOS uyarıları, iki sebep birlikte, AWAKE'e dönüş | Manuel |

Gerçek webcam testi CI'da otomatik çalışmaz; kapanmış göz içeren gerçek bir test fotoğrafı
yoktur, kapanma mantığı sentetik EAR dizileriyle test edilir.

## CI/CD ve sürümleme

**`ci.yml`** (her pull request'te ve `main`'e her push'ta):
1. `Lint and test`: ruff, tam pytest (entegrasyon dahil).
2. `Docker build and smoke test`: imaj build, container smoke testi + HEALTHCHECK,
   `sensitive.yaml` ile build edilip değerin imajda doğrulanması, geçersiz config ile build'in
   **başarısız** olması. Pull request'ler imaj push etmez.

**`release.yml`** (`vX.Y.Z` tag'i push edilince):
1. Tag sürümü `app/__init__.py` içindeki `__version__` ile aynı olmalı ve tag'lenen commit `main`
   üzerinde olmalı.
2. CI'ın tamamı yeniden çalışır (`workflow_call`).
3. `scripts/check_version_absent.py`: sürüm GHCR'da zaten varsa veya bu kesin olarak
   doğrulanamıyorsa (yetki/ağ/zaman aşımı/beklenmeyen yanıt) yayın **durur** (fail-closed).
4. İmaj bir kez build edilir; `scripts/publish_tested_image.sh` **aynı imajı** smoke testinden
   geçirir, sonra tüm tag'lerle push eder ve tag'lerin aynı digest'i gösterdiğini doğrular.
5. Digest iş akışı özetine yazılır (`ghcr.io/alabora33/drowsiness-detector@sha256:...`).

İzinler: varsayılan `contents: read`; `packages: write` sadece yayın job'unda; kimlik bilgisi
olarak sadece `GITHUB_TOKEN`. Action'lar commit SHA'sına sabittir.

**Tag'ler:** `X.Y.Z` değişmez (aynı sürüm ikinci kez yayınlanamaz); `X.Y` ve `latest` kayan
tag'lerdir. Kesin sabitleme için digest kullanın:
`docker pull ghcr.io/alabora33/drowsiness-detector@sha256:<digest>`.

**Yeni sürüm yayınlama:**
1. Pull request ile `app/__init__.py` içindeki `__version__` değerini artırın (ör. `0.2.0`) ve merge edin.
2. `main` üzerinde tag oluşturup gönderin:
   ```bash
   git switch main && git pull --ff-only
   git tag -a v0.2.0 -m "v0.2.0"
   git push origin v0.2.0
   ```
3. Actions'ta "Release" iş akışını izleyin; özette digest görünür.

## Bilinen sınırlamalar

- **Tek global eşik herkese uymaz.** Göz şekli, gülümseme, gözlük yansıması ve aşağı bakmak EAR'ı
  değiştirir (test fotoğrafında açık ama gülümseyen gözler EAR ≈ 0.20). Kişiye göre
  `ear_threshold` ayarı gerekebilir; otomatik kalibrasyon yoktur.
- Kötü ışıkta yüz bulunamayabilir (`low_light` bayrağı bunu gösterir); yan profil ve yüzün kısmen
  görünmesi tespiti bozar.
- PERCLOS uyarısı gözler açıldıktan sonra da oran düşene kadar (birkaç saniye) sürebilir.
- Kimlik doğrulama yoktur; servis yerel kullanım içindir. Yerel ağdan erişim HTTPS gerektirir
  (tarayıcı kuralı) ve bu proje HTTPS sunmaz.
- İmaj ~1.15 GB (MediaPipe, OpenCV ve Debian'ın `libegl1` paketinin Mesa bağımlılığı). Sadece
  linux/amd64 build edilir.
- İmajda OpenCV'nin GUI'siz (headless) sürümü kullanılır; bu yüzden `pip check`
  `mediapipe requires opencv-contrib-python` uyarısı verir. Uygulamayı etkilemez.
- Release imajları `docker push` ile gönderildiği için buildx provenance attestation içermez.
- Varsayılan port 8000'dir; config'te port değişirse `-p` eşlemesi de değişmeli
  (`scripts/container_smoke.sh` 8000 varsayar).

## Sorun giderme (kısa)

| Belirti | Çözüm |
|---|---|
| `port is already allocated` | Başka bir host portu kullanın: `-p 127.0.0.1:8080:8000`, sonra `http://localhost:8080` |
| "Kamera izni reddedildi" | Adres çubuğundaki kamera simgesinden izin verip **Başlat**'a tekrar basın |
| "Kamera için güvenli bağlam gerekir" | Sayfayı `localhost` veya SSH tüneli üzerinden açın |
| "Kamera bulunamadı" / "başka uygulama kullanıyor" | Kamerayı kullanan diğer uygulamaları kapatın |
| Container `unhealthy` veya hemen kapanıyor | `docker logs drowsiness` — `Startup failed:` satırı sebebi gösterir |
| Sık yanlış uyarı | Arayüzdeki EAR değerine bakarak `ear_threshold`'u gözler açıkken ve kapalıyken ölçülen değerlerin arasına çekin |

Daha fazlası: [docs/DEPLOYMENT_DEBIAN.md](docs/DEPLOYMENT_DEBIAN.md#sorun-giderme)

## Proje yapısı

```
app/            uygulama kodu ve static/index.html
configs/        default, sensitive, night-driving profilleri
models/         MediaPipe face_landmarker.task (sha256 models/README.md içinde)
scripts/        smoke_test.py, container_smoke.sh, check_version_absent.py, publish_tested_image.sh
tests/          birim, API, entegrasyon ve release kontrolü testleri
docs/           Debian kurulum ve dağıtım kılavuzu
Dockerfile, .dockerignore, requirements.in (doğrudan), requirements.txt (kilit), requirements-dev.txt
.github/workflows/ci.yml, release.yml
```
