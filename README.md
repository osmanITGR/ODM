<div align="center">

# ODM — Osman Download Manager

**দ্রুতগতির ডাউনলোড ম্যানেজার | Windows ও Android**

[![Download](https://img.shields.io/github/v/release/osmanITGR/ODM?label=Download%20ODM&style=for-the-badge&color=0078D4)](https://github.com/osmanITGR/ODM/releases/latest)

</div>

---

## 💻 কম্পিউটারে ইনস্টল (Windows)

১. উপরের **Download ODM** বাটনে ক্লিক করুন  
২. **ODM.exe** ফাইলটি ডাউনলোড করুন  
৩. ফাইলটিতে ডাবল-ক্লিক করুন → **Install** বাটনে ক্লিক করুন  
৪. ব্যস! ডেস্কটপে ODM-এর আইকন চলে আসবে।

> ⚠️ **Windows সতর্কবার্তা দেখালে:** "More info" → "Run anyway" ক্লিক করুন।  
> এটি ভাইরাস নয় — নতুন সফটওয়্যারে ডিজিটাল সার্টিফিকেট না থাকলে Windows এমন দেখায়।

---

## 📱 মোবাইলে ইনস্টল (Android)

১. উপরের **Download ODM** বাটনে ক্লিক করে **ODM-Android.apk** নামান  
২. ফাইলটিতে ট্যাপ করুন  
৩. "Install blocked" এলে → **Settings** → **Allow from this source** চালু করুন  
৪. Play Protect সতর্ক করলে → **More details** → **Install anyway**

> ⚠️ Play Store-এর বাইরের যেকোনো অ্যাপে Android এই বার্তা দেখায়। এটি ভাইরাস নয়।

**ভিডিও ডাউনলোড করার সবচেয়ে সহজ উপায়:** যেকোনো অ্যাপে ভিডিওর
**Share** বাটনে ট্যাপ করে তালিকা থেকে **ODM** বেছে নিন।

ডাউনলোড করা ফাইল জমা হবে ফোনের **Download → ODM** ফোল্ডারে।

---

## ✨ কী কী করতে পারবেন

| ফিচার | বিবরণ | 💻 | 📱 |
|---|---|:-:|:-:|
| ⚡ **দ্রুত ডাউনলোড** | একটি ফাইলকে ৩২টি ভাগে ভেঙে একসাথে নামায় — ব্রাউজারের চেয়ে কয়েকগুণ দ্রুত | ✅ | ✅ |
| ⏸️ **থামানো ও চালু করা** | অ্যাপ বা কম্পিউটার বন্ধ করলেও ডাউনলোড নষ্ট হয় না | ✅ | ✅ |
| 🎬 **ভিডিও ডাউনলোড** | Facebook, Instagram, TikTok সহ বহু সাইট থেকে | ✅ | ✅ |
| 📋 **Download Queue** | একসাথে অনেক ফাইল সারিবদ্ধভাবে ডাউনলোড | ✅ | ✅ |
| 📶 **Speed Limit** | ইন্টারনেটের কতটুকু ব্যবহার করবে নিজে ঠিক করুন | ✅ | ✅ |
| 🌐 **Browser Integration** | Chrome/Edge-এর ডাউনলোড সরাসরি ODM-এ চলে আসবে | ✅ | — |
| ⏰ **Scheduling** | নির্দিষ্ট সময়ে (যেমন রাত ২টা–৬টা) ডাউনলোড চালানো | ✅ | — |
| 📤 **Share করে ডাউনলোড** | যেকোনো অ্যাপ থেকে লিংক share করলেই ODM ধরবে | — | ✅ |
| 📵 **শুধু Wi-Fi** | মোবাইল ডেটায় ডাউনলোড বন্ধ রাখে, MB বাঁচায় | — | ✅ |

---

## 🎬 ভিডিও ডাউনলোড সম্পর্কে

**কোন সাইট থেকে কাজ করবে:**

| | সাইট |
|---|---|
| ✅ কাজ করবে | Facebook, Instagram, TikTok, Twitter/X, Vimeo, Dailymotion, Reddit, সরাসরি ভিডিও লিংক |
| ⚠️ মাঝে মাঝে | YouTube — তারা নিয়মিত নিয়ম বদলায় |
| ❌ কখনোই নয় | Netflix, Amazon Prime, Hotstar — এগুলো বিশেষভাবে সুরক্ষিত, কোনো অ্যাপই পারে না |

**💻 Windows-এ একটি অতিরিক্ত ধাপ (ঐচ্ছিক):**

বেশিরভাগ ভিডিওর ছবি ও শব্দ আলাদা থাকে। জোড়া লাগাতে **ffmpeg** লাগে।
Start মেনুতে **PowerShell** খুলে নিচের লাইনটি লিখে Enter চাপুন:

`winget install Gyan.FFmpeg`

এটি ছাড়াও ODM চলবে, তবে কিছু ভিডিওর মান সীমিত থাকবে।

**📱 মোবাইলে এটি লাগে না** — সেখানে জোড়া লাগানো নিজে থেকেই হয়।

---

## 🌐 Browser Integration সেটআপ

১. ODM খুলুন → **Settings → Browser integration**  
২. **Start bridge** → **Copy token** ক্লিক করুন  
৩. Chrome-এ যান: chrome://extensions  
৪. **Developer mode** চালু করুন  
৫. **Load unpacked** চাপুন → এই ফোল্ডার দিন: C:\Users\<আপনার নাম>\AppData\Local\ODM\extension  
৬. Extension popup-এ token পেস্ট করে **Save** চাপুন  

---

## 🗑️ আনইনস্টল করতে

**💻 Windows:** Settings → Apps → Installed apps → ODM → Uninstall  
**📱 Android:** অ্যাপের আইকন চেপে ধরে রাখুন → Uninstall

---

<div align="center">

## 📞 সাহায্য দরকার হলে

**Osman IT**  
WhatsApp: [+8801625251930](https://wa.me/8801625251930)

</div>
