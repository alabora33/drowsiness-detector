# Drowsiness Detector – Kurulum ve Kullanım Kılavuzu

Bu dokümanda Drowsiness Detector uygulamasının Debian 13 ve Ubuntu ortamlarında nasıl kurulacağını ve çalıştırılacağını anlattım.

Uygulama, bilgisayar kamerasından alınan görüntülerle gözlerin açık veya kapalı olduğunu takip eder. Gözler belirli bir süre kapalı kaldığında veya sık sık kapandığında kullanıcıya uyarı verir.

Uygulamayı Docker üzerinden veya doğrudan Python ile çalıştırabilirsiniz.

## 1. Sistem gereksinimleri

- Debian 13 veya Ubuntu (Docker için)
- Docker veya Python 3.13
- İlk kurulum için internet bağlantısı
- Chrome veya Edge tarayıcısı
- Kamera

Uygulamayı Debian 13 ve Windows 11 üzerinde Ubuntu WSL2 ortamında test ettim. Gerçek kamera testlerini Windows bilgisayarda gerçekleştirdim.

Kamera tarayıcı üzerinden kullanıldığı için Docker'a ayrıca kamera bağlamak gerekmiyor.

## 2. Docker kurulumu

Bilgisayarınızda Docker zaten kuruluysa bu adımı geçebilirsiniz.

Debian veya Ubuntu terminalinde:

```bash
sudo apt update
sudo apt install -y docker.io
```

Docker servisini başlatın:

```bash
sudo systemctl enable --now docker
```

Kurulumu kontrol edin:

```bash
sudo docker --version
sudo docker info
```

Bu yöntem, dağıtımın paket deposundaki Docker sürümünü kurar. En güncel Docker Engine veya Buildx özellikleri gerektiğinde Docker'ın resmî deposundan kurulum tercih edilmelidir.

**Windows ve WSL2 kullananlar:** Docker Desktop kuruluysa WSL içine ayrıca Docker yüklemeniz gerekmez. Docker Desktop → Settings → Resources → WSL Integration bölümünden kullandığınız dağıtımı etkinleştirin.

## 3. Uygulamayı Docker ile çalıştırma

Önce yayınlanan Docker imajını indirin:

```bash
sudo docker pull ghcr.io/alabora33/drowsiness-detector:0.1.0
```

Ardından uygulamayı başlatın:

```bash
sudo docker run -d \
  --name drowsiness \
  -p 127.0.0.1:8000:8000 \
  ghcr.io/alabora33/drowsiness-detector:0.1.0
```

Tarayıcıda **http://localhost:8000** adresini açın.

**Başlat** butonuna basıp kameraya izin verdiğinizde uygulama çalışmaya başlayacaktır.

### Uygulamayı durdurma ve yeniden başlatma

Durdurmak için:

```bash
sudo docker stop drowsiness
```

Yeniden başlatmak için:

```bash
sudo docker start drowsiness
```

Container'ı kaldırmak için:

```bash
sudo docker rm -f drowsiness
```

Logları görmek için:

```bash
sudo docker logs -f drowsiness
```

## 4. Uygulamayı farklı ayarlarla çalıştırma

Projede üç farklı yapılandırma dosyası bulunmaktadır:

| Dosya | Açıklama |
|---|---|
| `default.yaml` | Varsayılan ayarlar |
| `sensitive.yaml` | Daha erken uyarı veren hassas profil |
| `night-driving.yaml` | Gece sürüşü için hazırladığım deneysel profil |

Gece sürüşü profilinde göz kapanma uyarısı süresini 1,5 saniyeden 1,2 saniyeye düşürdüm. Bu ayarlarla oluşturduğum Docker imajını gerçek kamerada test ettim.

Önce projeyi indirin:

```bash
sudo apt install -y git

git clone https://github.com/alabora33/drowsiness-detector.git
cd drowsiness-detector
```

