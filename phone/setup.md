# Putting Signal Lab on the Note 9

About 20 minutes, once. After this, new versions arrive through Settings → About.

## 1. Apps (you install these)

From **F-Droid** (<https://f-droid.org>), not the Play Store — the Play Store copies of Termux are
years out of date and don't work with Termux:API:

- **Termux**
- **Termux:API** (notifications and spoken alerts)
- **Termux:Boot** (optional: starts Signal Lab after the phone restarts)

Open Termux:Boot once after installing it, so Android lets it run at boot.

In Android Settings → Apps → Termux → Battery, choose **Unrestricted**, or Android will put
Signal Lab to sleep overnight.

## 2. Python and the tools (in Termux)

```sh
pkg update
pkg install python python-numpy termux-api curl unzip
pip install requests
```

## 3. The app (in Termux)

```sh
mkdir -p ~/signal-lab/versions ~/signal-lab/data
cd ~/signal-lab
curl -LO https://github.com/ikverse/Signal-Lab/releases/download/v0.2.0/signal-lab-v0.2.0.zip
unzip signal-lab-v0.2.0.zip -d versions/0.2.0 && rm signal-lab-v0.2.0.zip
echo 0.2.0 > current.txt
cp versions/0.2.0/phone/start.sh start.sh && chmod +x start.sh
```

## 4. The history (from the PC, then in Termux)

The phone can download its own candles, but copying the PC's database saves about an hour and
brings the backtest scorecard with it. With the phone on USB and USB debugging on, in
**PowerShell** in the `signal-lab` folder on the PC:

```powershell
adb push data\signal_lab.db /sdcard/Download/signal_lab.db
```

Then in Termux:

```sh
termux-setup-storage
cp ~/storage/downloads/signal_lab.db ~/signal-lab/data/signal_lab.db
```

## 5. Start it (in Termux)

```sh
~/signal-lab/start.sh
```

Leave Termux running in the background. To start it automatically after a reboot:

```sh
mkdir -p ~/.termux/boot
printf '#!/data/data/com.termux/files/usr/bin/sh\n~/signal-lab/start.sh\n' > ~/.termux/boot/signal-lab
chmod +x ~/.termux/boot/signal-lab
```

## 6. The screen

1. Open **http://127.0.0.1:8765** in Chrome on the phone.
2. Menu → **Add to Home screen**. The icon opens Signal Lab full-screen in landscape.
3. Plug the phone in and keep it on a stand. The app dims itself after two minutes untouched and
   shifts its layout a few pixels every few minutes to protect the AMOLED screen.

## Battery

The Note 9's battery is from 2018. Plugged in all day, check it now and then for swelling, and use a
charge limit if your One UI version offers one.

## Updates

Settings → About → **Check now**, then **Download**, then **Install and restart**. The new version
runs its own tests on the phone before it takes over; if they fail, nothing changes. **Roll back**
returns to the version before.
