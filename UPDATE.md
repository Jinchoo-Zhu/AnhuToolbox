# AnhuToolbox 自动更新发布说明

百宝箱从 GitHub Release 的固定地址读取更新清单：

```text
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
installer\AnhuToolbox_Setup_1.0.0.exe
installer\latest.json
```

3. 在 GitHub 创建与版本对应的标签，例如 `v1.0.0`。
4. 发布正式 Release，上传安装包和 `installer\latest.json`。
5. 确认 Release 不是 Draft，也不是 Pre-release。

只提交源码或只上传到 `main` 分支不会触发更新；必须发布 Release。

## 更新流程

1. 百宝箱启动后在后台读取 `latest.json`，运行期间每 4 小时复查一次。
2. 如果远端版本更高，在底部信息栏显示“发现新版本”提示，不主动打断当前操作。
3. 用户点击提示后，显示更新内容、下载大小和“立即更新并重启”操作，
   并明确提示安装完成后会自动重新启动。
4. 用户确认后下载到 `%LOCALAPPDATA%\AnhuToolbox\updates`。
5. 下载完成后校验大小与 SHA-256。
6. 百宝箱启动临时 `AnhuUpdater.exe` 并退出。
7. 更新器等待旧进程退出，静默运行 Inno Setup 安装包。
8. 安装成功后重新打开百宝箱；失败时重新打开旧版本。

## 安全说明

- 安装包地址必须属于固定 GitHub 仓库的 Release。
- 更新清单包含版本、SHA-256、文件大小和更新说明。
- 当前没有代码签名证书，Windows 可能显示 SmartScreen 提示。
- 不要使用自签名证书冒充公开发行证书；它不会被其他用户的电脑信任。
- 以后取得正式代码签名证书后，应先签名主 EXE、更新器和安装包。

## 测试更新

发布测试版本时，将版本号提高到当前安装版本以上。安装旧版本后启动百宝箱，
确认提示、下载进度、哈希校验、安装、重启和失败恢复均正常，再进行正式发布。
