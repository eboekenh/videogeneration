# Bu sürümde yapılan değişiklikler

Bağlantısı verilen Gemini YouTube Automation projesinin eğitim videosu odaklı akışı, Odysseus ve benzeri anlatı videolarına uygun olacak şekilde yeniden tasarlandı.

## Kaldırılan varsayımlar

- Gemini'nin sıfırdan 7–8 slaytlık ders yazması
- Her slayt için İngilizce gTTS sesi oluşturulması
- Pexels'tan otomatik ve kontrolsüz görsel seçilmesi
- Video üretildikten hemen sonra otomatik olarak YouTube'a yüklenmesi

## Eklenenler

- Mevcut uzun ses kaydını ana anlatım olarak kullanma
- Cümle bazlı `start` / `end` zamanları
- Görsel dosyasını storyboard'dan kesin olarak seçme
- Eksik ve tekrar eden görsel raporu
- Zaman boşluğu, üst üste binme ve ses süresi kontrolü
- Titreşimsiz zoom ve pan hareketleri
- Crossfade geçişler
- Arka plan müziğini düşük sesle karıştırma
- Hızlı 540p preview ve 1080p final seçenekleri
- Sahne cache sistemi
- Faster Whisper ile isteğe bağlı otomatik cümle hizalama
- Manuel GitHub Actions workflow'u

İlk güvenli kullanım sırası: `validate` → ilk 10 sahnelik `preview` → tüm preview → 1080p final.
