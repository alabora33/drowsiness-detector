# Debian kurulum ve dağıtım kılavuzu

Bu kılavuz drowsiness-detector'ı Debian tabanlı bir sistemde (doğal Debian veya Windows üzerinde
WSL2 Debian) Docker ile ya da doğrudan Python ile çalıştırmayı anlatır. Genel bakış ve mimari için
[README](../README.md).

## Desteklenen ortamlar

| Ortam | Durum |
|---|---|
| Debian 13 (trixie), amd64 — Docker ile | Test edildi (WSL2 üzerinde) |
| Debian 13 — doğrudan Python 3.13 ile | Test edildi |
| Debian 12 (bookworm), amd64 — Docker ile | Desteklenir (imaj kendi Debian 13 tabanını taşır) |
| Debian 12 — doğrudan Python ile | Önerilmez (sistem Python'u 3.11; bağımlılık kilidi 3.13 ile üretildi) → Docker kullanın |
| Windows 11 + WSL2 + Docker Desktop | Gerçek webcam ile manuel test edildi |
| arm64 (Raspberry Pi vb.) | İmaj yayınlanmıyor |

Kamera her durumda **tarayıcı** tarafından açılır. Container'a `/dev/video0` gibi bir cihaz
bağlamak gerekmez; tarayıcı ile servis aynı makinede değilse bkz.
[Uzak sunucuda çalıştırma](#uzak-sunucuda-çalıştırma).

## 1. Docker kurulumu (Debian)

Docker'ın resmi apt deposundan:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin
```

Docker'ı `sudo` olmadan kullanmak için (oturumu kapatıp açın):

```bash
sudo usermod -aG docker "$USER"
```

Kontrol: `docker info` ve `docker buildx version`.

**WSL2:** WSL içine Docker Engine kurmak yerine Windows'ta Docker Desktop kullanılabilir:
Docker Desktop → Settings → Resources → WSL Integration → Debian'ı açın → Apply & Restart.
Entegrasyonu açtıktan sonra `docker info` hata verirse Docker Desktop'ı yeniden başlatın.

## 2. GHCR'dan hazır imajı çalıştırma

```bash
docker pull ghcr.io/alabora33/drowsiness-detector:0.1.0
docker run -d --name drowsiness --restart unless-stopped \
  -p 127.0.0.1:8000:8000 ghcr.io/alabora33/drowsiness-detector:0.1.0
```

- Tarayıcıda **http://localhost:8000** → **Başlat** → kamera iznini verin.
- `--restart unless-stopped` makine yeniden başlayınca servisi otomatik başlatır.
- Belirli bir yapıyı birebir sabitlemek için tag yerine digest kullanın
  (`...drowsiness-detector@sha256:<digest>`; digest release iş akışının özetinde yazar).
- Sürüm tag'leri: `X.Y.Z` değişmez; `X.Y` ve `latest` kayan tag'lerdir.

Durdurma / güncelleme / geri alma:

```bash
docker rm -f drowsiness
docker run -d --name drowsiness --restart unless-stopped \
  -p 127.0.0.1:8000:8000 ghcr.io/alabora33/drowsiness-detector:<yeni-veya-eski-sürüm>
```

İsteğe bağlı sıkılaştırma (test edildi, uygulama salt-okunur dosya sistemiyle çalışır):

```bash
docker run -d --name drowsiness -p 127.0.0.1:8000:8000 \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
  ghcr.io/alabora33/drowsiness-detector:0.1.0
```

## 3. Kaynaktan imaj build etme (CONFIG_PATH)

```bash
sudo apt-get install -y git
git clone https://github.com/alabora33/drowsiness-detector.git
cd drowsiness-detector

docker build --build-arg CONFIG_PATH=configs/default.yaml       -t drowsiness-detector:default .
docker build --build-arg CONFIG_PATH=configs/sensitive.yaml     -t drowsiness-detector:sensitive .
docker build --build-arg CONFIG_PATH=configs/night-driving.yaml -t drowsiness-detector:night .
```

- `CONFIG_PATH` **build context içinde** bir yol olmalı; kendi profilinizi `configs/` altına
  koyun. Context dışındaki bir yol (`../my.yaml`) `"/my.yaml": not found` hatası verir.
- Config build sırasında doğrulanır; geçersiz bir dosya build'i durdurur:
  ```
  Invalid configuration in /app/config/config.yaml:
    - detection.ear_threshold: Input should be less than or equal to 0.4 (got 2.0)
  ```
- Hangi profilin gömüldüğünü görmek:
  ```bash
  docker inspect --format '{{index .Config.Labels "io.github.alabora33.drowsiness-detector.config"}}' drowsiness-detector:night
  docker run --rm drowsiness-detector:night python -m app.config --check /app/config/config.yaml
  ```
- Build'i uçtan uca doğrulamak (geçici container ve ağ açar, sonra siler):
  ```bash
  ./scripts/container_smoke.sh drowsiness-detector:default
  ```

## 4. Çalışma anında config değiştirme

Yeniden build etmeden başka bir dosya kullanmak için dosyayı salt-okunur bağlayıp `APP_CONFIG`
ile gösterin:

```bash
cp configs/default.yaml ~/my-profile.yaml      # düzenleyin
docker run -d --name drowsiness -p 127.0.0.1:8000:8000 \
  -v "$HOME/my-profile.yaml:/config/my-profile.yaml:ro" \
  -e APP_CONFIG=/config/my-profile.yaml \
  ghcr.io/alabora33/drowsiness-detector:0.1.0
docker logs drowsiness | grep config          # "config /config/my-profile.yaml"
```

Dosya açılışta doğrulanır; hatalıysa container `Startup failed: ...` mesajıyla exit 2 verir.
Eşikler ortam değişkeniyle değil, sadece dosya ile verilir.

## 5. Docker'sız (doğrudan Python) çalıştırma — Debian 13

```bash
sudo apt-get install -y python3-venv python3-pip libgles2 libegl1 libgl1 libglib2.0-0t64
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m app.main
```

- Depo kök dizininden çalıştırın (`configs/default.yaml` ve `models/` göreli yollardır).
- `libgles2 libegl1`: MediaPipe'ın native kütüphanesi; `libgl1 libglib2.0-0t64`: OpenCV.
  Eksikse açılışta `Startup failed: cannot load MediaPipe native libraries (...)` görülür.
- Varsayılan `server.host: 0.0.0.0` servisi tüm arayüzlere açar; doğrudan çalıştırırken
  kendi profilinizde `host: 127.0.0.1` kullanın.

Testler: `.venv/bin/ruff check . && .venv/bin/pytest -v`

## 6. Uzak sunucuda çalıştırma

Tarayıcı kamerayı sadece güvenli bağlamda verir (`localhost` veya HTTPS). Servis başka bir
Debian makinedeyse portu yerel ağa açmak yerine SSH tüneli kullanın:

```bash
ssh -L 8000:127.0.0.1:8000 kullanici@sunucu
```

Ardından kendi bilgisayarınızda http://localhost:8000 açın. Kamera kendi bilgisayarınızın
kamerasıdır; kareler tünel üzerinden sunucuya gider.

## 7. Windows 11 + WSL2 + Docker Desktop ile kamera testi

1. Docker Desktop'ın çalıştığından emin olun (WSL terminalinde `docker info`).
2. WSL (Debian/Ubuntu) terminalinde imajı çalıştırın (bkz. bölüm 2 veya 3).
3. **Windows'taki** tarayıcıda http://localhost:8000 açın; Docker Desktop portu Windows'a yönlendirir.
4. **Başlat** → kamera izni. Gözler açıkken `UYANIK`, kapalıyken `GÖZLER KAPALI`,
   ~1.5 sn sonra `UYUKLAMA UYARISI` ve "Uyarı sebebi" satırında gerekçe görülmeli.
5. Loglar: `docker logs -f drowsiness` (`State ... reasons=...` satırları).

## 8. CI/CD ve release prosedürü

Ayrıntılar README'nin "CI/CD ve sürümleme" bölümünde. Özet:

1. Değişiklikler pull request ile gelir; `ci.yml` lint, testler, Docker build, smoke testi ve
   config kontrollerini çalıştırır. PR'lar imaj yayınlamaz.
2. Yeni sürüm için `app/__init__.py` içindeki `__version__` bir PR ile artırılır ve merge edilir.
3. `main` üzerinde `vX.Y.Z` tag'i gönderilir. `release.yml`: tag/sürüm/`main` kontrolü → tam CI →
   fail-closed GHCR sürüm kontrolü → tek build → aynı imajla smoke testi → push → tag'lerin aynı
   digest'i gösterdiği kontrolü → özet.
4. İlk yayından sonra paket görünürlüğünü kontrol edin: GitHub → profil → Packages →
   drowsiness-detector → Package settings. Public değilse anonim `docker pull` çalışmaz.

## Sorun giderme

| Belirti | Sebep / çözüm |
|---|---|
| `permission denied ... /var/run/docker.sock` | Kullanıcı `docker` grubunda değil: `sudo usermod -aG docker $USER`, oturumu yenileyin |
| WSL'de `Cannot connect to the Docker daemon` | Docker Desktop kapalı veya WSL entegrasyonu kapalı (bölüm 1) |
| `port is already allocated` | `-p 127.0.0.1:8080:8000` ile başka port kullanın |
| `docker pull` → `denied` / `unauthorized` | Paket henüz yayınlanmamış veya private (bölüm 8, madde 4) |
| Build: `"/....yaml": not found` | `CONFIG_PATH` build context dışında veya `.dockerignore` dışında; dosyayı `configs/` altına koyun |
| Build: `Invalid configuration in ...` | Mesajdaki alanı düzeltin; bilinmeyen, tekrarlanan anahtar ve yanlış tipler reddedilir |
| Container hemen kapanıyor | `docker logs drowsiness`; `Startup failed:` satırı sebebi (config, model, native kütüphane) söyler |
| Container `unhealthy` | `docker inspect --format '{{json .State.Health}}' drowsiness`; config'te port değiştiyse `-p` eşlemesini de değiştirin |
| Sayfa açılıyor, kamera açılmıyor | Güvenli bağlam (bölüm 6), tarayıcı kamera izni, kamerayı kullanan başka uygulama |
| "Sunucu bağlantısı kesildi" | Container durdu veya yeniden başladı; `docker ps`, `docker logs` |
| Durum hep `YÜZ YOK` | Yüz kadraja tam girmiyor veya ışık az (`low_light`); kamerayı yüz hizasına getirin |
| Sık yanlış uyarı | Arayüzdeki EAR değerini gözler açıkken/kapalıyken gözleyip `ear_threshold`'u ikisinin arasına ayarlayın; "Uyarı sebebi" PERCLOS ise `perclos.threshold`'u artırın |
| Doğrudan Python'da `libGLESv2.so.2` / `libGL.so.1` hatası | Bölüm 5'teki sistem paketlerini kurun |

## Bilinen sınırlamalar

README'deki [Bilinen sınırlamalar](../README.md#bilinen-sınırlamalar) bölümüne bakın. Özellikle:
tek global eşik herkese uymaz, kötü ışık ve yan profil tespiti zayıflatır, servis kimlik
doğrulamasızdır ve yerel kullanım içindir, araç tıbbi teşhis koymaz.
