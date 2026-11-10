# GitHub 上传教程（新手向）

这篇教程假设你：

- 没传过 GitHub；
- 不太会写代码；
- 只想把这个项目公开出去，顺便学会以后怎么更新。

先说结论：**你要上传的是 `invoice2rkd-public` 这个文件夹里的内容，不是整个 `Default Project`，也不是你的发票文件夹。**

---

## 0. 先搞清楚：什么能传，什么不能传

### 可以传

- `app.py`
- `invoice2rkd/` 源码
- `data/completions.json`
- `tools/`
- `docs/`
- `examples/示例-入库单.xls`（纯虚构数据）
- `requirements.txt`
- `README.md`
- `LICENSE`
- `.gitignore`
- `使用说明.txt`
- `build.ps1` / `run.cmd`

### 绝对不要传

- 任何真实发票 PDF / 图片
- 生成的入库单 `.xls`
- `data/catalog.json`（里面有公司供应商/项目历史）
- `示例输出/`
- `dist/`、`build/`（exe 和打包中间文件）
- 公司合同、报价、客户名单
- 任何带 API Key、密码、内网地址的文件

> 公开仓库 = 全世界都能看到。先在本地把敏感文件删掉/移走，再上传。

---

## 1. 注册 GitHub

1. 打开 https://github.com
2. 点右上角 **Sign up**。
3. 填邮箱、密码、用户名（用户名会成为仓库地址的一部分，建议用英文，例如 `imen`）。
4. 完成邮箱验证。
5. 建议在 **Settings → Password and authentication** 打开两步验证（2FA）。

---

## 2. 方式 A：网页上传（第一次最省事）

适合：不想装 Git、项目文件不多。

### 2.1 新建仓库

1. 登录后点右上角 **+** → **New repository**。
2. 填写：
   - **Repository name**：`invoice2rkd`（或 `invoice-to-excel`）
   - **Description**：`扫描发票 PDF/图片 → 入库单 Excel（离线 OCR）`
   - 选择 **Public**（公开）或 **Private**（私有；只有你和邀请的人能看）
   - 不要勾选 “Add a README file”“Add .gitignore”“Choose a license”，因为本地已经准备好了。
3. 点 **Create repository**。

### 2.2 上传文件

1. 在新仓库页面，点 **uploading an existing file**。
2. 打开资源管理器，进入：
   ```
   C:\Users\imen_\Documents\Default Project\invoice2rkd-public
   ```
3. 按 `Ctrl+A` 选中里面**所有文件和文件夹**（注意：不要选中 `invoice2rkd-public` 这一层文件夹本身）。
4. 把这些内容拖到浏览器的上传区域。
5. 等文件列表出现，确认包含：
   - `README.md`
   - `LICENSE`
   - `requirements.txt`
   - `invoice2rkd/`
   - `docs/screenshot.png`
   - `docs/GitHub上传教程.md`
   - `examples/示例-入库单.xls`
6. 在下方 **Commit changes** 填：
   ```
   Initial commit: 扫描发票转入库单生成器
   ```
7. 点 **Commit changes**。

> `.gitignore` 是隐藏文件。如果上传列表里没有它，在资源管理器里打开“查看 → 显示 → 隐藏的项目”，再重新拖一次；或者后面用 GitHub 网页“Add file → Create new file”新建 `.gitignore`，把本地内容复制进去。

### 2.3 检查

打开仓库首页，应该能看到 README 和截图。点进 `invoice2rkd/` 能看到源码。

---

## 3. 方式 B：GitHub Desktop（以后更新最方便）

第一次网页上传完成后，建议装 GitHub Desktop，以后改代码/改文档用它。

### 3.1 安装

1. 打开 https://desktop.github.com
2. 下载安装 GitHub Desktop。
3. 打开后用 GitHub 账号登录。

### 3.2 把仓库克隆到本地

1. GitHub 网页打开你的仓库。
2. 点绿色 **Code** → **Open with GitHub Desktop**。
3. GitHub Desktop 会弹出克隆窗口，选一个本地目录，例如：
   ```
   C:\Users\imen_\Documents\GitHub\invoice2rkd
   ```
4. 点 **Clone**。

### 3.3 修改并上传

1. 把 `invoice2rkd-public` 里改好的文件复制到刚克隆的目录（覆盖同名文件）。
2. GitHub Desktop 左侧会显示改动文件。
3. 在左下角填 Commit message，例如：
   ```
   更新 README 和拖拽说明
   ```
4. 点 **Commit to main**。
5. 点右上角 **Push origin**。

以后每次改完，重复“复制 → Commit → Push”。

---

## 4. 方式 C：命令行（可选）

如果你已经装了 Git，可以在 `invoice2rkd-public` 目录执行：

```powershell
git init
git add .
git commit -m "Initial commit: 扫描发票转入库单生成器"
git branch -M main
git remote add origin https://github.com/<你的用户名>/invoice2rkd.git
git push -u origin main
```

以后更新：

```powershell
git add .
git commit -m "说明这次改了什么"
git push
```

> 不会命令行也没关系，用方式 A + B 就够了。

---

## 5. 上传便携版 exe（Release）

