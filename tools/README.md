# 外部工具目录

`tools.json` 用于登记工具箱的外部程序与分类。

# 工具资源备份与打包

第三方程序、驱动和 SDK 附件由独立的 GitHub 仓库 `AnhuToolbox-tools` 保存，
并在本目录留下 `tools.gresource` 清单。完整安装包的打包命令会自动检查该清单，
避免缺少工具文件时生成不完整的安装包。

从 GitHub 恢复工具附件：

```powershell
git clone git@github.com:Jinchoo-zhu/AnhuToolbox-tools.git ..\AnhuToolbox-tools
powershell -NoProfile -File ..\AnhuToolbox-tools\restore_tools.ps1 -ProjectRoot ..\AnhuToolbox
```

<!-- 以下保留原有的工具资源说明 -->

Hikvision SDK demos, reader utilities, disk utilities, and other third-party binaries
are separate from the main source repository because of their size and licensing.
