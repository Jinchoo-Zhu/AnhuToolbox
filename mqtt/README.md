# MQTT Broker Runtime

`mqtt/broker/` contains a minimal runtime extracted from the official
Mosquitto 2.1.4 Windows x64 package:

<https://mosquitto.org/files/binary/win64/mosquitto-2.1.4-install-windows-x64.exe>

Installer SHA-256:
`034017c8f8e3b5b86bdbd971f6c5184370311058e4de7b96a0f10204bbb9e7c8`

It is used only as an optional local broker while AnhuToolbox is running; it
is not registered as a Windows service.

Included license files:

- `NOTICE.md`
- `edl-v10`
- `epl-v20`

The installer copies this directory to `lib/mqtt/broker` only when the user
selects "安装 MQTT 服务端" on the optional runtime components page.
