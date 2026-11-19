# SomePhylloscopus 发布与版本检查

「某种柳莺」在首页右下角显示本机版本。点击版本按钮打开「版本与更新」，可以手动查最新正式版。配置完整后，启动时在后台查询，24 小时内已有查询记录时跳过自动查询。发现新版本后，按钮显示「有更新」，发布页里的说明和下载地址由维护者提供，用户自己选择何时更新。

## 发布前填写

修改应用目录中的 `config/release.json`。开发目录与便携版各有一份，准备发布时要同步。

```json
{
  "version": "0.1.0",
  "github_repository": "你的GitHub账号/SomePhylloscopus",
  "check_on_startup": true
}
```

- `version` 是安装包自身的版本。每次发布时填写实际版本，例如 `0.2.0`，并让 GitHub Release 使用对应标签 `v0.2.0`。
- `github_repository` 填实际 GitHub 账号或组织与仓库名。正式版使用 `mmax911110-lgtm/SomePhylloscopus`。应用通过 GitHub 的 `releases/latest` 链接查正式版。[GitHub 发布链接说明](https://docs.github.com/en/repositories/releasing-projects-on-github/linking-to-releases)
- `check_on_startup` 控制启动时的自动查询。设为 `false` 时，仍可在界面点击「立即检查」。

## 发出正式版

1. 从准备公开的代码提交创建版本标签，并在 GitHub Releases 发布相同标签的正式版。将它标记为该仓库的最新版本。草稿、预发行版或单独推送的 Git 标签不会出现在正式版查询中。[GitHub 发布说明](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
2. 在 Release 说明里给出更新内容及 Windows 便携包的下载入口。v0.1.0 使用分件和一个 Windows 下载器。下载器校验每个分件、合并 ZIP，再校验整包。GitHub Releases 要求每个上传文件小于 2 GiB。[GitHub Release 文件限制](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases#storage-and-bandwidth-quotas)
3. 用旧版点击「立即检查」，确认界面显示新标签、链接指向对应 Release。再用新版查一次，确认显示当前已是最新。

此版本的检查器使用 Python 标准库读取公开发布信息，按数字比较版本，例如 `0.10.0` 高于 `0.9.9`。发布入口的安排参考了 KeePassXC 的界面实现。[KeePassXC 主窗口源码](https://github.com/keepassxreboot/keepassxc/blob/develop/src/gui/MainWindow.cpp)
