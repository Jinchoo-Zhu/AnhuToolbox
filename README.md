# AnhuToolbox

AnhuToolbox 是面向串口、TCP 通信和日常数据处理的 Windows 桌面工具集。

主要功能包括串口及 TCP 收发、HEX/ASCII 转换、校验计算、预设命令、批量二维码、
JSON 美化、正则测试、文本对比、列表排序、编码和金额转换，以及可扩展的外部工具集。

## 从 GitHub 获取源码

安装 [Git](https://git-scm.com/download/win)，然后在 PowerShell 中执行：

```powershell
cd D:\TestCode
git clone git@github.com:Jinchoo-zhu/AnhuToolbox.git
cd .\AnhuToolbox
```

GitHub 的 SSH 需要在本机配置公钥。首次使用时可以按照
[GitHub SSH 文档](https://docs.github.com/zh/authentication/connecting-to-github-with-ssh)
添加密钥。新电脑如果没有配置 SSH，也可以使用 HTTPS 地址：

```powershell
git clone https://github.com/Jinchoo-zhu/AnhuToolbox.git
cd .\AnhuToolbox
```

`tools` 目录包含打包需要的第三方工具、SDK 和资料，克隆时必须完整下载，
不要单独删除或改名。

## 安装和运行

需要 Windows 和 [Python 3.10 或更高版本](https://www.python.org/downloads/windows/)。
下列步骤使用项目自己的虚拟环境，不影响电脑上的其他 Python 项目：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python .\verify_tools.py
python .\main.py
```

直接运行 `python .\main.py` 时，应用会读取本目录下的 `tools` 文件夹。
工具附件如需恢复，重新从 GitHub 下载对应文件，或重新完整克隆项目。

如果 PowerShell 禁止激活虚拟环境，可以只执行下面命令，或者按
[虚拟环境激活说明](https://docs.python.org/zh-cn/3/library/venv.html#how-venvs-work)
调整本机的执行策略：

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

## 生成 EXE 和安装包

先激活虚拟环境、确认工具完整，再执行 PyInstaller：

```powershell
.\.venv\Scripts\Activate.ps1
python .\verify_tools.py
pyinstaller --noconfirm --clean .\AnhuToolbox.spec
```

在 [AnhuToolbox.spec](AnhuToolbox.spec) 中，工具清单和附件都会在生成程序前自动校验；
缺少或损坏时会中止打包，防止出现功能不完整的 EXE。

如果要生成 Windows 安装程序，需要安装
[Inno Setup 6](https://jrsoftware.org/isdl.php)，在项目目录执行：

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" .\installer.iss
```

默认安装程序会生成在 `installer` 目录。安装后 `tools` 和 `data` 位于应用目录，
工具附件应与安装包一起安装，不要只复制主 EXE。

## 数据与备份

`data/settings.json`、`data/presets.json` 和 `data/projects` 是本机运行设置及用户数据，
不随源码仓库提交。更换电脑时，如有需要，请另行备份这些文件。

