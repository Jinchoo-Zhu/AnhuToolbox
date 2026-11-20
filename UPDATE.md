# AnhuToolbox 自动更新发布说明

百宝箱按以下顺序读取多个更新源，并选择其中版本最高的有效清单：

```text
https://mcsgzy.online:8443/anhutoolbox/updates/latest.json
https://github.com/Jinchoo-Zhu/AnhuToolbox/releases/latest/download/latest.json
```

## 发布新版本

1. 修改 `anhutoolbox/version.py`、`version_info.txt` 和 `installer.iss`，
   三处版本必须一致。
2. 构建程序、更新器、安装包并生成 `latest.json`：

```powershell
.\build_release.ps1 -Notes "本次更新内容"
```

生成文件：

```text
dist\AnhuUpdater.exe
installer\AnhuToolbox_Setup_1.0.4.exe
installer\latest.json
```

3. 将安装包复制到服务器的版本目录：

```text
F:\Services\anhutoolbox\releases\v1.0.4\
```

4. 将生成的 `installer\latest.json` 覆盖到：

```text
F:\Services\anhutoolbox\updates\latest.json
```

5. 确认下面两个地址可以匿名访问：

```text
https://mcsgzy.online:8443/anhutoolbox/releases/v1.0.4/AnhuToolbox_Setup_1.0.4.exe
https://mcsgzy.online:8443/anhutoolbox/updates/latest.json
```

`latest.json` 同时包含自建服务器和 GitHub 的安装包地址。用户下载时先使用
自建服务器，失败后自动回退到 GitHub。

## 更新流程

1. 百宝箱启动后在后台读取 `latest.json`，运行期间每 4 小时复查一次。
   标签栏右上角“关于”窗口也提供“检查更新”入口，可立即手动检查。
2. 如果远端版本更高，在标签栏右上角显示“发现新版本”提示，不主动打断当前操作。
3. 用户点击提示后，显示更新内容、下载大小和“立即更新并重启”操作，
   并明确提示安装完成后会自动重新启动。
4. 用户确认后下载到 `%LOCALAPPDATA%\AnhuToolbox\updates`。
   下载窗口支持“后台更新”，隐藏后主程序仍可继续使用，并可从顶部提示恢复进度。
5. 下载完成后校验大小与 SHA-256。
6. 询问用户是否立即安装并自动重启；暂不安装时保留下载结果和顶部安装入口。
7. 用户确认后，百宝箱启动临时 `AnhuUpdater.exe` 并退出。
8. 更新器等待旧进程退出，静默运行 Inno Setup 安装包。
9. 安装成功后重新打开百宝箱；失败时重新打开旧版本。

## 安全说明

- 安装包地址必须属于自建服务器的固定发布目录；
  同时接受原 GitHub Release 地址作为备用下载源。
- 更新清单包含版本、SHA-256、文件大小和更新说明。
- 当前没有代码签名证书，Windows 可能显示 SmartScreen 提示。
- 不要使用自签名证书冒充公开发行证书；它不会被其他用户的电脑信任。
- 以后取得正式代码签名证书后，应先签名主 EXE、更新器和安装包。

## 测试更新

发布测试版本时，将版本号提高到当前安装版本以上。安装旧版本后启动百宝箱，
确认提示、下载进度、哈希校验、安装、重启和失败恢复均正常，再进行正式发布。