exe/zip 体积较大，**不要放到仓库文件里**，放 GitHub 的 **Releases**。

1. 先准备好公开版压缩包：
   ```
   C:\Users\imen_\Documents\Default Project\invoice2rkd-release\入库单生成器-便携版.zip
   ```
   这个包是从公开源码打的，不带公司历史库。以后重新打包后，zip 会生成在 `invoice2rkd-public\dist\`，把它复制到 `invoice2rkd-release` 或直接上传即可。
2. 打开你的 GitHub 仓库，点右侧 **Releases** → **Draft a new release**。
3. 填写：
   - **Choose a tag**：`v1.2.0`，点 **Create new tag**
   - **Release title**：`v1.2.0 电子票文字层 + 扫描OCR双路径`
   - **Describe this release**：写更新内容（可以复制 `CHANGELOG.md`）
4. 把 `入库单生成器-便携版.zip` 拖到 **Attach binaries** 区域。
5. 点 **Publish release**。
6. 回到仓库首页，README 里可以加一句“下载见 Releases”。

> GitHub 单个 Release 附件支持到 2GB；但普通仓库单文件超过 100MB 会被拒绝。zip 不要 commit。

---

## 6. 给仓库加一点门面

在仓库首页右侧点齿轮 **About**：

- **Description**：`扫描发票 PDF/图片 → 入库单 Excel（离线 OCR）`
- **Website**：可以不填
- **Topics**：`invoice`, `ocr`, `excel`, `python`, `tkinter`, `chinese`, `invoice-recognition`

这样别人搜索/点进来更容易看懂。

---

## 7. 以后怎么更新

### 只改文档/README

- 直接在 GitHub 网页打开文件 → 铅笔图标编辑 → Commit changes。
- 或者用 GitHub Desktop：改本地文件 → Commit → Push。

### 改了代码

1. 本地测试：
   ```powershell
   python -m compileall invoice2rkd app.py
   python tests/test_basic.py
   ```
2. 重新打包公开版：
   ```powershell
   cd C:\Users\imen_\Documents\Default Project\invoice2rkd-public
   powershell -ExecutionPolicy Bypass -File build.ps1
   ```
3. 把源码改动同步到 GitHub（方式 B/C）。
4. 新建一个 Release（例如 `v1.2.1`），上传新的 zip。

---

## 8. 新手最容易踩的坑

### 坑 1：把整个 `Default Project` 传上去了

里面可能有发票、客户资料、其他项目。**只传 `invoice2rkd-public` 里面的内容。**

### 坑 2：把 `data/catalog.json` 传上去了

里面有公司供应商/项目历史。公开仓库不要带；`.gitignore` 已经排除，但网页上传时要自己看清。

### 坑 3：把 exe/zip commit 进仓库

仓库单文件超过 100MB 会失败；即使没超，也会让仓库很臃肿。exe/zip 放 **Releases**。

### 坑 4：公开后才发现有敏感信息

- 立即删除文件并 commit；
- 但 Git 历史里仍可能保留。最稳妥是删除仓库重建，或联系 GitHub Support 清理；
- 如果泄露了密码/API Key，立刻更换。

### 坑 5：GitHub Desktop 提示“not a Git repository”

说明这个文件夹还没初始化 Git。最简单的做法：先按“方式 A”在网页建仓库并上传，再用 GitHub Desktop **Clone** 下来，不要直接在原文件夹里瞎点。

### 坑 6：中文文件名/路径

GitHub 支持中文文件名；但为了少出问题，仓库名、分支名、命令里的路径尽量用英文。`docs/GitHub上传教程.md` 这种中文文件名没问题。

### 坑 7：别人下载 exe 被 SmartScreen 拦截

正常。说明里写清楚“未签名，首次运行请允许”。不要建议用户关闭杀毒软件。

---

## 9. 发布前检查清单

- [ ] `invoice2rkd-public` 里没有真实发票/生成的 xls
- [ ] 没有 `data/catalog.json`
- [ ] 没有 `dist/`、`build/`
- [ ] `README.md` 截图能显示
- [ ] `LICENSE` 里的版权人/年份你确认过
- [ ] `data/company.json` 的 `title`/`buyer` 你确认过（公开版默认是“入库单 / 购买方公司名称”）
- [ ] `requirements.txt` 能安装
- [ ] `python tests/test_basic.py` 通过
- [ ] 公开版 exe 能在另一台电脑/另一个目录启动
- [ ] Release 里上传的是公开版 zip，不是带公司历史库的内部版
- [ ] 仓库是 Public 还是 Private 你确认过
- [ ] 没有 API Key、密码、内网地址

---

## 10. 你现在的文件在哪

- 要上传的源码：`C:\Users\imen_\Documents\Default Project\invoice2rkd-public`
- GitHub 公开版便携包：`C:\Users\imen_\Documents\Default Project\invoice2rkd-release\入库单生成器-便携版.zip`
- 你日常用的内部版（带历史学习库）：`C:\Users\imen_\Documents\Default Project\invoice2rkd`

如果还有不确定的，先把仓库设成 **Private**，自己点一遍确认没问题，再改 Public。
