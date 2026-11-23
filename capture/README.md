# Packet Capture Runtime

This directory contains the TShark/Dumpcap runtime used only by the
AnhuToolbox packet-capture page. The Wireshark GUI is not included or launched.

- Source: Wireshark 4.6.10 official Windows x64 distribution.
- Wireshark/TShark license: GNU General Public License v2 or later.
- License text: `engine/COPYING.txt`.
- Upstream source: https://gitlab.com/wireshark/wireshark
- Npcap: `npcap/npcap-1.89.exe`, distributed according to Npcap's license.

The runtime is copied by PyInstaller into `lib/capture/engine`, and the Npcap
installer is copied into `lib/capture/npcap` in the installed application.
