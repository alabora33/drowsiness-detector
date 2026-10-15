# Drowsiness Detector

Bu projede bilgisayar kamerasından gelen görüntülerle gözlerin açık mı kapalı mı olduğunu takip eden bir uyuklama uyarı uygulaması geliştirdim. Gözler uzun süre kapalı kaldığında veya kısa aralıklarla sık sık kapandığında ekranda uyarı çıkıyor. Uyarı sırasında ses de çalabiliyor.

Uygulamanın backend kısmı Python ile yazıldı. Kamerayı tarayıcı açıyor, görüntüleri WebSocket üzerinden sunucuya gönderiyor. Python tarafında MediaPipe ile yüz noktaları bulunuyor, EAR ve PERCLOS değerleri hesaplanıyor.


## Neler yapıyor?

- Bilgisayarın kamerasından canlı görüntü alıyor.
- Gözlerin açık veya kapalı olduğunu takip ediyor.
- Uzun süre göz kapalı kalırsa uyarı veriyor.
- PERCLOS ile belirli bir süre içindeki göz kapanma oranını kontrol ediyor.
- Ayarlar ekranından eşikleri değiştirmeye izin veriyor. Kaydedilen ayarlar kamera çalışırken uygulanıyor.
- Docker ile çalışıyor ve ayarlar volume kullanılarak saklanabiliyor.

## Docker ile çalıştırma

Bilgisayarda Docker kurulu olması yeterli. Debian veya Ubuntu için kurulum adımlarını [buraya](docs/DEPLOYMENT_DEBIAN.md) yazdım.

Yayınlanmış ilk sürümü indirmek ve çalıştırmak için:

```bash
docker pull ghcr.io/alabora33/drowsiness-detector:0.1.1

docker run -d --name drowsiness \
  -p 127.0.0.1:8000:8000 \
  ghcr.io/alabora33/drowsiness-detector:0.1.1
```

Ardından tarayıcıda **http://localhost:8000** adresini açıp **Başlat** butonuna basın. Kamera izni verildiğinde uygulama çalışmaya başlar.

Container'ı durdurmak için `docker stop drowsiness`, yeniden başlatmak için `docker start drowsiness` kullanabilirsiniz.



## Kaynak koddan çalıştırma

Önce projeyi indirin:

```bash
git clone https://github.com/alabora33/drowsiness-detector.git
cd drowsiness-detector
```

Python 3.13 kuruluysa sanal ortam oluşturup paketleri yükleyebilirsiniz:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m app.main
```

Debian'da MediaPipe için bazı sistem paketleri de gerekebilir:

```bash
sudo apt install -y libgles2 libegl1 libgl1 libglib2.0-0t64
```

Sunucu başladıktan sonra yine **http://localhost:8000** adresine girin. Port başka bir uygulama tarafından kullanılıyorsa YAML dosyasındaki `server.port` değerini değiştirebilirsiniz.

## Ayarlar nasıl değiştiriliyor?

Projede üç hazır ayar dosyası var:

| Dosya | Kullanımı |
|---|---|
| `configs/default.yaml` | Normal kullanım, göz kapanma süresi 1.5 saniye |
| `configs/sensitive.yaml` | Daha erken uyarı için hassas ayarlar |
| `configs/night-driving.yaml` | Gece sürüşü için denediğim profil, göz kapanma süresi 1.2 saniye |

Docker imajını oluştururken hangi config dosyasının kullanılacağını seçebiliyorsunuz. Örneğin:

```bash
docker build --build-arg CONFIG_PATH=configs/night-driving.yaml \
  -t drowsiness-detector:night .
```

Bu komut gece sürüşü profilini imajın içine ekler. Yani ödevde istenen build sırasında config dosyası seçme özelliği korunuyor.

### Arayüzden ayar kaydetme (v0.1.1 geliştirmesi)

Yeni Ayarlar bölümünden EAR eşiği, göz kapanma süresi, göz açılma süresi, düşük ışık eşiği ve PERCLOS ayarları düzenlenebiliyor. **Kaydet** dediğinizde değerler kontrol ediliyor ve kamera açıksa yeni ayarlar sonraki karelerde kullanılıyor.

Bu geliştirmeyi kendi bilgisayarımda çalıştırmak için önce imajı oluşturdum:

```bash
docker build --build-arg CONFIG_PATH=configs/default.yaml \
  -t drowsiness-detector:dev .
```

Kaydedilen ayarların container silinip yeniden oluşturulsa da kalması için volume kullandım:

```bash
docker run --rm --name drowsiness-settings-test \
  -p 127.0.0.1:8080:8000 \
  -v drowsiness-settings:/app/data \
  drowsiness-detector:dev
```

Bu örnekte uygulama **http://localhost:8080** adresinde açılır. Ayarlar `/app/data/settings.yaml` dosyasına yazılır. Container'ı durdurup aynı volume ile tekrar çalıştırdığımda değişiklikler korunuyor.

Volume kullanmadan başlatılırsa ayarların container yeniden oluşturulduğunda korunacağı garanti değil.

## Uygulama nasıl çalışıyor?

Tarayıcıdan gelen JPEG kareleri WebSocket ile FastAPI sunucusuna iletiliyor. MediaPipe yüz ve göz noktalarını buluyor. Ardından EAR değeri hesaplanıyor. EAR değeri belirlenen eşikten düşükse göz kapalı kabul ediliyor.

Ayrıca PERCLOS yöntemiyle belirli bir zaman aralığında gözlerin ne kadar kapalı kaldığı hesaplanıyor. Bu sayede sadece uzun süreli kapanmalar değil, sık tekrarlanan kapanmalar da uyarı oluşturabiliyor.

Ekranda `UYANIK`, `GÖZLER KAPALI`, `UYUKLAMA UYARISI` ve `YÜZ YOK` durumlarını görebilirsiniz.

## Testler

Projede hem algoritma hem API ve WebSocket tarafı için otomatik testler var. Testleri çalıştırmak için:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m pytest -q
```

`feat/runtime-config` dalında son kontrolümde **121 test geçti**. Ayrıca Windows 11 + WSL2 ortamında gerçek kamerayla test yaptım. Kamera açıkken ayar değişikliği uygulanmasını ve Docker volume üzerinden ayarların korunmasını da kontrol ettim.

GitHub Actions ile pull request açıldığında test ve Docker kontrolleri çalışıyor. Sürüm yayınlandığında Docker imajı GHCR'a gönderiliyor. İlk sürüm `0.1.0`; `0.1.1` için ayar yönetimi geliştirmesi üzerinde çalışıyorum.

