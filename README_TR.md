# Mitoloji Video Otomasyonu — Odysseus Sürümü

Bu repo, hazır bir ses kaydını ve cümle bazlı storyboard'u kullanarak görselleri doğru sırada birleştirir. Orijinal projedeki “Gemini yeni ders yazsın, gTTS seslendirsin, Pexels'tan rastgele görsel bulsun” akışı yerine **mevcut script + mevcut audio + seçilmiş görseller** esas alınır.

## Neler yapıyor?

- Her cümleyi storyboard'daki `start` ve `end` sürelerine göre gösterir.
- `zoom_in`, `zoom_out`, `pan_left`, `pan_right`, `pan_up`, `pan_down` ve `static` hareketlerini destekler.
- Hareketleri FFmpeg ile üretir; rastgele titreme eklemez.
- Görseller arasında crossfade geçişi yapabilir.
- Konuşma sesini korur, isteğe bağlı arka plan müziğini düşük seviyede karıştırır.
- Eksik görsel, zaman boşluğu, üst üste binen sahne ve tekrar kullanılan görseller için rapor verir.
- Önce düşük çözünürlüklü preview, sonra 1080p final üretilebilir.
- Render edilen sahneleri cache'ler; küçük bir değişiklikte her şeyi baştan render etmez.
- İsteğe bağlı Faster Whisper aracıyla zaman damgasız cümleleri ses kaydına hizalar.

## 1. Kurulum

Python 3.10–3.12 ve FFmpeg önerilir.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

FFmpeg ayrıca sistemde kurulu ve `PATH` içinde olmalıdır.

## 2. Proje dosyalarını yerleştir

```text
project/
├── audio.mp3
├── storyboard.json
├── images/
│   ├── 001_odysseus.jpg
│   ├── 002_trojan_horse.jpg
│   └── ...
└── music/
    └── background.mp3   # isteğe bağlı
```

## 3. Storyboard formatı

```json
{
  "title": "Odysseus",
  "scenes": [
    {
      "id": 1,
      "sentence": "Odiseus kimdir?",
      "image": "001_odysseus.jpg",
      "start": 0.0,
      "end": 3.7,
      "motion": "zoom_in",
      "focus_x": 0.5,
      "focus_y": 0.4,
      "zoom": 1.08
    }
  ]
}
```

`focus_x` ve `focus_y` 0 ile 1 arasındadır. Örneğin yüz görselin sağındaysa `focus_x: 0.72` kullanılabilir.

## 4. Önce storyboard'u kontrol et

```bash
python validate_storyboard.py \
  --storyboard project/storyboard.json \
  --audio project/audio.mp3 \
  --images project/images \
  --report output/validation-report.json
```

## 5. İlk 10 sahnelik hızlı preview

```bash
python build_video.py \
  --storyboard project/storyboard.json \
  --audio project/audio.mp3 \
  --images project/images \
  --music project/music/background.mp3 \
  --output output/odysseus_preview.mp4 \
  --preview \
  --max-scenes 10
```

## 6. 1080p final video

```bash
python build_video.py \
  --storyboard project/storyboard.json \
  --audio project/audio.mp3 \
  --images project/images \
  --music project/music/background.mp3 \
  --output output/odysseus_final_1080p.mp4
```

Müzik istemiyorsan `--music ...` satırını kaldır.

## Zaman damgası yoksa otomatik hizalama

Bu özellik için:

```bash
pip install -r requirements-whisper.txt
```

Storyboard'da geçici `duration` değerleri bulunabilir. Daha sonra:

```bash
python align_storyboard.py \
  --storyboard project/storyboard_untimed.json \
  --audio project/audio.mp3 \
  --output project/storyboard.json \
  --model small \
  --language tr
```

Araç ayrıca `.alignment-report.json` oluşturur. Skoru düşük sahneler elle kontrol edilmelidir; otomatik hizalama kusursuz kabul edilmemelidir.

## Eksik görselleri siyah bırakmak

```bash
python build_video.py ... --allow-missing
```

Bu seçenek, eksik görsel bulunan sahnelerde siyah placeholder üretir. Final render'dan önce validation raporundaki eksikleri düzeltmek daha iyidir.

## Demo

```bash
python scripts/create_demo_assets.py
python build_video.py \
  --storyboard example/storyboard.example.json \
  --audio example/demo_audio.wav \
  --images example/images \
  --music example/demo_music.wav \
  --output output/demo.mp4 \
  --preview
```

## GitHub Actions

`.github/workflows/build-video.yml` manuel çalışır. GitHub'a büyük ses ve görselleri eklemek repo boyutunu hızla artırabilir; uzun videolar için lokal bilgisayar veya Colab daha pratiktir. Workflow kullanılacaksa proje dosyalarını `project/` altında hazırlayıp Actions sekmesinden **Build mythology video** çalıştırılır.

## Önemli not

Crossfade açıkken sahneler teknik olarak çok kısa bir süre üst üste görünür; toplam video süresi yine storyboard süresine eşit tutulur. Tam ve sert cümle sınırları istenirse `--transition none` kullanılır.
