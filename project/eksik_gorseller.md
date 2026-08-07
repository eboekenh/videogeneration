# Eksik Görseller Raporu (güncellendi)

Kaynak: `project/storyboard.json` (V4'ten türetildi, 485 sahne)

## Ne yapıldı

- **64 görsel** — storyboard'un zaten referans verdiği mevcut panel/görseller `example/images/` → `project/images/` klasörüne kopyalandı.
- **114 görsel** — storyboard'da `BLACK / NEW IMAGE NEEDED` ya da bulunamayan `Old Homer Writing The Iliad.png` olarak işaretli ama videoda (`odyseus bis 420 minus 120 140.mp4`, 00:00–38:12 arası) gerçekten var olan sahneler için videodan kare çıkarıldı, `project/images/recovered_scene_XXX.jpg` olarak kaydedildi ve `project/storyboard.json`'daki `image` alanı buna göre güncellendi.
- **Toplam:** `project/images/` içinde **178 görsel** var, storyboard artık 449/485 sahne için gerçek görsele sahip.

## Hâlâ eksik: 35 sahne

Video 38:12'de bittiği için (storyboard 48:30'a kadar gidiyor), bu 35 sahne videodan kurtarılamadı. Detaylı liste: `project/eksik_gorseller.csv`.

| Bölüm | Eksik sahne |
|---|---|
| DİLENCİ, KÖPEK VE YAY | 18 |
| HOMEROS'UN SONU VE NOLAN'IN YENİ SONU | 9 |
| KAHRAMAN MI, DÜZENBAZ MI? | 8 |

## Not

`recovered_scene_XXX.jpg` dosyaları videodan tek kare olarak alındı (sahne başlangıcına yakın bir zamanda, crossfade geçişinden kaçınmak için +1sn içeriden), bu yüzden orijinal kaynak görsellere göre biraz daha düşük çözünürlüklü olabilir (video 1280×720). Final render öncesi göz atman iyi olur.

Render için hâlâ eksik olanlar: `project/audio.mp3` (seslendirme) ve 35 sahne için yeni görsel.
