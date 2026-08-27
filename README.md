# Shorts Automation 🎬

نظام آلي ينتج ويرفع **3 فيديوهات YouTube Shorts يومياً** (فئات: Explain / Mystery / What If) بالكامل مجاناً، ويشتغل **24/7 على GitHub Actions** — بدون أي كمبيوتر شخصي.

Automated pipeline producing 3 YouTube Shorts per day (Explain • Mystery • What-If) fully free, running 24/7 on GitHub Actions (no personal PC needed).

---

## 🧠 كيف يعمل (How it works)

| المرحلة | أداة | 
|---------|------|
| 1. توليد السكربت/العنوان/الوصف/التاغز | **Gemini API** |
| 2. توليد 16 صورة FHD + 8 غطاء | **Cloudflare Workers AI** (FLUX-2 klein) |
| 3. صور احتياطية عند امتلاء الرصيد | **Pollinations** → **OpenVerse** |
| 4. الصوت (عربي) + الترجمة + الحركة | **edge-tts** + **FFmpeg** (karaoke subs) |
| 5. فحص الجودة (الصوت/النص/الوزن) | مدمج بالـ pipeline |
| 6. الرفع والنشر المجدول | **YouTube Data API v3** |

---

## 🕒 جدول النشر (الستة المحددة بتوقيت أمريكا الشرقية)

| الفئة | تجهيز (UTC) | **النشر المجدول** |
|-------|-------------|-------------------|
| Explain | 11:00 | **00:00 UTC = 20:00 US Eastern** |
| Mystery | 12:00 | **01:00 UTC = 21:00 US Eastern** |
| What If | 13:00 | **02:00 UTC = 22:00 US Eastern** |

> الفيديو يُجهّز قبل النشر بساعات، يُرفع `private` مع `publishAt` — يوتيوب ينشر لوحده بالثانية المحددة. فشل الرفع = **محاولة واحدة فقط** ثم إيقاف.

---

## 🗝️ الأسرار المطلوبة (GitHub Secrets)

```
CF_TOKEN           # Cloudflare API token (Térülések/workers_ai)
CF_ACCOUNT         # Cloudflare account ID
GEMINI_API_KEY     # Google AI Studio key
POLLINATIONS_KEY   # Pollinations API key
YT_CLIENT_ID       # Google OAuth client id
YT_CLIENT_SECRET   # Google OAuth client secret
YT_REFRESH_TOKEN   # Long-lived YouTube refresh token
```

---

## ⚙️ التشغيل

### السحاب (الحل الرسمي) — يعمل تلقائياً:
1. ارفع هذه الملفات إلى مستودع (هذا المستودع).
2. ضع الأسرار أعلاه في `Settings → Secrets and variables → Actions`.
3. `daily-shorts` يعمل تلقائياً حسب الجدول. أو فعّله يدوياً: `Actions → daily-shorts → Run workflow`.

### محلياً (تشخيص/تجربة):
```bash
pip install -r requirements.txt
set GEMINI_API_KEY=...        # أو عدّل config.json
set CF_TOKEN=...
set CF_ACCOUNT=...
set YT_CLIENT_ID=...
set YT_CLIENT_SECRET=...
set YT_REFRESH_TOKEN=...
set CATEGORY=explained        # explained | mystery | whatif
set PUBLISH_HOUR_UTC=0        # ساعة النشر المجدول
python pipeline.py
```
- **Linux**: يتطلب `ffmpeg` + خط ‏DejaVu/Noto (مثبت آلياً بالمستودع؛ الخطوط العربية مرفقة في `fonts/`).
- **Windows**: استخدم ffmpeg المرفق أو من PATH؛ مسار الخطوط يُقرأ من `BASE/fonts`.

---

## 📁 بنية الملفات

```
├─ pipeline.py          # المحرّك الرئيسي (توليد → مونتاج → جودة → رفع)
├─ youtube_upload.py    # رفع يوتيوب + publishAt
├─ config.json          # إعدادات + مفاتيح (من env للسحاب)
├─ requirements.txt
├─ .github/workflows/shorts.yml   # 3 وظائف (explained/mystery/whatif) + إعادة محاولة واحدة
└─ fonts/               # Arial Bold + Impact (ترجمة الفيديو)
```

---

## ⚠️ ملاحظات

- سقف Cloudflare المجاني: **10,000 neuron/يوم** ≈ **3 فيديوهات كاملة فقط** — لا تشغّل أكثر.
- إذن YouTube من نوع `youtube.upload` فقط (رفع)، التطبيق في وضع **Production**.
- حافظ على مفاتيحك — لا ترفع `token.json` أو `config.json` بمفاتيح حقيقية للمستودع.

---

## 📦 للمطوّرين / أدوات ذكاء اصطناعي أخرى
إذا تسلمت هذا المجلد مجدداً:
1. شغّل `pipeline.py` مرة للتحقق (يتطلب Python 3.11 + الأنصارات أعلاه).
2. للسياق الكامل انظر git history وملفات `.github/workflows/`.
3. لا تكتب أسراراً جديدة في ملفات — استخدم var البيئة أو GitHub Secrets.