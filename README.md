Made by Kallyan Biswas

Facebook: "Kallyan Biswas" (https://www.facebook.com/kallyan.biswas.29)

<p align="center">
  <img src="https://raw.githubusercontent.com/Mrbotrx/Mrbotrx/refs/heads/main/IPTV_LINKS_LOGO.jpg" width="140" alt="BD OTT Playlist Logo"/>
</p><h1 align="center">BD-OTT-PLAYLIST</h1><p align="center">
  <b>Advanced Auto-Updating IPTV Playlist System</b><br/>
  🇮🇳 India | 🇧🇩 Bangladesh | KB OTT
  <br/>
  Smart Channel Organization • Health Monitoring • Automated Updates
</p><p align="center">
  <a href="https://github.com/Mrbotrx/BD-OTT-PLAYLIST/actions/workflows/ind_bot.yml">
    <img src="https://github.com/Mrbotrx/BD-OTT-PLAYLIST/actions/workflows/ind_bot.yml/badge.svg" alt="IND.bot"/>
  </a>
  <a href="https://github.com/Mrbotrx/BD-OTT-PLAYLIST/actions/workflows/update.yml">
    <img src="https://github.com/Mrbotrx/BD-OTT-PLAYLIST/actions/workflows/update.yml/badge.svg" alt="AKASH OTT"/>
  </a>
  <img src="https://img.shields.io/badge/Python-3.12-blue?logo=python" alt="Python"/>
  <img src="https://img.shields.io/badge/Playlist-M3U%20%2F%20M3U8-green" alt="M3U"/>
  <img src="https://img.shields.io/badge/Automation-GitHub%20Actions-black?logo=githubactions" alt="GitHub Actions"/>
</p><p align="center">
  <a href="#-overview">Overview</a> ·
  <a href="#-playlists">Playlists</a> ·
  <a href="#-features">Features</a> ·
  <a href="#-how-it-works">How It Works</a> ·
  <a href="#-installation">Installation</a> ·
  <a href="#-supported-players">Players</a> ·
  <a href="#-বাংলা-গাইড">বাংলা গাইড</a>
</p>---

🚀 Overview

BD-OTT-PLAYLIST is an advanced automated IPTV playlist management project developed for India and Bangladesh.

The system uses Python and GitHub Actions to collect, organize, validate and generate regularly updated M3U/M3U8 playlists.

Designed with smart channel filtering, stream health monitoring, duplicate removal and intelligent category organization.

No dedicated hosting server is required.

---

✨ Features

- 🤖 Full Automation — Automated playlist generation.
- ⚡ Fast Processing — Concurrent stream checking.
- 🩺 Health Monitoring — Checks stream availability.
- 🧠 Smart Categories — Automatically organizes channels.
- 🔍 Duplicate Removal — Removes duplicate entries.
- ⭐ Channel Priority — Prioritizes popular channels.
- 💾 Smart Caching — Reduces repeated checks.
- 🔄 Automatic Updates — Scheduled playlist rebuilding.
- 📺 M3U Support — Standard M3U/M3U8 compatibility.
- 🌍 Multi-Region — India and Bangladesh playlist support.

---

📺 Playlists

Playlist| Update Frequency| Format
🇮🇳 India + Bangla VIP| Every 3 hours| M3U
🇧🇩 AKASH OTT| About every 58 minutes| M3U8

🇮🇳 India + Bangla VIP

https://raw.githubusercontent.com/Mrbotrx/BD-OTT-PLAYLIST/main/india/India_vip.m3u

🇧🇩 AKASH OTT

https://raw.githubusercontent.com/Mrbotrx/BD-OTT-PLAYLIST/main/kb_go_playlist.m3u8

«Copy your preferred playlist URL and add it to your IPTV player using the M3U URL option.»

---

🧠 Smart Channel Organization

The system is designed to organize channels into multiple categories.

Category| Description
⭐ Featured| Priority channels
🎬 Movies| Movie channels
📺 Entertainment| Entertainment channels
🎵 Music| Music channels
🏏 Sports| Sports channels
📰 News| News channels
🇮🇳 India| Indian television
🇧🇩 Bangla| Bangladeshi television
🌍 International| International channels
📡 Others| Additional channels

Actual categories depend on available source data.

---

🔄 How It Works

flowchart TD
    A[GitHub Actions] --> B[Load IPTV Sources]
    B --> C[Parse M3U / M3U8]
    C --> D[Normalize Channels]
    D --> E[Remove Duplicates]
    E --> F[Smart Categorization]
    F --> G[Stream Health Checks]
    G --> H[Channel Ranking]
    H --> I[Generate Playlist]
    I --> J[Publish Updated Files]
    J --> K[IPTV Players]

---

⚙️ Installation

Follow these steps to set up the project on your GitHub account.

Step 1 — Clone Repository

git clone https://github.com/Mrbotrx/BD-OTT-PLAYLIST.git

cd BD-OTT-PLAYLIST

Alternatively, fork the repository directly on GitHub.

Step 2 — Enable Workflow Permissions

Navigate to:

Settings
   ↓
Actions
   ↓
General
   ↓
Workflow permissions
   ↓
Read and write permissions

Save your changes.

Step 3 — Run Workflows

1. Open your GitHub repository.
2. Navigate to the Actions tab.
3. Select the workflow you want to execute.
4. Click Run workflow.

Available workflows:

- "IND.bot - India + Bangla VIP Auto Update"
- "AKASH OTT Auto Playlist"

---

📱 Supported Players

Compatible with standard M3U/M3U8 applications.

- VLC Media Player
- TiviMate
- OTT Navigator
- IPTV Smarters
- Kodi
- Other M3U-compatible players

---

🩺 Troubleshooting

<details>
<summary><b>Playlist is empty</b></summary>Check the GitHub Actions execution logs and verify that the configured sources are accessible.

Some streams may be geo-restricted or unavailable from GitHub-hosted runners.

</details><details>
<summary><b>Workflow failed</b></summary>Check the following:

- Python version.
- Dependency installation.
- GitHub workflow permissions.
- Source availability.
- YAML indentation.

</details><details>
<summary><b>Playlist is not updating</b></summary>Open the Actions tab and check the latest workflow execution. GitHub scheduled jobs may occasionally be delayed.

</details><details>
<summary><b>Some channels are missing</b></summary>Unavailable, restricted or incompatible streams may be excluded during validation.

</details>---

🇧🇩 বাংলা গাইড

BD-OTT-PLAYLIST একটি Advanced Automated IPTV Playlist Management Project।

এখানে Python এবং GitHub Actions ব্যবহার করে স্বয়ংক্রিয়ভাবে IPTV Playlist তৈরি ও আপডেট করা হয়।

প্রধান সুবিধা

- স্বয়ংক্রিয় Playlist Update।
- Working Stream যাচাই।
- Duplicate Channel বাদ দেওয়া।
- Smart Category System।
- Popular Channel Priority।
- M3U এবং M3U8 Support।
- Automated GitHub Actions।

Playlist ব্যবহার

নিচের যেকোনো লিংক কপি করে IPTV Player-এ M3U URL হিসেবে যুক্ত করুন।

India + Bangla VIP

https://raw.githubusercontent.com/Mrbotrx/BD-OTT-PLAYLIST/main/india/India_vip.m3u

AKASH OTT

https://raw.githubusercontent.com/Mrbotrx/BD-OTT-PLAYLIST/main/kb_go_playlist.m3u8

---

⚠️ Disclaimer

This project is intended for IPTV playlist organization, automation and stream availability monitoring.

It does not host, create, distribute or claim ownership of third-party television channels or media content.

Users are responsible for ensuring that they have appropriate authorization to access and use any included streams.

The project maintainers are not responsible for third-party content, availability or copyright-related issues.

---

🙏 Credits & Developer

Developer: Kallyan Biswas

Facebook: "Kallyan Biswas" (https://www.facebook.com/kallyan.biswas.29)

Team: KB Cyber Team

Repository: "Mrbotrx/BD-OTT-PLAYLIST" (https://github.com/Mrbotrx/BD-OTT-PLAYLIST)

If you like this project, please give the repository a ⭐.

Thank you for your support!

---

<p align="center">
  <b>Developed with ❤️ by Kallyan Biswas</b>
  <br/>
  <sub>BD-OTT-PLAYLIST | KB Cyber Team</sub>
</p>