Gece sürüşü ayarlarıyla Docker imajı oluşturmak için:

```bash
sudo docker build \
  --build-arg CONFIG_PATH=configs/night-driving.yaml \
  -t drowsiness-detector:night .
```

Oluşturulan imajı çalıştırın:

```bash
sudo docker run --rm \
  --name drowsiness-night \
  -p 127.0.0.1:8080:8000 \
  drowsiness-detector:night
```

Tarayıcıdan **http://localhost:8080** adresini açın.

Farklı bir profil kullanmak için `CONFIG_PATH` değerini `configs/default.yaml` veya `configs/sensitive.yaml` olarak değiştirebilirsiniz.

### İmajı yeniden oluşturmadan ayar değiştirme

Proje klasöründeyken:

```bash
sudo docker run --rm \
  --name drowsiness-custom \
  -p 127.0.0.1:8080:8000 \
  -v "$PWD/configs/night-driving.yaml:/config/custom.yaml:ro" \
  -e APP_CONFIG=/config/custom.yaml \
  ghcr.io/alabora33/drowsiness-detector:0.1.0
```

Bu şekilde farklı ayarları imajı yeniden oluşturmadan kullanabilirsiniz.

## 5. Docker kullanmadan Python ile çalıştırma

Uygulamayı Debian 13 üzerinde doğrudan Python 3.13 ile de çalıştırabilirsiniz. Ubuntu kullanıyorsanız Python 3.13'ün kurulu olması gerekir.

Proje klasöründe gerekli paketleri yükleyin:

```bash
sudo apt update
sudo apt install -y \
  python3-venv python3-pip \
  libgles2 libegl1 libgl1 libglib2.0-0t64
```

Python sanal ortamını oluşturun:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Gerekli kütüphaneleri yükleyin:

```bash
python -m pip install -r requirements.txt
```

Uygulamayı başlatın:

```bash
python -m app.main
```

Tarayıcıdan **http://localhost:8000** adresine girin.

Farklı bir profille çalıştırmak için:

```bash
APP_CONFIG=configs/night-driving.yaml python -m app.main
```

## 6. Uygulamanın kullanımı

Uygulama açıldıktan sonra **Başlat** butonuna basın ve kamera izni verin.

Ekranda şu durumlar gösterilir:

| Durum | Anlamı |
|---|---|
| UYANIK | Gözler açık |
| GÖZLER KAPALI | Göz kapanması algılandı |
| UYUKLAMA UYARISI | Göz kapanma süresi veya sıklığı uyarı seviyesine ulaştı |
| YÜZ YOK | Kamera görüntüsünde yüz bulunamadı |

Varsayılan ayarlarda gözler yaklaşık 1,5 saniye kapalı kaldığında uyarı oluşur.

Uygulama ayrıca PERCLOS yöntemiyle gözlerin belirli bir süre içindeki kapanma oranını hesaplar. Sık göz kapanmalarında da uyarı verebilir.

Uyarının sebebi ekranda gösterilir.

## 7. Windows 11 ve WSL2 üzerinde test

Uygulamayı Windows 11 üzerinde Ubuntu WSL2 ve Docker Desktop ile test ettim.

İzlediğim adımlar:

1. Docker Desktop'ı başlattım.
2. WSL2 terminalinde Docker imajını çalıştırdım.
3. Windows tarayıcısından `http://localhost:8080` adresini açtım.
4. Kameraya izin verdim.
5. Gözlerimi belirli sürelerle kapatarak uyarıları kontrol ettim.

Gece sürüşü profiliyle yaptığım Docker testinde **409 kamera karesi işlendi**. Yaklaşık 1,2 saniyelik göz kapanmalarında uyarı oluştu. PERCLOS kontrolü de çalıştı.

Bu testle uygulamanın Docker içinde çalışırken tarayıcı kamerasından gelen görüntüleri işleyebildiğini doğruladım.